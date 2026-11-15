# Handoff: `/dev/dma_heap` on top of `/dev/ion`, for kernels without DMA-BUF heaps

**Completed 2026-11-15.** Merged to main in PRs #13 and #14. The full results are in
[DMA-HEAP-ION.md](../DMA-HEAP-ION.md). The plan below is kept as the record of what was asked.

## Outcome

- `packages/android-vaapi/dma-heap.c` builds `libandroid-dma-heap.so`, for Bionic in
  `android-vaapi` and for glibc in `android-vaapi-glibc`. It presents `/dev/dma_heap/system`
  and `/dev/dma_heap/system-uncached` and turns `DMA_HEAP_IOCTL_ALLOC` into ION's
  `ION_IOC_ALLOC`. Heaps are chosen the way Android's libdmabufheap chooses them.
- `src/native/acceleration.py` loads it only when `/dev/dma_heap` is absent and `/dev/ion` is
  present. `LIVECD_DMA_HEAP_ION=0` turns it off. It replaced `LIVECD_TVA_ION_FALLBACK`.
- Both VA-API bridges now allocate only through the heap. `tva_ion.h` and the glibc
  `ion-dma-heap.c` preload are removed.

| Step | Result on the S20 |
| --- | --- |
| 1. Probe | ION heap list recorded; system heap ID 0. Raw ION at 4 KiB, 1 MiB and 64 MiB, cached and uncached, with `mmap` and a sync round trip: pass |
| 2. Preload with host tests | `tests/dma-heap/test-dma-heap.sh`, 9 cases against a fake ION device: pass |
| 3. Standalone | heap-API client with a second process over `SCM_RIGHTS`: pass. Vulkan dma-buf import on PanVK, both heaps: pass. Fails without the preload, as it must |
| 4. Bridge and browsers | FFmpeg VP9/HEVC 48 of 48 frames bit-exact. Firefox VP9/HEVC in hardware. Chrome WebRTC encode and VP9/HEVC playback through the glibc preload. With `LIVECD_DMA_HEAP_ION=0`, the bridge falls back to software, as it must |
| 5. Installed run | `android-vaapi` 11 and `android-vaapi-glibc` 3 installed on the S20: desktop check 30 of 30, Chrome and Firefox VP9/HEVC pass |

PanVK needed no change: Zenith's JM patch 005 already falls back to ION itself.

## Not done, by decision or for lack of a phone

- **The desktop session (`graphics.py`) does not load the preload.** With it, PanVK's
  HOST_COHERENT memory would become uncached ION. That needs the desktop and Ghostty checks
  first, and nothing needs it today.
- **Note10+ regression run.** It is ION-only too, so its bridge now depends on the preload. It
  has not been run there.
- **Chromium** on the S20 waits for the revision 3 CI build.
- `opendir("/dev/dma_heap")` listing is not emulated. Nothing found so far needs it.

The follow-ups that build on the heap are listed below under "Built on top of this".

## The task

Make `/dev/dma_heap/system` appear to exist on kernels that predate DMA-BUF heaps, with ION
(`/dev/ion`) doing the actual allocating.

- Programs and drivers written for DMA-BUF heaps then work unchanged.
- The buffers they get are real DMA-BUFs. Only the allocator interface is emulated.

Why this is enough:

- An ION allocation already returns a genuine DMA-BUF file descriptor. Import into the GPU,
  `mmap`, `DMA_BUF_IOCTL_SYNC` and passing it to another process all work on it today; the
  video bridge's decoded frames are ION buffers that every browser imports.
- What 4.19 lacks is the interface, `/dev/dma_heap/<name>` with `DMA_HEAP_IOCTL_ALLOC`. That was
  added in Linux 5.6, and Android moved to it from ION.
- Newer GKI kernels are the reverse: DMA-BUF heaps and no ION. So "heap first, ION as the
  fallback" is the order everything should follow. Today that order is implemented separately
  in each component (below). This task puts it in one place.

What the S20 offers (checked 2026-11-14):

