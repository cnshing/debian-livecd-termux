# Firefox, mpv and Chromium acceleration checks

Results on Android 11 with Adreno 640. Full checks and fixes were
authorized after the initial startup-only run. No tests use the live desktop.

| Application / codec | Current result |
| --- | --- |
| Firefox / VP9 | Pass: VA-API frames, WebRender, Turnip/KGSL process, numbered-frame pixel comparison |
| mpv / VP9 | Pass: Qualcomm MediaCodec component, `mediacodec-copy`, `gpu-next`, Turnip/KGSL, numbered-frame pixels |
| mpv / H.264 | Pass: the same checks with the Qualcomm AVC decoder |
| mpv / HEVC | Pass: the same checks with the Qualcomm HEVC decoder |
| Firefox / HEVC | Pass: VA-API frames, WebRender, Turnip/KGSL process and numbered-frame pixels with the private FFmpeg libraries |
| Native Chromium 156 / VP9 | Pass: `VaapiVideoDecoder`, Vulkan/Turnip, browser and GNOME pixels across 2 fullscreen cycles with native producer completion |
| Chromium (Debian 156, pinned) / VP9, HEVC | Pass: `VaapiVideoDecoder`, Turnip GPU compositing, browser and GNOME Shell pixels across 6 fullscreen cycles |
| ungoogled Chromium 156 (pinned) / VP9, HEVC | Pass: the same checks |
| Google Chrome / VP9, HEVC | Pass: the same checks, with the shared VA completion adapter |

The pixel oracle identifies a reference by the image's barcode, checks eight
color patches (maximum channel error 16), and requires PSNR >=28 dB and
SSIM >=0.90. Firefox captures its page; mpv captures the decoded video. These
checks do not qualify GNOME fullscreen presentation, Android's actual display,
long playback or every stream/profile. The glibc runs below record an earlier
intermittent stale-frame failure under concurrent hardware-encoding load.

## Native packages after the fresh-install investigation, 2026-11-10

The checked phone had just been reinstalled from `7ae6f6b`. Its Firefox and
Chromium GPU rendering worked, but Firefox lacked the home-built probe/decoder
pair and Chromium could not load `libva.so.2`. The fixes were tested by installing
the new native packages on that clean base; final acceptance from the assembled
new repository tarball remains a separate reinstall check.

`android-firefox-video` now packages Mozilla's KGSL graphics probe and VA-API
FFmpeg 9.0.2 libraries under `$PREFIX`. Its small private Firefox loader shares
the installed application's assets, and a manifest guards its Firefox identity.
The launcher warns and starts the current Firefox with software decoding when
the port is missing, incomplete or mismatched. The Browser overlay installs the
package by default. The documented `livecd-accelerate` command is also packaged,
and the acceleration test uses the installed `termux-va` daemon.

Chromium's native VA loader requires desktop `libva.so.2` / `libva-drm.so.2`
names, while Termux's Meson emits unversioned libraries. Private aliases in
`android-vaapi` resolve that failure. Hardware decoding then exposed a producer
completion bug: its browser capture had the requested frame, while GNOME showed
a different one. The native driver now performs a bounded 500 ms surface wait
at `vaEndPicture` for the native Chromium profile. This is the same completion
boundary used by the existing glibc adapter; Firefox keeps its explicit waits.

With `android-vaapi` revision 2, `android-firefox-video` 9.0.2 and
`livecd-desktop` 0.2.0-12:

- Firefox 159.0.1 passes VP9 and HEVC: 48 frames, VA-API frame diagnostics,
  WebRender, Turnip/KGSL process evidence and numbered-frame pixels, with
  `hardware_verified: true`. Both were repeated after the completion change.
- Native Chromium 156 passes the strict VP9 hardware/fullscreen command below.
  Only `VaapiVideoDecoder` is recorded, all four fullscreen/windowed samples
  drop zero frames, and both browser and GNOME match reference frames 12 and 36
  on their first capture. PSNR is 30.74–30.76 dB and SSIM 0.908–0.910. The contact
  sheet was visually checked.
- `LIVECD_VA_DISABLE_COMPLETION=1` reproduces the failure with the same command:
  hardware and browser pixels pass, while GNOME shows frames 3 and 11 instead of
  12 and 36. The disabled control's contact sheet was also checked.
- Every test uses a private Termux:X11 server and passes live-session isolation
  and cleanup checks. No test sends input to `:0` or opens a camera/microphone.

From a short phone test directory containing `browsers/` and `fixtures-v2/`:

```sh
python browsers/test-acceleration.py firefox --fixtures fixtures-v2 --out f1
python browsers/test-acceleration.py firefox --fixtures fixtures-v2 --case chart-hevc.mp4 --out f2
python browsers/test-fullscreen.py chromium --browser-command "$PREFIX/bin/chromium-browser" \
  --x-server lorie --renderer zink --browser-flag=--window-size=1280,1100 \
  --require-gpu --require-hardware-decode --private-daemon --media-dir fixtures-v2 \
  --fixture-manifest fixtures-v2/manifest.json --case chart-vp9.webm --cycles 2 --out c1
```

