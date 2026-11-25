# Handoff: S20 PanVK presentation with Android hardware buffers

State on 2026-11-24. Not started. Follows [s20-panvk-raw-dri3.md](s20-panvk-raw-dri3.md).
Shared rules: [README.md](README.md).

## Why

The goal of [s20-panvk-raw-dri3.md](s20-panvk-raw-dri3.md) was to stop the CPU copying every
frame. Raw DRI3 did not do that. It moved the copy from the app into the X server, where it reads
uncached ION memory: X server CPU rose from about 14% to 71% during 1080p video, and total CPU
rose by 23–52% ([results](s20-panvk-raw-dri3-results.json)).

The cause is in Termux:X11 (`termux/termux-x11` at `a00942e`, file
`lorie/src/main/cpp/lorie/InitOutput.c`). Nothing below has been measured on the phone yet:

- `loriePixmapFromFds`: a raw fd (`DRM_FORMAT_MOD_LINEAR`, `INVALID` or the private
  `RAW_MMAPPABLE_FD` = 1274, which PanVK sends) is wrapped with
  `LorieBuffer_wrapFileDescriptor`, which `mmap`s it. The server then treats it as CPU memory.
- `lorieExa`: `PrepareSolid`, `PrepareCopy` and `PrepareComposite` are `FalseNoop`, so every
  copy and composite in the X server runs on the CPU (fb), through `loriePrepareAccess` →
  `LorieBuffer_lock`.