| Node | State |
| --- | --- |
| `/dev/ion` | present, `crw-rw-rw- system system u:object_r:ion_device:s0` |
| `/dev/dma_heap` | absent |
| `/dev/dri/*` | not visible to the app (SELinux) |
| `/dev/mali0` | read/write for the Termux app |

## Who allocated before this work (2026-11-14)

| Component | Heap | ION | Other |
| --- | --- | --- | --- |
| VA-API bridge surfaces, `packages/android-vaapi/tva_ion_winsys.h` | first | then ION via `tva_ion.h` (system heap, `/dev/ion` opened read-only) | — |
| glibc bridge for Chrome, `android-vaapi-glibc` | same | through a preload (`ion_fallback: preload`, `LIVECD_TVA_ION_FALLBACK` in `src/native/acceleration.py`) | — |
| PanVK kbase shareable buffers (`kbase_kmod.c`) | `/dev/dma_heap/system`, overridable with `PANVK_KBASE_DMA_HEAP` | Zenith's later JM patch 0133 says it handles a "new-ABI ION heap" | gralloc `AHardwareBuffer` BLOB as the last resort (patch 0133); otherwise an ordinary kbase buffer that cannot be shared |
| Zenith patch 0129 | asks for the `system-uncached` heap for HOST_COHERENT memory | — | — |
| GBM, Chrome, GStreamer, FFmpeg DRM frames | expect a render node or a heap; nothing on the S20 | — | — |

**To confirm first:** which of these paths the pinned 26.3.1 release actually takes on the
S20. The `kbase_kmod.c` in the pinned tree's `kbase-common` files opens only the DMA-BUF heap;
the ION handling is mentioned in the later JM patches. Run the driver with Mesa debug logging
and look for `kbase: dma-heap unavailable at ...`.

## Design

A small preload library, built for both Bionic and glibc (glibc through Bionilux). It follows
the same pattern as `packages/android-vaapi/render-node.c`, which already fakes
`/dev/dri/renderD128`.

1. **Make the device appear.**
   - `open`/`openat` of `/dev/dma_heap/system` (and `system-uncached`) returns a descriptor on
     `/dev/ion`, opened read-only. Read-only is what works for apps on Android, and is enough
     to allocate.
   - Remember which descriptors are emulated heaps.
   - `stat`/`fstat`/`statx`/`access` and `opendir`/`readdir` of `/dev/dma_heap` report the heaps
     as character devices.
   - Pass everything else through.
2. **Translate the allocation.**
   - `ioctl(fd, DMA_HEAP_IOCTL_ALLOC, struct dma_heap_allocation_data)` on an emulated
     descriptor becomes `ION_IOC_ALLOC`, new ABI (Linux 4.12+):
     - `len` maps directly;
     - `heap_id_mask` is the system heap ID;
     - `flags` is cached for `system` and uncached for `system-uncached`.
   - The returned fd is handed back in `fd`, with `fd_flags` (`O_CLOEXEC`/`O_RDWR`) applied to
     it.
   - Find the heap IDs once with `ION_IOC_HEAP_QUERY` and match them by type: system, not by
     vendor name. Samsung's names and IDs differ from Qualcomm's. Never use carveout, CMA or
     secure heaps.
   - Reuse the query and allocation code in `tva_ion.h` rather than writing it again.
3. **Report failures honestly.**
   - If ION is missing or has no system heap, `open` fails with `ENOENT`, exactly as on a kernel
     without heaps, so callers take their own next fallback.
   - Kernels with ION's legacy ABI (before 4.12), and MediaTek 4.14 kernels where
     `ION_IOC_HEAP_QUERY` returns `EINVAL`, are not handled. They also fail with `ENOENT`, so
     PanVK's gralloc fallback still applies there.
   - Never hand out shared memory or `memfd` that pretends to be a DMA-BUF.
4. **Enable it only where it is needed.**
   - The launcher loads the preload only when `/dev/dma_heap` is absent and `/dev/ion` is
     present. On GKI phones the real heap is used.
   - `LIVECD_DMA_HEAP_ION=0` turns it off.