Raw device evidence stays in the working tree's `temp/acceptance-fixes/` and the
phone's `~/.cache/codex-video/`. The package artifact check verifies the decoder ABI,
native helpers, VA loader aliases and compiled completion support. Host tests
cover the launcher fallback and completion routing, including the disabled
control and other native clients.

## Earlier development qualification

The test runner now writes mpv's explicit log file, flushes Firefox diagnostics,
and waits for process exit after signalling. A private Firefox application copy
contains a compiled port of Mozilla's graphics probe: it recognizes Zink/Turnip
on an accessible KGSL node and reports that render node. Its VA-API probe still
queries the actual driver. Private GBM/DRM aliases provide the desktop sonames
without editing installed package files. The launcher checks the private copy's
identity against the installed Firefox version.

Stock Termux FFmpeg already supports Android MediaCodec hardware decoding. The
additional private FFmpeg work supplies Firefox's VA-API interface for codecs its
bundled FFVPX does not provide; it does not replace the FFmpeg command or mpv's
system libraries.

The final checks reach all 48 fixture frames in Firefox and the last frame in
mpv. VP9/HEVC pass for Firefox; VP9/H.264/HEVC pass for mpv. All five final runs
pass cleanup and live-session isolation checks. H.264 remains disabled in the
VA-API bridge because of the earlier stream failure; mpv's direct MediaCodec
H.264 route is independent and passes. An explicit Firefox H.264 software-fallback
control also passes playback, GPU, pixel and cleanup checks with the final private
FFmpeg libraries; it is recorded separately from hardware decoding passes.

The Podman entry point uses Termux's pinned image/checkout, host-owned caches,
FUSE and two build jobs. libva staging removes only a hash-pinned patch intended
for a different upstream version. libva built successfully. Strict Chromium
hardware cases require the installed VA-API build receipt, `VaapiVideoDecoder`,
GPU process evidence and the existing pixel/fullscreen checks.

The Chromium attempt downloaded and patched the matching source and generated its
build targets. The latest resume exited because Ninja was missing from the
continued libva build environment. The user then requested stopping Chromium work;
no build container or compiler remained running. Recipes and local build caches
were retained. Stock Chromium's GPU rendering remains available; rebuilding is
needed specifically to add its compiled-out VA-API video backend.

Host verification passed 9 packaging checks and 5 video-tool groups. Passing
device runs require no surviving tagged applications and identical live
desktop/shared daemon state before and after each run. Optional raw evidence is
local at `temp/docs/evidence/browsers/native-gpu-video/`;
see the [privacy notes](../privacy.md).

## Prebuilt VA-API Chromium

The Chromium source build stayed stopped. Debian's signed arm64 Chromium 156 and
ungoogled-chromium's arm64 portable release, both built with VA-API, run on Termux's
glibc through the same Bionilux and Mesa stack as Chrome
([lock](../../overlays/Browser+Chromium/browsers/chromium-prebuilt.lock.json)). Two small
adapters are compiled at install time:

- [`va-completion.c`](../../overlays/Browser+Chromium/browsers/va-completion.c) waits on
  `vaSyncSurface2` (bounded to 500 ms) after each successful `vaEndPicture`. Without it the
  Termux:VA bridge reports completion before its CPU copy is visible to Chromium's implicit
  DRM synchronization, and GNOME Shell shows a stale frame after a seek while the browser's
  own capture is correct. `LIVECD_VA_DISABLE_COMPLETION=1` reproduces that failure.
- [`bionilux-fortify.c`](../../overlays/Browser+Chromium/browsers/bionilux-fortify.c) routes
  `__readlink_chk` through Bionilux's `readlink` hook, fixing Debian Chromium's ICU startup error.

The fullscreen matrix (`tests/browsers/run-phone-video-suite.py`, 6 cycles per case, private
GNOME Shell on a private Termux:X11 server) passed all 14 cases:

| Case | Chrome | Chromium | ungoogled |
| --- | --- | --- | --- |
| Hardware VP9, HEVC | Pass | Pass | Pass |
| Software override (`LIVECD_*_HARDWARE_VIDEO=0`) | Pass, `VpxVideoDecoder` | Pass | Pass |
| H.264 | — | Pass, software fallback | Pass, software fallback |
| Completion adapter disabled (negative) | — | Fails as expected: stale shell frame only | Fails as expected |
| Shared-buffer colour fallback off (negative) | Fails as expected: wrong colours | — | — |

Every passing case matched both pixel layers on the first attempt (PSNR at least 30.7 dB,
SSIM 0.91), kept the requested fullscreen state in all 12 samples, dropped no frames, and left
the live desktop and shared daemon unchanged. Firefox and mpv were rerun after the shared
adapters were installed and still pass.

**Known intermittent failure.** After the builds were installed and activated on the
desktop, one of 13 hardware-decode runs failed: Chromium HEVC, windowed, showed a stale frame
in GNOME Shell (frame 13 for 36) while the browser's own capture was correct. Another
session's hardware-encoder tests were using MediaCodec at the time. Three immediate reruns
passed. The completion wait therefore narrows this race but is not shown to close it under
load. Colours were correct in every hardware run. Raw evidence is local under
`temp/docs/evidence/browsers/native-gpu-video/`.
