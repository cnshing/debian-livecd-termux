# Handoff: `/dev/dma_heap` on top of `/dev/ion`, for kernels without DMA-BUF heaps

**Completed 2026-11-15.** Merged to main in PRs #13 and #14. The full results are in
[DMA-HEAP-ION.md](../DMA-HEAP-ION.md). The original plan is in Git history.

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
| 4. Bridge and browsers | FFmpeg VP9/HEVC 48 of 48 frames bit-exact. Firefox VP9/HEVC in hardware. Chrome WebRTC encode and VP9/HEVC playback through the glibc preload. Chromium revision 3 VP9/HEVC playback and WebCodecs/WebRTC encode through the Bionic preload. With `LIVECD_DMA_HEAP_ION=0`, the bridge falls back to software (Firefox, FFmpeg) and Chromium falls back to `VpxVideoDecoder`, as they must |
| 5. Installed run | `android-vaapi` 11 and `android-vaapi-glibc` 3 installed on the S20: desktop check 30 of 30, Chrome and Firefox VP9/HEVC pass |

PanVK needed no change: Zenith's JM patch 005 already falls back to ION itself.

## Not done, by decision or for lack of a phone

- **The desktop session (`graphics.py`) does not load the preload.** With it, PanVK's
  HOST_COHERENT memory would become uncached ION. That needs the desktop and Ghostty checks
  first, and nothing needs it today.
- **Note10+ regression run.** It is ION-only too, so its bridge now depends on the preload. It
  has not been run there.
- `opendir("/dev/dma_heap")` listing is not emulated. Nothing found so far needs it.

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
