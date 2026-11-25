# Handoff: Note10+ Turnip presentation with Android hardware buffers

State on 2026-11-25 UTC. **Not started; nothing has been measured on the Note10+.** This page
proposes porting the S20's AHB presentation to the Note10+'s Turnip driver and lists what to
check first. The S20 work it builds on: [s20-panvk-ahb-present.md](s20-panvk-ahb-present.md).
Shared rules: [README.md](README.md).

## Why

On the S20, presenting Vulkan swapchain images to Termux:X11 as Android hardware buffers (AHBs)
instead of MIT-SHM readback cut total CPU by 28% for gears and by 11–17% for video at equal
output, in both run orders, with correctness, race and soak checks passing. It is the S20
desktop's default from `mesa-vulkan-icd-panvk-kbase` 26.3.1-2 and `livecd-desktop` 0.2.0-51.

The saving comes from Termux:X11 (`termux/termux-x11` at `a00942e`,
`lorie/src/main/cpp/lorie/InitOutput.c` and `renderer.cpp`):

- An AHB arrives through modifier 1255 (`AHARDWAREBUFFER_SOCKET_FD`) and can be **flipped**:
  the Android activity samples it on the GPU through `EGL_NATIVE_BUFFER_ANDROID`, no CPU copy.
- A raw dma-buf (`DRM_FORMAT_MOD_LINEAR`/`INVALID`) is `mmap`ed and treated as CPU memory.
  `loriePresentFlip` **refuses to flip it** unless `TERMUX_X11_FORCE_FLIP=1`, with the comment
  "For some reason it does not work fine with turnip", so every frame is copied by the CPU.
- MIT-SHM readback copies on the application side instead (what the S20 replaced).

Whichever of the last two the Note10+ uses today, it pays a CPU copy per frame that an AHB flip
would avoid. How large that copy is on Adreno is unknown; measure it before porting anything.

## How the Note10+ presents today

The Note10+ (SM-N975U1, Snapdragon 855, Adreno 640, Android 11, kernel 4.14) has two Turnips:

| Turnip | Used by | Source | Present path |
| --- | --- | --- | --- |
| Bionic, Termux `mesa-vulkan-icd-freedreno` 26.2.6-1xx, staged by `prebuilt/turnip/gpu-setup.py` into `~/.local/opt/livecd-native/gpu` | mutter (Zink/Kopper), GTK, Chromium, Firefox | `packages/mesa`, `-Dplatforms=x11,wayland`, `-Dfreedreno-kmds=msm,kgsl` | **unsettled**, see below |
| glibc, `android-vaapi-glibc` (lfdevs Mesa) | Chrome | `packages/android-vaapi-glibc` | DRI3 with shared dma-bufs; present waits for the fence since revision 14 ([note10-chrome-typing.md](note10-chrome-typing.md)) |

The Bionic present path needs settling first. [note10-gpu-rectangles.md](note10-gpu-rectangles.md)
and [note10-chrome-typing.md](note10-chrome-typing.md) report that the Bionic Turnip "does not use
DRI3 on KGSL" (empirical: Chromium was clean where Chrome tore). The source suggests otherwise:
`tu_wsi_init` (`src/freedreno/vulkan/tu_wsi.cc`) sets `sw_device = false`, and with no DRM device
behind KGSL `tu_wsi_can_present_on_device` reports a different GPU, which in
`wsi_common_x11.c` selects the DRM image path with `same_gpu = false` — a prime blit into a linear
dma-buf, still sent over DRI3. Decide it on the phone (step 1). Termux:X11 runs **without**
`-legacy-drawing` on Turnip (`graphics.legacy_drawing`), so its root is already AHB-backed.

## What carries over from the S20

Reusable, mostly:

- The shared Mesa parts of `tools/panvk-probes/platform-patches/0004-wsi-x11-termux-ahb.patch`:
  the `WSI_IMAGE_TYPE_AHB` allocation in `wsi_common.c` (CPU-usable AHB, queried memory
  properties, dedicated import) and the X11 socket transport in `wsi_common_x11.c` (modifier
  1255, one-byte request, `AHardwareBuffer_sendHandleToUnixSocket`, three-second timeouts).
  Only the switch in `panvk_wsi_init` is PanVK-specific; Turnip needs its own in `tu_wsi_init`.
- The render-completion wait: KGSL attaches no implicit fences and the 4.14 kernel lacks
  `DMA_BUF_IOCTL_IMPORT_SYNC_FILE`, so the present must wait on the CPU. `packages/mesa`
  patch 0028 and `android-vaapi-glibc` revision 14 already do this for DRI3; the AHB path in
  patch 0004 keeps the same wait (patch 0003 on the S20).
- Probes: `tools/panvk-probes/ahb-import.py`, `ahb-x11.py`, `ahb-egl.py`,
  `tests/native/panvk-ahb-present.py`, and `tests/browsers/private-lorie`. They take a
  `--driver` path; check for PanVK-only assumptions before trusting a pass.
