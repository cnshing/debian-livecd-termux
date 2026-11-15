# Handoff: Chromium hardware encoding

State on 2026-11-14. Chromium is this project's source build (`packages/chromium`). Shared
rules and pass criteria: [README.md](README.md).

## Status

State on 2026-11-14 (evening). **On for Mali when Chromium 156.0.8078.79-3 or later is installed**
(`chromium_encodes_webcodecs()` in `src/native/acceleration.py` reads dpkg's status file and adds
`AcceleratedVideoEncoder` for the bionic `chromium` profile on `/dev/mali0`). Older revisions keep it off.

| Use | Adreno | Mali (S20), revision 3 |
| --- | --- | --- |
| WebRTC, H.264 and VP9 | not run | **passes**: loopback 285 frames per codec, `OMX.Exynos.AVC.Encoder` / `OMX.Exynos.VP9.Encoder` 286 in, 286 out, received 640x360 picture correct, no GPU crash |
| WebCodecs `VideoEncoder` H.264 | not run | **passes**: 60 in, 60 out on `OMX.Exynos.AVC.Encoder`, clean flush, software decode max colour error 12, 0 frames over 16; frames 0, 29, 59 viewed after ffmpeg decode (labels, moving box and colours right) |
| WebCodecs `VideoEncoder` VP9 | not run | **passes** on `OMX.Exynos.VP9.Encoder`, 60 in/out, software decode max error 12 (pixels checked in-page; not viewed as an image) |
| MediaRecorder | not run | not run |

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

- Note10+ (and any Adreno phone) has never run a browser encode test.
- MediaRecorder not tested.
- The Exynos encoders refuse MediaCodec's `low-latency` key (logged as `configure failed with
  low-latency: -10000`, then retried without), so call latency is unmeasured.
- HEVC WebCodecs encode not tested (the S20 has `OMX.Exynos.HEVC.Encoder`; see
  [s20-codec-parity.md](s20-codec-parity.md)).
- Revision 3 must reach the apt repository (merge, then the packages build on main) before users get it.

## How to test

On the S20, private display and private daemon. The probes are in Git on the CI branch:
[`tests/video-encode/webcodecs.html`](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/tests/video-encode/webcodecs.html)
takes `codec=avc1.42001f` or `vp09.00.10.08` and `input=canvas` or `bt709` in its query string,
and `save=1` posts the chunks to `/chunks` for software decoding. Serve it on localhost, run the
browser on a private display with its own `XDG_CONFIG_HOME`, and read `window.RESULT`. The
canvas input is the acceptance case; `bt709` is a control. The earlier WebRTC loopback page and
runner are not in Git.

## Where things are

| What | Where |
| --- | --- |
| Patch | `packages/chromium/0100-termux-webcodecs-shmem.patch` (CI branch) |
| Bootstrap and reuse | `.github/workflows/packages.yml` (CI branch) |
| Browser flags | `command_line()` in `src/native/acceleration.py` |
| History | [VIDEO-ENCODING-HANDOFF.md](../VIDEO-ENCODING-HANDOFF.md) |