- `loriePresentFlip` refuses imported fd buffers unless `TERMUX_X11_FORCE_FLIP=1` ("does not
  work fine with turnip"). So even a fullscreen raw-DRI3 frame is copied, not flipped.
- `lorieDri3Info.fds_from_pixmap` is `FalseNoop`: a compositor cannot get a window's pixmap back
  as a GPU buffer.

Termux:X11 also accepts **AHardwareBuffers**: modifier `AHARDWAREBUFFER_SOCKET_FD` = 1255
(`…_FLIPPED_SOCKET_FD` = 1256 for bottom-up images). The fd is a Unix socket; the server writes
one byte and receives the buffer with `AHardwareBuffer_recvHandleFromUnixSocket`
(`lorieReceiveSocketBuffer`). Allowed formats: `R8G8B8X8_UNORM`, `R8G8B8A8_UNORM`,
`B8G8R8A8_UNORM`. Such a buffer **can** be flipped: the Android activity samples it on the GPU
through `EGL_NATIVE_BUFFER_ANDROID` (`renderer.cpp`), with no CPU copy.

## What AHBs can and cannot save

| Frame | Raw fd today | With AHB |
| --- | --- | --- |
| GNOME Shell's own fullscreen output (root-sized present) | CPU copy into root | flip, no copy (if the flip is accepted) |
| Unredirected fullscreen app (game, fullscreen video) | CPU copy | flip, no copy |
| Windowed app under GNOME Shell | CPU copy into the window pixmap | still a CPU copy: `PrepareCopy` is a no-op and `fds_from_pixmap` is missing |

So the target is GNOME Shell's output and fullscreen apps. Removing the copy for ordinary windows
would need GPU compositing in Termux:X11 (EXA hooks plus `fds_from_pixmap`); that is a separate
and much larger change, out of scope here.

## Where things stand

| What | Where |
| --- | --- |
| Driver | `packages/mesa-vulkan-icd-panvk-kbase`, Zenith `cf70e02`, `combined-ahb`; present-wait patch `tools/panvk-probes/platform-patches/0003-*` (989e419) |
| Path selection | Zenith `src/panfrost/vulkan/panvk_wsi.c` `panvk_wsi_init`: `PANVK_KBASE_DRI3=raw`/`termux` sets `kbase_raw_dri3`, which disables modifiers and sends `RAW_MMAPPABLE_FD`. There is no AHB mode |
| WSI image allocation | WSI's own buffers come from kbase/ION dma-bufs (`kbase_kmod_supports_dmabuf`), not from AHardwareBuffer |
| Earlier AHB result | [PANVK-X1S-RESEARCH.md](../PANVK-X1S-RESEARCH.md) line 82 and 98: app-allocated AHB imports return `VK_ERROR_INVALID_EXTERNAL_HANDLE`; logcat `complete metadata unavailable rc=-95; refusing guessed layout` (no usable Samsung gralloc layout metadata). Zenith patches `android/013-vendor-mapper-metadata`, `android/014-vendor-neutral-gralloc-mapper-and-hidl-mapper4`, `android/008-ahb-dma-buf-finder` are the code involved |
| Benchmark | `tests/native/panvk-desktop.py --integrated --benchmark-only` on this branch (see the raw DRI3 page for flags); records CPU per process, gears FPS, mpv drops |

## Next steps

1. **Measure the ceiling first, without new code.** On a private lorie, rerun the raw DRI3
   benchmark with `TERMUX_X11_FORCE_FLIP=1` in the X server's environment. GNOME Shell's
   root-sized frames should then flip instead of being copied. Compare X server CPU with the
   earlier raw and SHM runs, and look at the recordings for corruption (the Turnip comment). This
   shows how much a flip saves before any AHB work. If X server CPU barely drops, the copy is not
   where the time goes; find out where (`simpleperf` on the server process) before continuing.
2. **Allocate one AHB and draw into it.** Small standalone probe on the S20: `AHardwareBuffer_allocate`
   1920×1080 `R8G8B8A8_UNORM` with `GPU_COLOR_OUTPUT | GPU_SAMPLED_IMAGE`, import into PanVK with
   `VK_ANDROID_external_memory_android_hardware_buffer`, clear to a colour, read back. This is the
   step that failed before on Samsung metadata. Record the exact failure with the current driver.
   Options if it still fails, in order of preference:
   - Get the layout from Android rather than guessing: `AHardwareBuffer_describe` (stride) and
     `AHardwareBuffer_lockPlanes` on a CPU-usable buffer, and check whether Samsung allocates
     single-plane RGBA linearly for these usages. Verify with a pattern written by the CPU and read
     by the GPU, and the reverse.
   - Use a dma-buf PanVK already allocates and wrap it as an AHB. Android has no public API for
     that; note it and do not pursue private APIs without asking the user.
3. **Send the AHB to Termux:X11.** Small client probe: socketpair, `xcb_dri3_pixmap_from_buffers`
   with modifier 1255 and the socket fd, answer the server's one-byte request with
   `AHardwareBuffer_sendHandleToUnixSocket`, then `xcb_present_pixmap` fullscreen. Check the server
   log for `DRI3: imported AHardwareBuffer` (needs the server debug flag) and the Android
   picture. Then check that the flip is taken (`loriePresentFlip` returns TRUE, no CPU copy:
   X server CPU stays near idle at 60 fps).
4. **AHB mode in PanVK's X11 WSI.** If steps 2–3 pass: a new `PANVK_KBASE_DRI3=ahb` mode where the
   swapchain allocates its images as AHBs and presents them with modifier 1255 (or 1256 when the
   image is bottom-up). Keep the present wait from patch 0003: AHBs carry no fence either. This is
   a Zenith/Mesa patch under `tools/panvk-probes/platform-patches/`; Mesa's `AGENTS.md` rules apply
   (label AI-written commits, nothing posted upstream).
5. **Benchmark and race-check** as in the raw DRI3 page: same fixture, both run orders, the race
   tests, then a 30-minute soak. Done only if total CPU is lower than MIT-SHM, not just X server
   CPU moved.

## Gotchas

- `graphics.apply_renderer` strips `PANVK_KBASE_DRI3`, `VK_DRIVER_FILES` and `VK_ICD_FILENAMES`;
  set overrides after it and check `/proc/<pid>/environ` and the mapped `libvulkan_panfrost.so`.
- Flips need a root-sized pixmap (`pvfb->root.width/height`). A resolution change or a non-fullscreen
  shell frame falls back to the copy.
- Video decode is separate. The benchmark decodes in software on purpose. Hardware decode goes
  through MediaCodec; making decoded frames reach the screen without a copy is the zero-copy work,
  not this page.
- Never drive the live `:0`; use a private lorie. Claim the phone in `temp/PHONE-STATUS`.

## What counts as done

- With AHB presentation, total CPU (shell + X server + app) during the 1080p video and gears
  phases is clearly below MIT-SHM, in both run orders.
- No split or cut frames in the race tests; the soak completes.
- Recordings opened and looked at.
