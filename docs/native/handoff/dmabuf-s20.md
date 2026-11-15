# Handoff: DMA-BUF support on the S20, with ION fallback

State on 2026-11-14. Galaxy S20 (`x1s`, SM-G981B), Exynos 990, Mali-G77, Android 13, Linux
4.19.87, stock kernel, no root. For whoever takes this on as a dedicated project. It stands on
its own; the other pages in this folder are linked where they matter.

## Goal

Every program that expects Linux DMA-BUF video and graphics buffers gets them on the S20, as it
would on a Linux desktop. Each buffer comes from an allocator the Termux app is allowed to use,
and the ION fallback works wherever there is no DMA-BUF heap.

"Done" means:

- Programs can allocate, export, import and synchronise DMA-BUFs with each other, with no CPU copy
  that a desktop would not make.
- Chrome's WebCodecs hardware encode runs without a source patch.
- Each step has a phone test that fails when the DMA-BUF path is not taken.

## Why this is its own project

Chrome's WebCodecs hardware encode crashes on the S20 ([encode-chrome.md](encode-chrome.md)):

- On Linux, Chrome's encoder adapter always asks for GPU-memory-buffer input. This is compiled
  in (`media/video/video_encode_accelerator_adapter.cc`, under `#if BUILDFLAG(IS_LINUX)`), with
  no flag to turn it off.
- The GPU process then `CHECK`s that each buffer is a native pixmap: a DMA-BUF that Chrome
  allocated through GBM.
- On Termux, Chrome has no working GBM device, so its buffers are shared memory and the check
  aborts the GPU process.

Chromium avoids this with source patches 0100 and 0101 (`packages/chromium`). Chrome is Google's
binary and cannot be patched. The real fix is to give Chrome what it expects: GBM, native pixmaps
and DMA-BUF import all the way down. That touches the allocator, Mesa, the X server, the GPU
driver and the VA-API bridge, so it is a project of its own, not a bridge fix.

## What the phone allows

Checked on the S20 on 2026-11-14:

| Node | State |
| --- | --- |
| `/dev/ion` | present, `crw-rw-rw- system system u:object_r:ion_device:s0` |
| `/dev/dma_heap` | absent; Linux 4.19 predates DMA-BUF heaps |
| `/dev/dri/*` | absent to the app; the phone's display nodes are denied by SELinux |
| `/dev/mali0` | read/write for the Termux app |

So on the S20, **ION is the only kernel DMA-BUF allocator**, not a fallback. Phones on GKI
5.10+ kernels have the opposite: `/dev/dma_heap/system` and no `/dev/ion`. The code must try
the DMA-BUF heap first, then ION, everywhere it allocates.

[docs/browsers/android-video-allocators.md](../../browsers/android-video-allocators.md) has the
full permission probe from the Note10+: ION opened read-only can still allocate, `ASharedMemory`
is not a DMA-BUF, and `AHardwareBuffer` works. That probe **has not been run on the S20**.

## What already exists

