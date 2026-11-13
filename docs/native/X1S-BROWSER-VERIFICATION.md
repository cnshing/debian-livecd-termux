# Chrome and Chromium on x1s

## Current state (2026-11-12): ANGLE on PanVK

**Both browsers render on the GPU.** The user approved ANGLE on PanVK.
`mesa-vulkan-icd-panvk-kbase` packages the driver for the stock kernel's
`/dev/mali0` (Mali-G77, kbase JM 11.35). The shared launcher selects it
independently of the desktop renderer.

| Capability | Native Chromium 156 | glibc Google Chrome |
| --- | --- | --- |
| GPU compositing, WebGL 1/2, WebGPU | enabled; captures and readback correct | same |
| VP9 hardware playback | passes with android-vaapi revision 3 or later | decodes with the private glibc build; one compositor comparison below the SSIM threshold |
| HEVC / H.264 playback | software fallback | software fallback |
| WebCodecs hardware encoding | GPU-process crash with the encoder feature enabled | same |
| WebRTC H.264 / VP9 hardware loopback | works with the encoder feature enabled | no network interfaces / ICE candidates under Bionilux |

Playback and encoding results above use private test launchers and drivers,
except for the installed-launcher GPU rendering checks. The phone still had
android-vaapi revision 2 at the 2026-11-12 continuation's inventory. Installing
revision 4 and repeating VP9 through the installed `chromium-browser` remain
required. Stop the desktop before replacing its globally preloaded library.

### Decode surfaces and completion

The software surface backend does not mean software codec execution: Termux:VA
still calls Exynos MediaCodec. Its original malloc-backed surfaces could not
be exported to ANGLE. Revision 3 adds an ION dma-buf winsys
([tva_ion_winsys.h](../../packages/android-vaapi/tva_ion_winsys.h)). Chromium
VP9 then passes six fullscreen cycles, 188 frames, none dropped, with numbered
frames 12 and 36 correct at the browser and compositor layers.

The glibc recipe now cross-builds the same pinned bridge and shared patches
against a pinned Debian ARM64 sysroot. It installs the softpipe driver under
`android-vaapi-glibc/mali` beside the prebuilt Turnip stack. The launcher selects
that driver on Mali only. This package change still needs its CI build and
installed-launcher device qualification; the existing private glibc build is
the playback evidence, not a qualification of the new package.

Both browsers require `TERMUX_VA_SYNC_END_PICTURE=1`: removing that bounded
completion wait exposes stale compositor frames. Exynos HEVC (and H.264 when
explicitly enabled) returns its first frame only after about 18 pictures,
exceeding the bridge's 500 ms per-picture wait. The browser falls back to
software. The wait must remain until the bridge can handle delayed decoders
without exposing stale pictures. Native Chromium passes VP9 only on Adreno too.
H.264 and AV1 remain disabled by default in the VA profile.

Chrome's private glibc VP9 run produces the correct frame numbers and colours,
but a windowed compositor capture scores SSIM **0.8987**, below **0.90**.
Software Chrome scores 0.921 in that comparison. Chroma upsampling in the
ANGLE/Vulkan NV12 path is a hypothesis, not a demonstrated cause. Acceptance
thresholds remain unchanged.

### Encoding and Chrome networking

`AcceleratedVideoEncoder` remains disabled by default. With that feature on,
native Chromium's WebRTC loopback uses `OMX.Exynos.AVC.Encoder` and
`OMX.Exynos.VP9.Encoder`, and the matching hardware decoders: about 284 frames
per codec with exact received colours. WebRTC uploads ordinary I420 memory.
Do not add `--video-capture-use-gpu-memory-buffer`. The daemon retries without
the low-latency key that Exynos rejects; latency in a real call is unqualified.

WebCodecs follows a different path. On Linux,
`VideoEncodeAcceleratorAdapter` requests `kGpuMemoryBuffer` storage. These
browsers supply shared memory where `CreateGpuMemoryBufferHandle()` requires
`gfx::NATIVE_PIXMAP`, causing a CHECK and a GPU-process SIGTRAP. This happens
in both browsers with VA driver revisions 2 and 3. CBR is also required;
Chromium blocks VA-API VBR outside ChromeOS. Enabling the feature globally can
therefore let a WebCodecs page crash the GPU process repeatedly and disable GPU
acceleration for the session. Native Chromium needs a shared-memory adapter
or a graceful failure before enabling the feature by default. Prebuilt Chrome
requires a separate decision about accepting this risk.

Chrome WebRTC produces zero ICE candidates and stays in connection state `new`.
Its log reports `Could not bind NETLINK socket: Permission denied`. This is a
Bionilux/network-interface discovery problem, independent of the codec bridge;
Chrome hardware WebRTC encoding and decoding have not been qualified.