- The benchmark and correctness harness `tests/native/panvk-desktop.py` (`--benchmark-video-fps`
  for equal-output comparisons, `--benchmark-video-profile` for per-thread CPU, race, restarts,
  soak, `--mode installed`). It is PanVK-specific today (`PAN`, Mali FD checks); generalise it
  rather than writing a second harness.
- The launcher hook: `graphics.session_presentation` gives only the desktop session on
  Termux:X11 `PANVK_KBASE_DRI3=ahb`; extend it for Turnip, keeping browsers and glibc out.

Not reusable:

- Patch 0005 removed a PanVK kbase cost (whole-buffer cache cleaning of every imported buffer on
  every submission). Turnip/KGSL has its own import and cache handling; profile per-thread CPU
  before assuming either the cost or its absence.
- The PanVK packages, release and tree pins.

## What Turnip needs

1. **AHB import.** `VK_ANDROID_external_memory_android_hardware_buffer` support in Turnip and
   Mesa's common Vulkan code is compiled only with `-Dplatforms=android` (and gralloc through
   `src/util/u_gralloc`, which has a Qualcomm backend, `u_gralloc_qcom.c`). Termux's Mesa builds
   `x11,wayland` and carries `0000-disable-android-detection.patch`. A Bionic Turnip built for
   both Android and X11 is needed — the S20's PanVK is built that way by Zenith's
   `scripts/build-android.sh` (`tools/panvk-probes/build-driver.sh`). On KGSL, importing the
   AHB's dma-buf goes through `kgsl_bo_init_dmabuf` (`tu_knl_kgsl.cc`).
2. **A switch in `tu_wsi_init`** that sets `wsi_device.x11.ahb` (and leaves `sw_device` false),
   rejected on non-Android builds as patch 0004 does for PanVK.
3. **AHB usage bits that import.** On the S20, GPU-only usage `0x300` failed import and
   CPU-usable `0x333` passed. Check both on Adreno with `ahb-import.py` before choosing.
4. **No fallback exists** in the AHB WSI when the X server lacks the socket import (for example
   Xvfb): swapchain creation fails. Only ever enable it for Termux:X11.

The glibc Turnip (Chrome) cannot use this path; leave Chrome on DRI3.

## Next steps, in order

1. **Measure the baseline and settle the present path.** On a private lorie (`private-lorie`,
   1920×1080, fake 60/s, the same 1080p30 fixture with software decode, five-second warmups,
   30-second intervals), record Shell, X server and application CPU for gears, 30 FPS video and
   10 FPS equal-output video, plus VO drops. Identify the Bionic path from the server's DRI3
   import log, the application's mapped buffers and a `MESA_VK_WSI_DEBUG=sw` control.
   `graphics.apply_renderer` strips `MESA_VK_WSI_*`; set it afterwards and check
   `/proc/<pid>/environ`.
2. **Decide go/no-go** from the X server and readback share of CPU. If the copy is small on
   Adreno, record that and stop.
3. **Build a private Android+X11 Bionic Turnip** in CI with the shared WSI parts of patch 0004
   and a Turnip switch. Turnip has no source-build workflow here yet; `panvk-driver.yml` is the
   model. Stage it privately; install nothing.
4. **Probes:** AHB import with both usages, CPU↔GPU pattern checks, the socket client with 180
   paced presents completing as `FLIP`, exact root pixels, Android EGL sampling.
5. **Paired qualification against the same Turnip without AHB**, both run orders: gears and
   equal-output video total CPU (the owner's gate is CPU for equal work), FPS, drops; then
   colour/resize, restarts, a 300-frame race and a 30-minute soak. Open the captures.
6. **Promotion, only on the owner's go-ahead:** package the driver, extend
   `session_presentation`, install through the local repo, recheck with `--mode installed`.

## Gotchas

- The phone's display is shared with the user, often under DeX. Never drive the live `:0`;
  claim the phone in `temp/PHONE-STATUS`; never stop processes you did not start.
- The launcher overwrites `TU_DEBUG` and strips `MESA_VK_WSI_*`, `VK_DRIVER_FILES` and
  `VK_ICD_FILENAMES`; set experiment variables after `acceleration.prepare` or
  `apply_renderer`, then verify the process environment and mapped `libvulkan_freedreno.so`.
- KGSL has no implicit sync; any present path without a CPU fence wait shows partly rendered
  bins (rectangles, horizontal splits). Keep the wait.
- Raw CPU totals at the source rate reward dropping frames; compare at equal output and keep
  drop counters (see the S20 page).
- `gpu-setup.py` matches Turnip to the installed `mesa` version; a private Turnip must not
  replace the staged one in `~/.local/opt/livecd-native/gpu`.

## What counts as done

- The baseline is measured and the Bionic present path is identified, with evidence.
- Either a recorded no-go, or an AHB Turnip whose total CPU for gears and equal-output video is
  clearly below the current path in both run orders, with no split frames in the race test, a
  completed soak, and captures opened and looked at.
