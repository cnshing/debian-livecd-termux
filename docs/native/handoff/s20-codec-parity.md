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

### Run-time capabilities (MediaCodecInfo, read 2026-11-14)

Read on the x1s with `tests/native/codec-info/CodecInfo.java`, a dex run through `app_process`
(build and run commands in that file). Raw output: `tests/native/codec-info/x1s-2026-11-14.jsonl`.
Where this differs from the XML above, it wins: it is what an Android app actually gets.

| Codec | Profiles offered | Max size | 4K rate | 8K rate |
| --- | --- | --- | --- | --- |
| H.264 dec | Baseline, Main, High, Constrained Baseline, Constrained High; **no High 10** | 8192x8192 | 64 | not offered |
| HEVC dec | Main, **Main 10**, Main 10 HDR10, Main 10 HDR10+ | 8192x8192 | 120 | 30 |
| VP9 dec | Profile 0, **Profile 2**, Profile 2 HDR, Profile 2 HDR10+ | 8192x8192 | 70 | **not offered** (XML says 8K30) |
| VP8 dec | Main | 8192x8192 | 120 | 30 |
| MPEG-4 Part 2 dec | Simple, Advanced Simple | **896x896** (XML says 2048) | n/a | n/a |
| H.263 dec | Baseline, H320, Backward-compatible, ISWV2 | **720x576** (XML says 2048x1152) | n/a | n/a |
| H.264 enc | Baseline, Main, High, CB, CH | 8192x8192 | 64 | not offered |
| HEVC enc | Main, **Main 10**, Main 10 HDR10 | 8192x8192 | 120 | 30 |
| VP9 enc | Profile 0, **Profile 2**, Profile 2 HDR | 4096x8192 | 70 | not offered |
| VP8 enc | Main | 3840x3840 | 120 | not offered |
| MPEG-4 Part 2 enc | Simple, Advanced Simple | 896x896 | n/a | n/a |
| H.263 enc | Baseline | 720x576 | n/a | n/a |

The HEVC and VP9 codecs (the only ones with 10-bit profiles) list one extra colour format,
2135032171 (`0x7f42016b`), a vendor value. It is presumably Samsung's 10-bit layout, which is
not named standard P010 (format 54); what it looks like in memory has not been checked. `low-latency` holds for every decoder except VP9, as the XML says.
All decoders offer `adaptive-playback`; no codec offers tunnelled playback.

## Where Linux programs stand

"VA-API" means every program that uses the bridge: FFmpeg, GStreamer, Chromium, Chrome and
Firefox's FFmpeg. mpv calls MediaCodec directly through FFmpeg, so it is a separate column.

### Decode

| Codec | Through VA-API | Through mpv | What is missing |
| --- | --- | --- | --- |
| H.264 | **off**: the bridge guesses a PPS field and can hang the player | passes | [decode-h264.md](decode-h264.md) |
| HEVC 8-bit | passes up to 1080p | passes | nothing above 1080p tested |
| HEVC 10-bit | untested; the bridge does write Main 10 into its rebuilt SPS | **passes** (FFmpeg MediaCodec, 48/48 frames, 2026-11-14) | bridge test; the bridge offers only `HEVC_MAIN`, so a P010 surface and the Main 10 profile need adding |
| VP9 profile 0 | passes up to 1080p | passes | nothing above 1080p tested |
| VP9 profile 2 (10-bit) | **not offered**: the bridge offers only profile 0 | **passes** (FFmpeg MediaCodec, 48/48, 2026-11-14) | add profile 2 and a P010 surface to the bridge |
| VP8 | **not offered**, and not a bridge-table fix: Mesa's gallium has no VP8 video format, no VA picture parser and no `VAProfileVP8` in its frontend. The daemon already maps `CODEC_VP8` | **decodes bit-exact** (YUV of all 48 frames equals libvpx, `OMX.Exynos.vp8.dec`), but the suite's RGB check fails: FFmpeg converts the MediaCodec frame as if full range | fix the range tag in FFmpeg's MediaCodec output (decode-native); for VA-API, add a VP8 pipe format, `picture_vp8.c` and the 3/10-byte frame-header rebuild to the Mesa fork |
| MPEG-4 Part 2 | **not offered**: Mesa's VA frontend dropped MPEG-4 Part 2, and the daemon protocol has no id for it | **passes** (`OMX.Exynos.mpeg4.dec`, 48/48, 640x360). Android limits it to 896x896 | VA-API needs a Mesa frontend for MPEG-4 plus a new protocol id; low value |
| H.263 | **not offered** | no FFmpeg MediaCodec decoder; Android limits it to 720x576 | VA-API's MPEG-4 profiles cover H.263 baseline streams; low value |
| AV1 | software, which is parity | software | nothing; keep it disabled on the S20 |
| 4K and 8K | untested | 4K HEVC: 120 frames in 2.0 s, **60 fps including start-up** (software: 30 fps), 2026-11-14; picture correctness at 4K not checked. 8K untested | 4K through the bridge; 8K fixture. Android declares 4K VP9 at 70 fps and no 8K VP9 |
| Low-latency decoding | not requested | not requested | optional |

### Encode

| Codec | Through VA-API | What is missing |
| --- | --- | --- |
| H.264 | works with faults: no colour metadata, an extra key frame in Baseline, low bitrates overshoot | [encode-native.md](encode-native.md) |
| HEVC | works, same colour-metadata fault | same |
| VP9 | works for the browsers' private tests; FFmpeg's `vp9_vaapi` has not been run on its own | add VP9 to the native suite |
| VP8 | **not offered**: the bridge maps H.264, HEVC and VP9 only | Mesa's gallium has no VP8 at all, so it needs the same Mesa work as VP8 decode plus a `CODEC_VP8_ENC` protocol id. Android caps it at 3840x3840 |
| MPEG-4 Part 2, H.263 | **not offered**, and VA-API has no encode entry point for them | cannot be reached through VA-API at all. Android caps them at 896x896 and 720x576. Parity would need another route, such as FFmpeg's direct MediaCodec encoders. Needs the user's decision |
| 10-bit | untested | the encoders offer it: HEVC Main 10 and VP9 profile 2 (MediaCodecInfo). Not H.264. Bridge offers neither |
| 4K and 8K | untested; one picture at a time and every picture copied. 1080p30 was already at the limit on the Note10+ | measure; pipelining in the driver would be the fix |
| Bitrate modes, low latency | standard CBR only; `low-latency` is refused by the encoders, so Android apps cannot use it either | [encode-native.md](encode-native.md) |

### On a fresh installation

None of the above is reachable as installed today. The installed driver (`android-vaapi`
revision 5) cannot find the Mali GPU, the installed FFmpeg has no VA-API, and no overlay
installs GStreamer's VA plugin. That comes first: [encode-native.md](encode-native.md). It
affects decoding through FFmpeg and GStreamer as well.

### Peer work (2026-11-14)

No peer PR is open yet. Branches pushed: `fix/decode-h264`, `fix/decode-frame-sync`,
`fix/decode-native`, `fix/decode-chromium`, `fix/decode-chrome`, `fix/decode-firefox`,
`fix/encode-native`, `fix/encode-chromium` (as `fix/chromium-webcodecs-shmem`),
`fix/encode-chrome`, `fix/encode-firefox`. Update the rows above as each merges.

Fixtures for the new rows: `tests/browsers/make-video-fixtures.py --codecs vp8 mpeg4`, and
`--ten-bit --codecs hevc vp9`; run them with `tests/browsers/test-native-mediacodec.py`.

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
