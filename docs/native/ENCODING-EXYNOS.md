# Hardware video encoding on Exynos

**Support is limited.** Hardware encoding on Samsung Exynos phones works for some programs, with
known faults, and does not work out of the box on a fresh installation. Browsers do not
hardware-encode by default. Treat everything on this page as experimental.

Tested on one phone: Galaxy S20 (`x1s`, SM-G981B), Exynos 990, Mali-G77, stock Android 13,
November 2026. Other Exynos phones have not been tested. For the Snapdragon results, see
[ENCODING.md](ENCODING.md).

## How it reaches the hardware

Android lets an ordinary app reach the video hardware only through MediaCodec. Every program
therefore takes the same path, the same one as on Snapdragon phones:

```text
program's own VA-API code (FFmpeg, GStreamer va, Chromium)
  → libva → termuxva_drv_video.so     packages/android-vaapi
  → Unix socket: one NV12 picture in, one encoded picture out
  → termux-va daemon                  packages/termux-va
  → MediaCodec → Samsung's OMX encoders → the MFC hardware
```

The daemon lists the hardware encoders it found next to its socket, in `<socket>.encoders`, and
refuses Android's software encoders. On the S20 these are:

| Codec | Encoder |
| --- | --- |
| H.264 | `OMX.Exynos.AVC.Encoder` |
| HEVC | `OMX.Exynos.HEVC.Encoder` |
| VP9 | `OMX.Exynos.VP9.Encoder` |

The phone also has VP8, MPEG-4 Part 2 and H.263 encoders. The bridge does not offer them, and
VA-API has no encode entry point for MPEG-4 or H.263. There is no AV1 encoder. The bridge sends
8-bit pictures only; whether the encoders take 10-bit has not been checked. The full comparison
with what Android offers is in [handoff/s20-codec-parity.md](handoff/s20-codec-parity.md).

