# Handoff: Chromium hardware encoding

State on 2026-11-15. Chromium is this project's source build (`packages/chromium`). Shared
rules and pass criteria: [README.md](README.md).

## Status

**On for Mali when Chromium 156.0.8078.79-3 or later is installed**
(`chromium_encodes_webcodecs()` in `src/native/acceleration.py` reads dpkg's status file and adds
`AcceleratedVideoEncoder` for the bionic `chromium` profile on `/dev/mali0`). Older revisions keep it off.

| Use | Adreno | Mali (S20), revision 3 |
| --- | --- | --- |
| WebRTC, H.264 and VP9 | H.264 **passes** (Note10+, 2026-11-16): 288 in, 288 out on `OMX.qcom.video.encoder.avc`, received 640x360 picture viewed; no VP9 encoder on this SoC | **passes**: loopback 285 frames per codec, `OMX.Exynos.AVC.Encoder` / `OMX.Exynos.VP9.Encoder` 286 in, 286 out, received 640x360 picture correct, no GPU crash |
| WebCodecs `VideoEncoder` H.264 | **passes**: 60 in, 60 out on `OMX.qcom.video.encoder.avc`, max colour error 10, 0 frames over 16 | **passes**: 60 in, 60 out on `OMX.Exynos.AVC.Encoder`, clean flush, software decode max colour error 12, 0 frames over 16; frames 0, 29, 59 viewed after ffmpeg decode (labels, moving box and colours right) |
| WebCodecs `VideoEncoder` VP9 | no hardware VP9 encoder | **passes** on `OMX.Exynos.VP9.Encoder`, 60 in/out, software decode max error 12 (pixels checked in-page; not viewed as an image) |
| MediaRecorder H.264, colour | **passes** from revision 4 (Note10+, 2026-11-18): known-colour full/limited BT.601/709 frames 8/8 within 3 (FFmpeg decoding as signalled), canvas 1280x720 s0.70/l0.45 on `OMX.qcom.video.encoder.avc`; revision 3 failed 3/4 (no VUI colour) | not run (the colour fix is codec-independent; Exynos `KEY_COLOR_*` support untested) |

## What was wrong, and the fixes

1. Revision 1: on Linux `VideoEncodeAcceleratorAdapter` always asks for `kGpuMemoryBuffer` input; the
   GPU process hits `CHECK_EQ(handle.type, gfx::NATIVE_PIXMAP)` because GPU memory buffers here are
   shared memory, and SIGTRAP loops three times before GPU acceleration is turned off.
   `0100-termux-webcodecs-shmem.patch` (revision 2) makes the adapter use shared memory.
2. Revision 2 (CI 43579240070) no longer crashed, but every frame failed: `VaapiWrapper::UploadVideoFrameToSurface`
   only copies I420 and logged `Unsupported pixel format: PIXEL_FORMAT_NV12`.
   `0101-termux-vaapi-upload-nv12.patch` (revision 3, CI 43606485313) copies NV12 planes with
   `libyuv::NV12Copy`.

Never add `--video-capture-use-gpu-memory-buffer`. WebCodecs needs `bitrateMode: "constant"`
(Chromium refuses variable bitrate on VA-API outside ChromeOS).

CI: the Chromium dependency set is now looked up by the pinned builder commit when no set matches the
recipe hash, so a source patch no longer needs the three-hour dependency bootstrap.

### Rerun on 2026-11-15: revision 3 from CI 43676101303, with the dma-heap bridge

Chromium staged privately (not installed) and started through the installed launcher
(`android-vaapi` 11, `libandroid-dma-heap.so` preloaded), private display and daemon:

- WebCodecs H.264: 60 in, 60 out on `OMX.Exynos.AVC.Encoder`, max colour error 12, 0 frames
  over 16. Frames 0, 29 and 59 viewed after decoding the stream: labels, box and colours right.