Evidence: local `temp/gpu-x1s/panvk-runs/40-69*`,
`BROWSER-VIDEO-HANDOFF.md` and `CHROME-VIDEO-FINDINGS.md`.
For the earlier surface fix see `panvk-runs/30-37*`.

## Earlier no-ANGLE qualification

**Both browsers were tested. Neither passed hardware rendering/video acceptance
under the no-ANGLE constraint.** Native Chromium could use Mali Vulkan for Skia
rasterization, but its display compositing and video decoding remained software.
Google Chrome started through Bionilux; its Vulkan bridge did not initialize.
Firefox workloads remain skipped under the user's instruction.

See [the device investigation](X1S-GPU-VERIFICATION.md) for firmware and the
accepted mpv/MediaCodec paths. These are native Termux tests, including glibc
Chrome through Bionilux; they do not test the Android Chrome application.

## Installed browsers and provenance

- Google Chrome **157.0.8103.78**, ARM64 Linux stable, downloaded through Google's
  signed repository index by `overlays/Browser+Chromium/browsers/install-chrome.py`.
  Base glibc 2.44 was already installed. The original offline setup explicitly
  skipped Chrome; it was not a failed glibc compatibility test. Follow-up added
  Bionilux 0.5.0, android-vaapi-glibc and patchelf without upgrading existing
  packages. The installer checked `chrome --version` before activating it and
  preserved the existing extensions directory.
- Native Chromium **156.0.8078.79-1**, already built with VA-API. The installed
  repository package matches the previously successful CI artifact byte for
  byte: SHA-256
  `448d6489939b45f7276880b17c35e45fffeebc2f96db631df66a61dc0641dde1`.
  Its VA-API build receipt is present. Calling this stock Chromium with VA-API
  compiled out would be incorrect.