| Piece | Where | State on the S20 |
| --- | --- | --- |
| ION allocator (system heap, opened read-only) | `packages/android-vaapi/tva_ion.h` | Used; Bionic built-in, glibc via preload (`ion_fallback` in each package's manifest, `LIVECD_TVA_ION_FALLBACK` in `src/native/acceleration.py`) |
| Software-renderer surfaces held in DMA-BUFs (heap first, then ION) | `packages/android-vaapi/tva_ion_winsys.h` | Used; `TERMUX_VA_ION_WINSYS=0` turns it off |
| VA surface export (`vaExportSurfaceHandle`, DRM PRIME) | the same | Works: Chromium, Chrome and Firefox import decoded VP9/HEVC frames |
| A fake `/dev/dri/renderD128` that answers DRM version and PRIME capability queries | `packages/android-vaapi/render-node.c` | Used on Mali; reports driver name `termuxva` |
| PanVK (kbase) memory export | `mesa-vulkan-icd-panvk-kbase` | Exports ION-backed DMA-BUFs ([MALI-GPU-STATUS.md](../MALI-GPU-STATUS.md)) |
| Zink import of a DMA-BUF without SYNC_FD | Mesa patches 0021–0023, revision 103 | Firefox imports decoded frames |
| SYNC_FD semaphores in PanVK | [PANVK-SYNC-FD-HANDOFF.md](../PANVK-SYNC-FD-HANDOFF.md) | Ported and qualified privately for Ghostty → GTK only; not in the general driver |
| X11 presentation | `src/native/graphics.py` | MIT-SHM is the accepted path; raw DRI3 is a probe only |
| GBM | Mesa is built with `-Dgbm=enabled` | **Not checked** whether `gbm_bo_create` works on Mali; probably not, since there is no kbase GBM backend |

## The gaps, by where a buffer travels

1. **Decode output: one CPU copy.** The termux-va daemon gets each decoded frame from MediaCodec
   as a byte buffer over shared memory. The bridge then copies it into an ION surface (on Mali
   `TERMUX_VA_GPU_BACKEND=sw`). Zero copy would mean MediaCodec decoding to an `ANativeWindow`
   (from `AImageReader`) and the bridge wrapping each `AHardwareBuffer`'s DMA-BUF as the VA
   surface. That needs the Samsung gralloc layout (plane offsets, strides, AFBC or linear), the
   buffer lifetime and fences. None of that has been probed on the S20.
2. **Encode input: import not checked.** No test has confirmed that a DMA-BUF made outside the
   bridge can be imported as a VA surface (`vaCreateSurfaces` with
   `VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2`) and encoded. Programs that need this:
   - Chrome (native pixmaps);
   - FFmpeg `hwmap`/`hwupload` from DRM frames;
   - GStreamer `va` elements with `memory:DMABuf` caps;
   - screen capture.
   The encode input is also copied into MediaCodec's input buffer; MediaCodec's input surface
   (`AMediaCodec_createInputSurface`) would avoid that.
3. **GBM on Mali.** Chrome's Ozone X11 allocates native pixmaps through GBM on the render node.
   On the S20 that render node is the fake one above, and Mesa has no GBM backend that
   allocates from kbase or ION. One option is a GBM backend (in Mesa or a preload) whose
   `gbm_bo_create` allocates heap-then-ION, or an `AHardwareBuffer`, and exports its fd. Check in
   Chrome's source which GBM entry points and formats it actually needs (`ui/gfx/linux`,
   `ui/ozone/platform/x11`) before building anything.
4. **X11 native pixmaps.** Chrome decides whether native pixmaps are supported partly from the
   X server: DRI3 and its modifiers. Termux:X11 offers DRI3 on the Adreno path
   (`TERMUX_VA_X11_DRI3`). On Mali it has only been probed.
5. **The GPU writing and reading the same buffers.** Chrome's GPU process (ANGLE on PanVK)
   must import the GBM buffers and draw into them. PanVK exports ION memory, but importing
   *foreign* DMA-BUFs (from GBM or `AHardwareBuffer`) into PanVK and into Zink is not tested.
6. **Synchronisation.** Without SYNC_FD in the general PanVK driver, every cross-process handoff
   relies on the Zink workarounds or on `DMA_BUF_IOCTL_SYNC` CPU brackets. Moving the
   Ghostty-qualified SYNC_FD port into the default driver is part of this work.
7. **Making the fallback order explicit everywhere.** Each new allocator (GBM, `AHardwareBuffer`
   wrapping, any PanVK allocation path that bypasses kbase export) must try the DMA-BUF heap
   first, then ION, then fail clearly. It must never fall back silently to shared memory that
   looks like success. Bionic and glibc builds need the same order (built-in and
   `ion_fallback: preload`).

## Order of work

Each step ends with a phone test; don't start the next step until it passes.