**Direct V4L2 access is not possible.** The MFC encoder is a V4L2 device (`/dev/video*`), and
Linux VA-API drivers for V4L2 exist, such as [libva-v4l2](https://github.com/Halhadus/va-v4l2).
Termux runs as an ordinary Android app (SELinux domain `untrusted_app`), and Android denies it
even listing those nodes. Only Android's own media service may open them. Using them would need
root and a changed SELinux policy.

## What works

| Program | State on the S20 |
| --- | --- |
| The daemon's own protocol test | 28 of 30 checks pass. Both failures are the extra key frame below |
| FFmpeg `h264_vaapi`, `hevc_vaapi` | Pass with driver revision 7 or later and a VA-API build of FFmpeg: 46 of 46 checks covering pixels, profiles, key frames, MP4 seeking and bitrate. Targets of 1 and 6 Mb/s gave 0.96 and 5.78 Mb/s. Colours are right only after colour metadata is added (below) |
| GStreamer `va` encoders, Serein's camera | Pass with revision 6 or later: 60 of 60 key frames with parameter sets; pictures above 47 dB at 8 Mb/s. Fails at low bitrates (below) |
| Chromium WebRTC, H.264 and VP9 | Works in a private test with `--enable-features=AcceleratedVideoEncoder`: about 284 frames per codec, received colours exact. **Not enabled by default** (below) |

## What does not work

### On a fresh installation

These are packaging and deployment problems. They mean that, as installed, programs on an
Exynos phone get no hardware encoder at all.

- **The installed FFmpeg has no VA-API.** The S20 had Termux's FFmpeg `9.0.2-1`, which lists
  zero VA-API encoders. This project's `ffmpeg` package (`9.0.2-100`, VA-API enabled) was not
  offered by the phone's package source; the cause has not been established.
- **The installed VA driver cannot find the Mali GPU.** `android-vaapi` revision 5 presents
  only the Snapdragon GPU as `/dev/dri/renderD128`. Revisions 7 and 8 present `/dev/mali0` and
  choose CPU-backed surfaces on Mali. They pass the device-discovery tests but are not yet
  released; they are on the `fix/chromium-webcodecs-shmem` branch.
- **GStreamer has no VA-API plugin.** No overlay installs `gst-plugins-va`, so GStreamer
  programs, Serein included, have no hardware encoder.
- **OBS Studio** has no recipe.

### Faults in the encoded video

- **No colour metadata.** Encoded streams do not say which colour matrix they use. Players then
  guess, and on the S20 the colour-patch check failed until BT.709 primaries, transfer and
  matrix were added with FFmpeg's `h264_metadata` / `hevc_metadata` filters. After that the
  pictures scored 42–48 dB, maximum channel error 1. Nothing adds this automatically yet.
- **An extra key frame in H.264 Baseline.** The Exynos encoder inserts a key frame nobody
  requested. Programs that count key frames, such as Serein's own check, reject the stream.
- **Low bitrates overshoot.** Serein's 600 kb/s all-intra camera stream came out at
  2.556 Mb/s. Samsung's encoder setup (see the source notes below) chooses its rate-control mode
  from a coefficient that MediaCodec's standard constant-bitrate request sets for normal video,
  not for video calls. A Samsung-specific MediaCodec setting may change this; it is untested.
- **Low-latency mode is refused.** The Exynos encoders reject MediaCodec's `low-latency` key
  (`configure failed with low-latency: -10000`). The daemon retries without it. Call latency has
  not been measured.

### Speed

- **One picture at a time.** The driver sends a picture and waits for its result. 720p30 fits.
  1080p30 has not been measured on the S20; on the Snapdragon it was at the limit.
- **Every picture is copied.** There is no shared GPU buffer allocator (GBM, dma-buf) for apps
  on Android, so pictures go through ordinary memory.
- **VA-API scaling is slow.** A 120-frame scale-and-transcode took 72 seconds. Serein's 720p
  screen-share pipeline, which converts through VA-API, managed 51 frames in 118 seconds, so
  screen sharing is not usable.

## Browsers

No browser hardware-encodes by default. The launcher adds no encoding switches.

**Chromium (this project's build).** WebRTC works in hardware behind a feature flag (above).
The same flag also enables WebCodecs `VideoEncoder`, which crashes Chromium's GPU process. On
Linux, Chromium asks for GPU-memory input frames. Here those are plain shared memory, and a
check in Chromium aborts. After three crashes Chromium turns GPU acceleration off for the
session. A patch that gives WebCodecs shared-memory input
([`0100-termux-webcodecs-shmem.patch`](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/packages/chromium/0100-termux-webcodecs-shmem.patch),
on the `fix/chromium-webcodecs-shmem` branch) is being built. Until it passes on the phone, the flag stays off. WebCodecs also needs
`bitrateMode: "constant"`: Chromium refuses variable bitrate on VA-API outside ChromeOS.

**Google Chrome (prebuilt).** It cannot take the Chromium patch, so the WebCodecs crash stays.
Its WebRTC cannot connect at all: it finds no network interfaces under Bionilux (zero ICE
candidates, `Could not bind NETLINK socket: Permission denied`). That is a networking problem,
not a video one.

**Firefox: off, and not pursued.** With this project's private FFmpeg runtime
(`android-firefox-video` revision 5, on the `fix/chromium-webcodecs-shmem` branch), Firefox does reach the Exynos encoders, and an H.264 WebRTC
call passes. Two problems in Firefox's own code remain, and this project cannot fix them without
building Firefox:

1. **WebCodecs mislabels a canvas's colours.** Firefox converts canvas pixels with the BT.601
   matrix, then tells the page the stream is BT.709. Pictures decode with visibly wrong colours
   (maximum channel error 22). Firefox's own software VP9 encoder gives exactly the same result,
   so this is not the hardware.
2. **WebRTC cannot lower a hardware call's bitrate.** Firefox applies a bitrate change on the
   fly only to `libx264` and Android's MediaCodec, and refuses it for VA-API encoders. A call
   keeps its starting bitrate until the resolution changes, so congestion control cannot react.

Firefox's hardware encoding therefore stays at Firefox's default, off. This Firefox has no
software H.264 encoder, so it cannot send H.264 in WebRTC or WebCodecs at all. VP9 calls use
its software encoder and work.

Revision 5 also fixes a third problem, so it is not reopened: Firefox declares the H.264 level's
frame-rate limit (450 fps at 320x180) instead of the capture rate. The encoder then spread its
bitrate over 450 pictures a second while 30 arrived, and the call stayed at 320x180. The
runtime now takes the rate from the pictures' timestamps.

## What cannot be fixed here

| Problem | Why | Only remedy |
| --- | --- | --- |
| Direct V4L2 access to the encoder | Android's SELinux policy | Root and a changed policy |
| Shared GPU buffers (no copies) | Android gives apps no GBM or dma-buf allocator | None realistic |
| Firefox's two problems above | Firefox's own code | Building Firefox, or a fix from Mozilla |
| Chrome's WebCodecs crash | Chrome is a closed binary | A change from Google |
| Extra key frame, low-bitrate overshoot | Possibly Samsung's encoder firmware | Untested vendor settings; otherwise workarounds only |

## Source notes

The S20's encoder declarations match LineageOS's for this phone, which make the Samsung code
path readable. The [x1s device](https://github.com/LineageOS/android_device_samsung_x1s)
inherits `universal9830-common`. That builds Samsung's OMX AVC, HEVC and VP9 encoders from
[`android_hardware_samsung_slsi-linaro_openmax`](https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_openmax).
They pass controls through Samsung's video library to V4L2 and the MFC driver in the
[universal9830 kernel](https://github.com/LineageOS/android_kernel_samsung_universal9830).

- **Rate control.** In the H.264 encoder setup, standard constant bitrate sets the reaction
  coefficient to 10 and the video-call mode sets 5. The kernel treats 1–5 as intra-limited
  constant bitrate and 6–10 as fixed constant bitrate.
- **Samsung's extension.** The openmax build enables `rtc-ext-enc-bitrate-mode`, with integer
  fields `value` (an OMX rate-control mode) and `bitrate`. Its MediaFormat names would be
  `vendor.rtc-ext-enc-bitrate-mode.value` and `.bitrate`. Check the installed encoder offers
  them before relying on them.
- **Samsung's low-latency extension** (`rtc-ext-enc-low-latency.enable`) is not the same as
  Android's `low-latency` key. It disables rate control and enables per-frame quantizers, so it
  is not a safe blanket setting.

## Testing

The suites are in [`tests/video-encode/`](../../tests/video-encode); see
[ENCODING.md](ENCODING.md#running-the-tests) for how to run them on a phone. Give scripts run
over SSH `</dev/null`, because their children read stdin. The camera suite records whoever is in
front of the phone: delete its media after checking.

Accept an encode only when the daemon log shows a session with pictures in and out, **and** the
output decodes in software to the right pictures. A listed encoder or profile is not an encode.
Never loop a crashing browser GPU process. On 2026-11-11 repeated WebCodecs crashes plus
back-to-back browser runs made Android kill Termux and the running desktop.
