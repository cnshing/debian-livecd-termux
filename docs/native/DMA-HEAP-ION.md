# `/dev/dma_heap` on top of `/dev/ion`

Results of the handoff [handoff/dmabuf-s20.md](handoff/dmabuf-s20.md), merged in PRs #12–#14.
State on 2026-11-15.

## What exists

- `packages/android-vaapi/dma-heap.c` builds `libandroid-dma-heap.so`:
  - for Bionic in android-vaapi (27.0.0~devel20261029-6);
  - for glibc in android-vaapi-glibc (27.0.0~devel20261025-2, `lib/`).
- Each package's manifest names it as `dma_heap_preload`.
- `acceleration.video_environment` adds it to the video preloads (`LD_PRELOAD` or
  `BIONILUX_EXTRA_PRELOAD`) only when `/dev/dma_heap` is absent, `/dev/ion` is present and
  `LIVECD_DMA_HEAP_ION` is not `0`.
- **The bridge refactor.** Both VA bridges (`tva_ion_winsys.h`, `configure-bridge.py`) allocate
  only through `/dev/dma_heap/system`. They no longer have their own ION code:
  - `tva_ion.h` is removed;
  - the glibc `ion-dma-heap.c` preload is removed, and so is `LIVECD_TVA_ION_FALLBACK` in the
    shared launcher.
- **Not changed:**
  - the older standalone Chrome wrapper path in `overlays/Browser+Chromium/browsers/google-chrome`
    keeps its own adapter;
  - `prebuilt/native-video` keeps its own copy;
  - the desktop session (`graphics.py`) does not load the preload. PanVK already falls back to
    ION by itself, and loading the preload there would change its HOST_COHERENT memory (see
    below).
- It presents `/dev/dma_heap/system` and `/dev/dma_heap/system-uncached`, which are character
  devices to `stat`/`access`. `DMA_HEAP_IOCTL_ALLOC` turns into ION's 4.12+ `ION_IOC_ALLOC`.
- Heap choice follows Android's
  [libdmabufheap](https://android.googlesource.com/platform/system/memory/libdmabufheap/)
  (`BufferAllocator::QueryIonHeaps`):
  - `system` uses `ion_system_heap` with `ION_FLAG_CACHED`;
  - `system-uncached` uses the same heap with no flags;
  - when no heap has that name, the first heap of type `ION_HEAP_TYPE_SYSTEM` is used.
- It does nothing when a real `/dev/dma_heap` exists, when `/dev/ion` is missing, or when
  `LIVECD_DMA_HEAP_ION=0` is set. With no ION system heap, `open` fails with `ENOENT`.
- Host test: `tests/dma-heap/test-dma-heap.sh`, 9 cases against a fake ION device
  (`fake-ion.c`).

## S20 results (x1s, Linux 4.19.87, no root), 2026-11-15

ION heaps from `tests/dma-heap/ion-probe.c`:

| id | type | name |
| --- | --- | --- |
| 0 | 0 system | ion_system_heap |
| 1 | 2 carveout | camera_heap |
| 2 | 2 carveout | npu_fw |
| 3 | 4 dma | vstream_heap |
| 4 | 4 dma | crypto_heap |
| 5 | 2 carveout | secure_camera_heap |
| 6–10 | 5 custom | vfw_heap, vnfw_heap, vframe_heap, vscaler_heap, gpu_buffer |

- Raw ION, without the preload: cached and uncached allocations of 4 KiB, 1 MiB and 64 MiB all
  pass, each with `mmap` and a `DMA_BUF_IOCTL_SYNC` start/end round trip.
- Through the preload, `tests/dma-heap/heap-client.c` uses only the heap API:
  - `system` and `system-uncached` at all three sizes: ok;
  - each run covers open, alloc, the `O_CLOEXEC` flag on the fd, rejection of bad flags,
    `ENOTTY` for other ioctls, `mmap`, the pattern read back in a second process over
    `SCM_RIGHTS`, and alloc on a `dup` of the heap fd.
- Control: without the preload, and with `LIVECD_DMA_HEAP_ION=0`, the client fails at `stat`
  with `ENOENT`, so the test does exercise the preload.
- Bionic calls libc wrappers before library constructors run, so every forwarded call resolves
  its next definition on first use. The first build resolved them in the constructor and
  segfaulted on start-up, even with emulation disabled.

## Through the bridge and in Firefox (S20, CI run 43672564405, staged privately)

Nothing was installed for these checks. The packages were unpacked under `~/gpu-x1s/dma-heap/vaapi-6`, and
private copies of `src/native` were used.

- **FFmpeg VA-API decode against a private daemon** (`~/gpu-x1s/dma-heap/decode-check.py`, a
  copy of `hevc-latency.py`): VP9 and HEVC each give 48 of 48 frames bit-identical to software
  decoding.
  - With the preload, the bridge logs `tva: software backend on dma-buf surfaces`.
  - With `LIVECD_DMA_HEAP_ION=0`, it falls back to the null winsys, with plain memory and no
    export. So ION is now reached only through the preload.
- **Firefox on Zink/PanVK, private Termux:X11 `:84`** (`firefox-dmaheap-race.py`):

  | Run | VA-API frames | Browser PSNR (frames 12, 36) | Result |
  | --- | --- | --- | --- |
  | VP9, preload | 59 | 47.96 / 48.00 dB | ok |
  | HEVC, preload | 61 | 48.01 / 47.98 dB | ok (the first try timed out starting the private display; the retry passed) |
  | VP9, `LIVECD_DMA_HEAP_ION=0` | 0, software decode | 39.98 / 39.95 dB | fails as it should |

  The frame captures are in `~/gpu-x1s/browser-tests/race-dh-*` on the phone. The FFmpeg check
  is the frame-exact one.
- **Vulkan import** (`tests/dma-heap/vk-import.c`), PanVK on the Mali-G77, for both `system`
  and `system-uncached`:
  - a heap buffer is imported with `VK_EXT_external_memory_dma_buf`;
  - the GPU reads data the CPU wrote, and the CPU reads the GPU's fill and copy;
  - without the preload, the test fails at `open`.

## PanVK's own ION fallback

Zenith's `patches/jm-v7/005-kbase-ion-fallback-for-placed-map-dma-buf.patch` already does
heap-then-ION in `kbase_kmod.c`:

- it uses the first system-type ION heap, with `ION_FLAG_CACHED`;
- its log line is `kbase: using ION system heap, mask 0x%x`;
- the built driver, both the Bionic and the glibc copy, contains these strings.

So PanVK does not need the preload for shareable BOs. With the preload loaded, PanVK opens
`/dev/dma_heap/system` and ends up with the same ION allocation, so the two do not conflict.

**One behaviour change to test before the launcher loads the preload:** the GPU is not
IO-coherent, so PanVK asks for `/dev/dma_heap/system-uncached` for HOST_COHERENT memory.

- Today that open fails, and PanVK cleans imports before each submit.
- With the preload, PanVK would get uncached ION memory instead.
- Test CPU-write/GPU-read and the reverse, and rerun the desktop and Ghostty checks, before
  enabling it.

## Left

- **Note10+ regression run.** It is also ION-only, so its bridge now depends on the preload.
  It has not been run.
- **The desktop session through the preload**, which changes PanVK's HOST_COHERENT memory to
  uncached ION. It needs the desktop and Ghostty checks before `graphics.py` loads it.
- `opendir("/dev/dma_heap")` listing is not emulated yet.