1. **Probe the S20** with a small native program, run as the Termux app and through `adb shell`:
   - The ION heap list and IDs, and whether a system-heap allocation can be mapped and
     `DMA_BUF_IOCTL_SYNC`'d.
   - `AHardwareBuffer_allocate` for NV12/YUV420 and RGBA:
     - how many fds the native handle carries;
     - which fd holds which plane, and the strides;
     - whether the buffer is AFBC-compressed or linear.
   - `gbm_create_device` on the fake render node and `gbm_bo_create` for `GBM_FORMAT_NV12`
     and `GBM_FORMAT_ARGB8888`. Record the result, including failures.
   - Importing an ION allocation and an `AHardwareBuffer` fd into PanVK
     (`VK_EXT_external_memory_dma_buf`) and into Zink (`EGL_EXT_image_dma_buf_import`).
   Write the results into this page.
2. **VA import and encode from a DMA-BUF.** Make
   `vaCreateSurfaces(..., VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2)` work in the bridge for
   heap/ION buffers, then encode from them.
   - Test: FFmpeg `-init_hw_device vaapi ... -vf hwmap` from a DRM frame, and GStreamer
     `vah264enc` fed `video/x-raw(memory:DMABuf)`.
   - Decode the output with software and look at the frames.
3. **GBM for Mali.** Add a GBM backend or preload that allocates heap-then-ION, or
   `AHardwareBuffer` if step 1 shows linear layouts. Choose which from step 1's data.
   - Test: allocate, map, write a pattern, export, re-import in another process, and compare.
4. **DRI3 on Termux:X11 for PanVK.** Present a DMA-BUF-backed pixmap from PanVK and from a GBM
   buffer.
   - Test: a numbered-frame window captured on a private Xvfb/Termux:X11 display. Look at the
     pictures, not only checksums.
5. **SYNC_FD in the default PanVK driver.** Land the port from
   [PANVK-SYNC-FD-HANDOFF.md](../PANVK-SYNC-FD-HANDOFF.md).
   - Rerun the desktop, Ghostty and all three browser tests.
   - Drop Mesa 0021–0023 only once their crashes no longer reproduce without them.
6. **Chrome WebCodecs hardware encode, unpatched.** Run Chrome with `AcceleratedVideoEncoder`
   and native GPU memory buffers on.
   - Test: the WebCodecs H.264 and VP9 runs from [encode-chromium.md](encode-chromium.md). They
     must have no GPU-process exit and must show the encoder name `OMX.Exynos.*`. Decode the
     stream and view frames 0, middle and last.
   - When it passes, propose enabling `AcceleratedVideoEncoder` for Chrome; the user decides.
7. **Zero-copy MediaCodec** (gap 1 and the input surface in gap 2), only if step 1 shows the
   gralloc layout can be wrapped:
   - Measure CPU use and frame time against the copying path.
   - Keep the copying path as the fallback.
8. **Fallback coverage.** Host tests that force each allocator:
   - DMA-BUF heap missing;
   - ION missing;
   - both missing, which must report an error rather than fall back to shared memory;
   - `TERMUX_VA_ION_WINSYS=0`.
   Then one Adreno regression run on the Note10+, whose allocator rules differ (see
   android-video-allocators.md).

## Rules for phone work

- Claim `temp/PHONE-STATUS` before using the S20 and release it after. Other sessions share
  the phone.
- Private Xvfb or private Termux:X11 display only. Never send input to the live `:0`.
- Never kill processes you did not start. Stage packages privately (as encode-chromium did in
  `~/gpu-x1s/`) rather than installing, unless the user asks.
- Granting Termux permissions in Android Settings kills all Termux processes. Use `adb shell`
  grants, and warn first.
- No root, no kernel changes, no SELinux changes. Everything must work for an unprivileged app.

## Out of scope

- Protected (secure) ION heaps and DRM-protected video.
- Camera buffers as DMA-BUFs (android-camera); a natural follow-up once step 3 exists.
- AV1: the S20 has no AV1 hardware.