- WebCodecs VP9: 60 in, 60 out on `OMX.Exynos.VP9.Encoder`, max error 12, 0 over 16 (checked
  in-page; the raw VP9 chunks have no container, so not viewed).
- WebRTC H.264 and VP9 loopback: 286 and 284 frames, received at 640x360, received pictures
  viewed and correct.
- Encoding does not depend on the dma-heap library: with `LIVECD_DMA_HEAP_ION=0` WebCodecs H.264
  still passes (60 of 60, max error 12), because Chromium copies each frame into the surface
  (patch 0101). Decoding does depend on it ([decode-chromium.md](decode-chromium.md)).

## Still open

- On by default on Adreno too since livecd-desktop 0.2.0-24.
- Colour signalling: revision 4 (`0102-termux-vaapi-encode-colour-space.patch`) writes the frame
  colour space into the H.264 SPS VUI; Termux:VA forwards it to MediaCodec. Mali/Exynos not re-run.
- The Exynos encoders refuse MediaCodec's `low-latency` key (logged as `configure failed with
  low-latency: -10000`, then retried without), so call latency is unmeasured.
- HEVC encode (WebCodecs, WebRTC, MediaRecorder) is not offered, and is not a launcher or
  driver change. Assessed 2026-11-17: Chromium 156's VA-API encoder has delegates for H.264, VP8,
  VP9 and AV1 only (`media/gpu/vaapi/BUILD.gn`); `H265VaapiVideoEncoderDelegate` does not exist
  (the only HEVC encode delegate is Windows D3D12). The driver side is ready: the bridge and
  daemon encode HEVC Main on `OMX.qcom.video.encoder.hevc` / `OMX.Exynos.HEVC.Encoder`, take packed
  VPS/SPS/PPS, and signal colour (`tests/video-encode/test-daemon.py`, hevc-main cases). Work needed:
  (1) a new `h265_vaapi_video_encoder_delegate.{h,cc}` modelled on the H.264 one: VPS/SPS/PPS and
  slice-header builders (`media/gpu/h265_builder.cc` only builds what the decoder tests need),
  `VAEncSequenceParameterBufferHEVC`/picture/slice parameters, IDR-only + P references, CBR rate
  control; (2) wire it into `VaapiVideoEncodeAccelerator` (`CreateEncodeJob` picture type, profile
  list in `GetSupportedProfiles`, `VaapiWrapper` HEVC encode profile mapping); (3) blink/WebRTC
  gating: WebCodecs HEVC encode on Linux requires `BUILDFLAG(ENABLE_HEVC_PARSER_AND_HW_DECODER)`
  and the platform-HEVC-encoder feature, RTCVideoEncoder needs H.265 in its supported formats, and
  MediaRecorder needs `hvc1` in `VideoTrackRecorder`'s codec table. Each try is a 4.5-6 h CI build
  with no local Chromium build, which is why it was not attempted in the parity lane.
- Revision 3 is on main (PR #12); a fresh install gets it once a release carries it.

## How to test

On the S20, private display and private daemon. The probe is in Git:
[`tests/video-encode/webcodecs.html`](https://github.com/cnshing/debian-livecd-termux/blob/main/tests/video-encode/webcodecs.html)
takes `codec=avc1.42001f` or `vp09.00.10.08` and `input=canvas` or `bt709` in its query string,
and `save=1` posts the chunks to `/chunks` for software decoding. Serve it on localhost, run the
browser on a private display with its own `XDG_CONFIG_HOME`, and read `window.RESULT`. The
canvas input is the acceptance case; `bt709` is a control. The earlier WebRTC loopback page and
runner are not in Git.

## Where things are

| What | Where |
| --- | --- |
| Patch | `packages/chromium/0100-termux-webcodecs-shmem.patch`, `0101-termux-vaapi-upload-nv12.patch` |
| Bootstrap and reuse | `.github/workflows/packages.yml` |
| Browser flags | `command_line()` in `src/native/acceleration.py` |
