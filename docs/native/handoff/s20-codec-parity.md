# Handoff: parity with the S20's own video hardware

State on 2026-11-14. Shared rules and pass criteria: [README.md](README.md).

## The acceptance criterion

> Feature parity with the S20's native encoding and decoding capabilities.

Read here as: a Linux program on the S20 can use every hardware codec that Android itself
offers on that phone, up to the limits Android declares for it. This page turns that into a
checklist. Every other page in this folder now feeds into it.

The codecs belong to the Exynos 990's MFC block, not to the Mali-G77 GPU. The GPU only draws the
decoded pictures. So the target is Samsung's codec list, which apps reach through MediaCodec.

## The target: what Android offers on the S20

Taken from the phone's `/vendor/etc/media_codecs.xml`, read on 2026-11-13. Apart from the
telephony domain it matches LineageOS's
[`configs/media/media_codecs.xml`](https://github.com/LineageOS/android_device_samsung_universal9830-common/blob/96d43e19d657df7d8c8732973150b0b722df989c/configs/media/media_codecs.xml)
for this phone, which can be read without the phone. Frame rates are the declared limit: the codec's blocks per second divided
by the blocks in one picture. They are upper bounds, not measurements.

| Codec | Decoder | Decode limit | Encoder | Encode limit |
| --- | --- | --- | --- | --- |
| H.264 | `OMX.Exynos.avc.dec` | 8192x8192; 4K120, 8K30 | `OMX.Exynos.AVC.Encoder` | 8192x8192; 4K120, 8K30 |
| HEVC | `OMX.Exynos.hevc.dec` | 8192x8192; 4K120, 8K30 | `OMX.Exynos.HEVC.Encoder` | 8192x8192; 4K120, 8K30 |
| VP9 | `OMX.Exynos.vp9.dec` | 8192x8192; 4K120, 8K30 | `OMX.Exynos.VP9.Encoder` | 4096x8192; 4K120 |
| VP8 | `OMX.Exynos.vp8.dec` | 8192x8192; 4K120, 8K30 | `OMX.Exynos.VP8.Encoder` | 3840x2160; 4K120 |
| MPEG-4 Part 2 | `OMX.Exynos.mpeg4.dec` | 2048x2048; 1080p119 | `OMX.Exynos.MPEG4.Encoder` | 2048x2048; 1080p119 |
| H.263 | `OMX.Exynos.h263.dec` | 2048x1152; 1080p119 | `OMX.Exynos.H263.Encoder` | 2048x1152; 1080p119 |
| AV1 | none | software only, on Android too | none | |

Measured rates are in the phone's
[`media_codecs_performance.xml`](https://github.com/LineageOS/android_device_samsung_universal9830-common/blob/96d43e19d657df7d8c8732973150b0b722df989c/configs/media/media_codecs_performance.xml)
(LineageOS copy, not yet compared with the installed file). Frames per second Android measured:

| Codec | 1080p | 4K |
| --- | --- | --- |
| HEVC decode | 520–580 | 140–170 |
| VP9 decode | 360–420 | not listed |
| VP8 decode | 340–420 | not listed |
| H.264 encode | 80–176 | not listed |
| HEVC encode | 70–154 | not listed |
| VP8, VP9 encode | 50–110 | not listed |

So the hardware itself decodes 4K HEVC at well over 60 fps and encodes 1080p at 50 fps or more.
This project has measured nothing above 1080p30 on the S20.

Other declared features: `adaptive-playback` on every decoder, and `low-latency` on every
decoder except VP9. Secure decoders (`.secure`) exist for H.264, HEVC and VP9; they serve DRM
playback into protected buffers and are left out of parity here. Say so if you disagree.

Not in the XML and **not yet known**: the profiles and bit depths (HEVC Main 10, VP9 profile 2,
H.264 High 10) and colour formats. Android reports those only at run time, through
`MediaCodecInfo`. The board sets a 10-bit buffer alignment and an HDR10 plugin,
so 10-bit HEVC is likely; it has not been checked.

## Where Linux programs stand

"VA-API" means every program that uses the bridge: FFmpeg, GStreamer, Chromium, Chrome and
Firefox's FFmpeg. mpv calls MediaCodec directly through FFmpeg, so it is a separate column.

### Decode

| Codec | Through VA-API | Through mpv | What is missing |
| --- | --- | --- | --- |
| H.264 | **off**: the bridge guesses a PPS field and can hang the player | passes | [decode-h264.md](decode-h264.md) |
| HEVC 8-bit | passes up to 1080p | passes | nothing above 1080p tested |
| HEVC 10-bit | untested; the bridge does write Main 10 into its rebuilt SPS | untested | test it; check the driver offers a P010 surface |
| VP9 profile 0 | passes up to 1080p | passes | nothing above 1080p tested |
| VP9 profile 2 (10-bit) | untested | untested | test it |
| VP8 | **not offered**: the bridge maps only H.264, HEVC, VP9 and AV1 | untested; FFmpeg has a MediaCodec VP8 decoder | add VP8 to the bridge (`tva_codec_id`, the daemon's codec table) |
| MPEG-4 Part 2 | **not offered** | untested; FFmpeg has a MediaCodec MPEG-4 decoder | add to the bridge; VA-API has MPEG-4 profiles |
| H.263 | **not offered** | no FFmpeg MediaCodec decoder | VA-API's MPEG-4 profiles cover H.263 baseline streams; low value |
| AV1 | software, which is parity | software | nothing; keep it disabled on the S20 |
| 4K and 8K | untested | untested | measure frame rate and dropped frames; every picture is copied through ordinary memory |
| Low-latency decoding | not requested | not requested | optional |

### Encode

| Codec | Through VA-API | What is missing |
| --- | --- | --- |
| H.264 | works with faults: no colour metadata, an extra key frame in Baseline, low bitrates overshoot | [encode-native.md](encode-native.md) |
| HEVC | works, same colour-metadata fault | same |
| VP9 | works for the browsers' private tests; FFmpeg's `vp9_vaapi` has not been run on its own | add VP9 to the native suite |
| VP8 | **not offered**: the bridge maps H.264, HEVC and VP9 only | add VP8 to the bridge and daemon; FFmpeg has `vp8_vaapi` |
| MPEG-4 Part 2, H.263 | **not offered**, and VA-API has no encode entry point for them | cannot be reached through VA-API at all. Parity would need another route, such as FFmpeg's direct MediaCodec encoders. Needs the user's decision |
| 10-bit | untested | find out whether the encoder offers it, then test |
| 4K and 8K | untested; one picture at a time and every picture copied. 1080p30 was already at the limit on the Note10+ | measure; pipelining in the driver would be the fix |
| Bitrate modes, low latency | standard CBR only; `low-latency` is refused by the encoders, so Android apps cannot use it either | [encode-native.md](encode-native.md) |

### On a fresh installation

None of the above is reachable as installed today. The installed driver (`android-vaapi`
revision 5) cannot find the Mali GPU, the installed FFmpeg has no VA-API, and no overlay
installs GStreamer's VA plugin. That comes first: [encode-native.md](encode-native.md). It
affects decoding through FFmpeg and GStreamer as well.

## Order of work

1. **Deployment** ([encode-native.md](encode-native.md), steps 1–3). Without it nothing else
   reaches a user.
2. **Read the run-time capabilities** of every S20 codec: profiles, colour formats, performance
   points. Termux has no Java API for `MediaCodecList`. A small dex run with `app_process` works,
   as the display-power helper did for the fresh-install tests. Compare the phone's
   `/vendor/etc/media_codecs_performance.xml` with the LineageOS copy above. Add the results to
   this page, so the target is complete and in Git.
3. **H.264 decode** ([decode-h264.md](decode-h264.md)): the biggest gap for users.
4. **VP8** decode and encode in the bridge and daemon. The structure is already there for VP9.
5. **10-bit** HEVC and VP9 decode, then encode if the encoders offer it.
6. **4K and 8K** decode and encode measurements; driver pipelining if encode cannot keep up.
7. **MPEG-4 Part 2 decode** in the bridge. Ask the user whether MPEG-4 and H.263 *encode* are in
   scope: they cannot go through VA-API.
8. The encode faults in [encode-native.md](encode-native.md): colour metadata, the extra key
   frame, the bitrate modes.

## How to accept a row

Use the standard in [README.md](README.md), for each codec, profile and size:

- **Decode:** every frame of a clip decoded through the bridge matches a software decode (or
  stays within the fixture's thresholds where the codec is lossy at the output). The daemon log
  shows the Exynos decoder. Do it with FFmpeg first, then in the browsers that offer the codec.
- **Encode:** the daemon log shows the Exynos encoder with pictures in and out, the stream decodes
  in software to the right pictures, the bitrate is within range of the target, and the colour
  metadata is present.
- **Sizes:** at 4K and 8K, also record frames per second and dropped frames against the declared
  limit. A row passes at a size only if it keeps real time there.

## Where things are

| What | Where |
| --- | --- |
| Bridge codec tables | `tva_codec_id`, `tva_encode_codec_id` in `src/gallium/frontends/va/tva_bridge.c`, in the source `packages/android-vaapi` builds |
| Daemon encoder list | `packages/termux-va/0001-encoder-for-snapdragon-omx.patch`; the running daemon writes `<socket>.encoders` |
| Samsung's codec source | [LineageOS slsi-linaro openmax](https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_openmax), [universal9830-common](https://github.com/LineageOS/android_device_samsung_universal9830-common) |