- The newer [CI run](https://github.com/cnshing/debian-livecd-termux/actions/runs/43026620093)
  built FFmpeg successfully; Chromium exceeded GitHub's six-hour job limit.
  It produced no replacement Chromium artifact. No new CI build was needed to
  test the installed VA-API-enabled package.

## Final device results

The maintained `tests/browsers/test-fullscreen.py` drove fresh profiles on private
Termux:X11/GNOME displays and private codec-daemon sockets. The final six runs
were serial; all six passed the before/after shared-process and display isolation
checks. No ANGLE libraries were found in their recorded browser mappings, and
no ANGLE backend was selected.

| Browser | Codec | Decoding observed | Browser + GNOME frame 12/36 pixels | Hardware acceptance |
| --- | --- | --- | --- | --- |
| Chromium | VP9 | `VpxVideoDecoder` (software) | Pass | Fail |
| Chromium | H.264 | `FFmpegVideoDecoder` (software) | Pass | Fail |
| Chromium | HEVC | `FFmpegVideoDecoder` (software) | Pass | Fail |
| Chrome | VP9 | `VpxVideoDecoder` (software) | Pass | Fail |
| Chrome | H.264 | `FFmpegVideoDecoder` (software) | Pass | Fail |
| Chrome | HEVC | No advancing decoded frames | No accepted captures | Fail |

VP9 ran six fullscreen/windowed cycles per browser; the other codecs ran three.
Chrome HEVC completed window transitions, but the video did not advance: those
transitions are not a playback pass. Each passing visual case compares both
browser and compositor captures at frames 12 and 36 against numbered fixtures:
20 accepted image comparisons in total, with unchanged color, PSNR >=28 dB and
SSIM >=0.90 thresholds. Every final invocation required hardware decoding and
correctly failed that acceptance check or the earlier playback-progress check.

| Capability | Native Chromium | glibc Chrome |
| --- | --- | --- |
| Direct Vulkan rasterization | `GaneshVulkan`, Mali driver mapped | Vulkan initialization fails |
| GPU display compositing | `disabled_software` | `disabled_software` |
| Direct EGL/GLES request | Rejected: allowed EGL implementation is ANGLE | Same rejection |
| WebGL 1 / WebGL 2 without ANGLE | Context unavailable | Context unavailable |
| Hardware encoding | Not qualified; no advertised encoding profiles, software status | Same |

A VA probe can hold `/dev/mali0` without decoding any frames. Device FDs, driver
strings and `video_decode: enabled` do not override the actual software decoder
names or empty advertised decoding-profile list.

## Specific blockers

1. **Browser EGL implementation:** both builds reject `--use-gl=egl` with
   requested `egl-gles2,angle=none` and allowed `egl-angle,angle=default`.
   Native VirGL -> Android GLES works for mpv, but these browser builds do not
   accept that EGL implementation. No ANGLE fallback was enabled.
2. **Chrome's glibc Vulkan loader/ICD:** initially `libvulkan.so.1` was missing.
   A private Debian ARM64 Vulkan loader 1.4.309 was then extracted under the test
   workspace. It finds the Bionic ICD wrapper but cannot load its Android
   dependency `libnativewindow.so`, and `vkCreateInstance` returns -9. This
   private extraction changes no system Vulkan loader. The tested Bionic wrapper
   is not an established glibc-to-Android driver bridge.
3. **VA-API discovery and pipeline:** default DRM enumeration finds no render
   device on x1s. Explicit `/dev/mali0` plus the private driver permits VA-API
   initialization with CPU-backed surfaces (`softpipe` for native, `llvmpipe`
   for glibc), but both browsers still choose software decoders. These surface
   renderers do not establish software codec execution by themselves; the
   decoder diagnostics do.
4. **Native Vulkan video gating:** Chromium 156's
   [Linux media client](https://chromium.googlesource.com/chromium/src/+/refs/tags/156.0.8078.79/media/mojo/services/gpu_mojo_media_client_linux.cc#104)
   returns an unknown VA decoder for the Vulkan context unless the
   `VulkanFromANGLE` and `DefaultANGLEVulkan` feature gates are enabled. The GL
   route has its own gate and requires a working GL implementation. Successful
   independent VA-API FFmpeg decoding therefore does not imply browser decode.
   Removing checks would require a source change and subsequent import/surface
   correctness tests; enabling misleading flags is not an acceptance result.

## Harness correction and evidence

Earlier windowed compositor metrics failed because the crop inferred the bottom
shadow from half the outer/inner width difference. Chromium's actual X11
`_GTK_FRAME_EXTENTS` were asymmetric: 22,22,19,25. Reading those independent
extents moves the content origin from Y=122 to Y=119; both layers then pass
without changing thresholds. This supersedes the earlier Chromium compositor
failure. It does not retroactively qualify Firefox.

The harness now reads those extents, waits for private capture-extension
activation, serializes invocations through a lock, records WebGL red-pixel
readback when available, and saves relevant mapped libraries and device FDs.
Three host regression cases cover the crop and scaling correction.
Exploratory overlapping runs had invalid isolation comparisons and one private
startup collision; they are not the final acceptance evidence.

Raw local artifacts are excluded from Git:

- PC: `temp/gpu-x1s/browser-final-summary.json`,
  `resume-browser-final-run.txt`, `chrome-install-resume.txt`.
- Phone: `~/gpu-x1s/browser-tests/final-{chrome,chromium}-chart-*`, each with
  result/isolation JSON, browser/daemon/shell logs and accepted captures.
- Diagnostic launchers remain under the phone's browser-test workspace. They
  explicitly select `--use-gl=disabled --use-vulkan=native`, the private ICD,
  private VA drivers, and `/dev/mali0`; the Chrome launcher uses Bionilux and its
  own glibc library paths. They are experimental test launchers, not new browser
  defaults.

## Moto Pad reference: useful design, different platform

Reviewed [Mattcabrices/moto-pad-2026-arch-linux](https://github.com/Mattcabrices/moto-pad-2026-arch-linux)
at commit `a3d672c5967cbf39690bd77207ddb9896116e626`. Its Mali-G57/MediaTek system
boots Arch with a rebuilt kernel and patched Wayland compositor. It is not a
native Termux/X11 setup or a driver installation for Samsung's Mali-G77.

The useful parts are its libhybris Android-driver bridge and
[AHardwareBuffer-backed GBM implementation](https://github.com/Mattcabrices/moto-pad-2026-arch-linux/blob/a3d672c5967cbf39690bd77207ddb9896116e626/tools/src/archpad-gbm.c).
The latter supplies buffers and passes Android handles to a matching patched
wlroots compositor. This is relevant to the missing Linux/Android buffer-import
integration; copying the GBM library alone would not supply the compositor side.

Its actual [Chromium launcher](https://github.com/Mattcabrices/moto-pad-2026-arch-linux/blob/a3d672c5967cbf39690bd77207ddb9896116e626/config/chromium/chromium-gpu)
uses `--use-gl=angle --use-angle=gles-egl`. It therefore does not demonstrate
no-ANGLE Chromium acceleration. Its video shim adapts MediaTek V4L2 buffers,
formats and ordering, not Samsung MediaCodec/VA-API. This x1s Termux UID has
read/write access to `/dev/mali0`, but not the exposed `/dev/video*` nodes; no
`/dev/dri` or `/dev/dma_heap` path was found by the same check.

Inference: the buffer-allocation/handle-transport design may inform a future
Termux adaptation, and libhybris may inform a glibc driver bridge. Neither is a
validated no-ANGLE fix on x1s. The reference repository was read only; no scripts
from it were run on the phone. Firefox-specific notes were added to its handoff
for later source review, with workload testing still skipped.