5. **Then simplify.** Once the preload is in:
   - the bridge's own ION path (`tva_ion.h`, the `ion_fallback` preload) can be removed,
     leaving its heap code as the only path;
   - PanVK's shareable buffers can use the heap on the S20 with no driver change. Keep Zenith's
     gralloc fallback for kernels the preload can't serve.

Known limits:

- A preload only reaches programs that call through libc. Statically linked programs, and
  programs that make raw `syscall()` calls, bypass it. The sandboxed Chrome GPU process is the
  case to test.
- `render-node.c` notes the libc start-up and futex rules a preload must keep; follow them.
- Cache coherency: ION's system heap without the cached flag may differ from Linux's
  `system-uncached`. Test CPU-write then GPU-read, and the reverse, both with and without
  `DMA_BUF_IOCTL_SYNC`.

## Steps, each ending in a phone test

1. **Probe the S20.** Record each result in this page:
   - the ION heap list (IDs, types, names);
   - allocation of 4 KiB, 1 MiB and 64 MiB from the system heap, cached and uncached;
   - `mmap`, and a sync round trip;
   - which allocation path the pinned PanVK release takes.
2. **The preload, with host tests.** A fake ION device, built for Bionic and glibc:
   - each path in the design;
   - `ENOENT` when ION is missing;
   - descriptors that are not emulated pass through unchanged.
3. **The S20, standalone.** A test program that uses only the DMA-BUF heap API:
   - allocates, writes a pattern, passes the fd to a second process over a Unix socket, and
     reads the pattern back there;
   - imports the same fd into PanVK (`VK_EXT_external_memory_dma_buf`), has the GPU write it,
     and checks the result on the CPU.
   - It must fail when the preload is off. That proves the test exercises it.
4. **PanVK and the bridge through the preload.**
   - Run PanVK with the preload and confirm from the log that shareable buffers come from the
     heap.
   - Remove the bridge's own ION path.
   - Rerun the desktop check, Ghostty, and VP9/HEVC decode in Chromium, Chrome and Firefox
     (`tests/browsers/test-acceleration.py`).
   - Look at the decoded frames, not only the scores.
5. **Launcher wiring and a regression run.**
   - Load the preload in `src/native/acceleration.py` and `graphics.py` only on phones without a
     DMA-BUF heap.
   - Run the S20 tests once more from an installed package.
   - Run the Note10+ suite unchanged: it has ION and no heap too, so it uses the preload as well
     (see [android-video-allocators.md](../../browsers/android-video-allocators.md)).

## Built on top of this, not part of this task

These need a working heap first; each is its own follow-up:

- **GBM for Mali**, allocating from the heap: what Chrome's native pixmaps need.
- **DRI3 presentation** of heap buffers on Termux:X11.
- **SYNC_FD** in the default PanVK driver ([PANVK-SYNC-FD-HANDOFF.md](../PANVK-SYNC-FD-HANDOFF.md)).
- **Importing outside DMA-BUFs into the video bridge** for encoding (FFmpeg `hwmap`, GStreamer
  `memory:DMABuf`).
- **Chrome WebCodecs hardware encode without a source patch.** Chrome on Linux requires
  native-pixmap (GBM) input ([encode-chrome.md](encode-chrome.md)), so it needs the three
  items above, not just the heap.
- **Zero-copy MediaCodec** through `AHardwareBuffer`.

## Rules for phone work

- Claim `temp/PHONE-STATUS` before using the S20 and release it after. Other sessions share the
  phone.
- Private Xvfb or private Termux:X11 display only. Never send input to the live `:0`.
- Never kill processes you did not start. Stage packages privately (for example under
  `~/gpu-x1s/`) rather than installing, unless the user asks.
- Check free memory before and between browser runs, and never loop a crashing GPU process:
  Android's low-memory killer has taken down Termux this way before.
- No root, no kernel changes, no SELinux changes. Everything must work for an unprivileged app.
- Out of scope: protected (secure) heaps and DRM-protected video.
