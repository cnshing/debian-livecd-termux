# Handoff: Firefox hardware encoding

State on 2026-11-18. Shared rules and pass criteria: [README.md](README.md).

## Status

**Note10+ / Adreno, 2026-11-18: on by default** when the session's termux-va daemon lists a
hardware H.264 encoder (`<socket>.encoders`) and android-firefox-video is revision 8 or later
(`firefox_encode_ready()` in `src/native/acceleration.py`). `"firefox_encode": false` in
`~/.config/livecd-native/acceleration.json` turns it off. **Mali keeps its opt-in**
(`"firefox_encode": true`): the S20 was not available to re-qualify the new patches.

One Firefox bug kept a hardware WebRTC call from adapting at all; it is patched in `packages/firefox`:

| Fix | Patch |
| --- | --- |
| WebRTC sets its target through `MediaDataEncoder::SetBitrate`, which `FFmpegDataEncoder` rejected (`NS_ERROR_NOT_IMPLEMENTED`); 1102 only covered `Reconfigure`. The call kept its 240-288 kb/s starting target whatever the link did | `1103-webrtc-set-bitrate.patch` (159.0-102) |
| Reports the H.264 slice QP from `WebrtcMediaDataEncoder` | `1104-webrtc-h264-qp.patch` (159.0-103). **Changed nothing measurable**: libwebrtc's `VideoStreamEncoder` already parses the QP (qpSum was 26-27 per picture before it). Drop it with the next Firefox rebuild |

**What the 1.151 Mb/s "failed step" was.** Per-packet traces (`test-firefox-ffmpeg.py --trace`,
size and PTS of every packet, each charged to the second of its own PTS) show the earlier failure
was the test content's floor: full-range noise opened directly at 500 kb/s also gives 1118 kb/s.
With low-contrast content the encoder steps 2000→500 kb/s (389/475/494/499 kb/s in the following
seconds) and 500→2000 kb/s (2095 in the first second), within 25% from the first second after the
change. The daemon and Qualcomm's `video-bitrate` parameter were never the problem.

**Installed qualification, 2026-11-18: firefox 159.0-103 / android-firefox-video 9.0.2-8 /
livecd-desktop 0.2.0-43**, default on through the installed launcher (`launcher_firefox_encode`
true, no `--firefox-encode`), private display and daemon, synthetic canvas, `livecd validate` 30/30:

| Test | Result |
| --- | --- |
| `step`: sender capped at 200 kb/s (RTCRtpSender maxBitrate) for 15 s | passes: 506 kb/s before, 158-217 kb/s from the first second of the cap, 22-27 pictures/s, back to 502 kb/s |
| `adapt`: media through a relay limited to 250 kb/s for 20 s, 150 ms drop-tail queue | passes: 510 kb/s before, under 312 kb/s after 1 s (143-239), 0% loss once adapted, 26-37 pictures/s, back to 510 kb/s; colours right at each phase |
| `adapt` with the receiver decoding in software | passes (reach 1 s, 0.6% loss) |
| Negative controls | the pre-1103 runs (`hw-step-1`, `hw-adapt-1`) fail both modes (sent 290-297 kb/s whatever the constraint); `adapt --expect software` fails on the hardware session |
| WebRTC H.264 loopback | passes: 640x360, colours right, picture viewed |
| WebCodecs H.264 | passes: 60/60, maximum colour error 4, BT.601 label |
| VP9 (WebRTC) | falls back to Firefox's software VP9: 640x360, no daemon session (the SD855 has no VP9 encoder). WebCodecs VP9 with `prefer-hardware` is reported unsupported |
| Chromium WebRTC/WebCodecs, Chrome WebRTC (regression) | pass: 287 / 60 (error 3) / 286 hardware pictures |

Tolerances: the step must stay within 25% of the cap from 3 s after the change; the adapted rate
must be under 125% of the link within 8 s, with no second without a picture, at least 10 pictures
a second, at least 320x180, under 5% loss, and a return to 90% of the earlier rate. The call must
first send 1.5 times the constraint, or the test proves nothing.

**Remaining, shared with Chromium:** with the noisy test canvas at 200-500 kb/s, flat areas of the
received picture lag behind: a region keeps an older hue next to the current one (pictures
`q2-adapt/phases.png`, `q3-adapt-swdec/phases.png`). Chromium's default hardware encoder shows the
same on the same content (`q3-chromium-step/phases.png`); Firefox's software VP8 does not. It is in
the bitstream, not the decoder (software decode shows it too), so it is Qualcomm's CBR rate
control skipping flat macroblocks at a high QP with the daemon's 3600-picture key-frame period.
Candidates in termux-va: VBR (`bitrate-mode` 1), or an intra-refresh period. The colour check
samples one column and does not catch it. Both browsers' calls also stay at 320x180 under this
content: libwebrtc's H.264 quality scaler keeps the size while QP is over 24, and caps 320x180 at
500 kb/s. Plain canvas calls reach 640x360.

Evidence: `temp/parity-note10-20261116/firefox/` on the host (`trace1`, `inst-*`, `hw-*`, `sw-*`).

The following describes the earlier S20 qualification and source patches.

**On main since PR #12 (2026-11-15); encoding stays opt-in, off by default, and has not been
tested on the phone with the patched build. Turning it on by default is the user's call.**

Opt in with `"firefox_encode": true` in `~/.config/livecd-native/acceleration.json`. The launcher
then sets `media.use-remote-encoder.video.platform` in its managed `user.js` block, only on Mali
and only when the installed `android-firefox-video` manifest lists its encoders
(`firefox_encode_ready()` in `src/native/acceleration.py`). Without the opt-in nothing changes.

Firefox 159.0.1 (Termux's current build) and Mozilla's main still have both bugs, so this project
builds Firefox itself:

| Fix | Where |
| --- | --- |
| WebCodecs labels the encoder's output BT.601 (`smpte170m`), the matrix libyuv converts canvas pixels with | `packages/firefox/1101-webcodecs-bt601-label.patch` |
| WebRTC may change a `*_vaapi` encoder's bitrate on the fly, as it already does for libx264 | `packages/firefox/1102-vaapi-bitrate-reconfigure.patch` |
| The VA-API encoder picks up a new `bit_rate` with its next picture | `packages/android-firefox-video/0103-follow-caller-bitrate.patch` (revision 6) |

`packages/firefox` is Termux's recipe at the pinned builder revision (159.0) plus those two patches.
It builds in a CI job of its own, like Chromium. Because of the apt pin, it replaces Termux's
Firefox until it is removed. android-firefox-video's manifest pins the Firefox binary, so the two
always build together. android-firefox-video revision 6 carries the encoder work below, and
android-vaapi carries the Mali backend and local-libdrm fixes.

See "Verification" at the end for what was proven on the phone.

## What was made to work

With the preference on and a private build of `android-firefox-video` revision 5, Firefox does reach the Exynos encoders:

| Use | Result on the S20 |
| --- | --- |
| WebRTC H.264 loopback | passes: 640x360, 246 frames encoded and 245 decoded, colours correct |
| WebCodecs H.264, VP9 | 60 of 60 chunks and decoded pictures, clean flush; colours wrong (problem 1) |
| WebCodecs HEVC | the configuration tested is reported unsupported |
| MediaRecorder | not run with hardware encoding |

Revisions 3 to 5 fixed, in order:

1. Firefox's FFmpeg was built without encoders. Revision 3 adds the VA-API encoders and an
   I420-to-NV12 upload, because Firefox submits I420 without a hardware frames context.
2. FFmpeg's hardware encoder crashed when Firefox drained an empty replacement encoder (NULL
   `pic_end`). Revision 4 guards it. Driver revision 8 also finds libdrm when Firefox loads it
   locally.
3. **The declared frame rate.** Firefox passes libwebrtc's `maxFramerate`, which is the H.264
   level's limit over the picture size (450 fps at 320x180), not the capture rate. VA-API has no
   timestamps, so the encoder spread its bitrate over 450 pictures a second while 30 arrived,
   and the call stayed at 320x180. Revision 5
   ([`0102-follow-real-picture-rate.patch`](https://github.com/cnshing/debian-livecd-termux/blob/main/packages/android-firefox-video/0102-follow-real-picture-rate.patch))
   declares at most 60 fps (otherwise 30) and scales the bitrate from the interval between
   timestamps, averaged over 32 pictures. Its device test passes 18 of 18 (1.80–2.06 Mb/s against
   2 Mb/s); revision 4 failed 6.

All of this is harmless while the preference is off.

## The two Firefox problems (patched in `packages/firefox`)

1. **WebCodecs mislabels a canvas's colours.** Firefox converts canvas pixels with BT.601 and
   then hands the page a decoder configuration saying BT.709
   ([`VideoEncoder::EncoderConfigToDecoderConfig`](https://github.com/mozilla-firefox/firefox/blob/28b7a7bffb5f82828143d9ad63839ad263b598be/dom/media/webcodecs/VideoEncoder.cpp#L605)
   hardcodes it). Its decoder prefers that configuration to the stream's own signalling, so
   writing BT.601 into the stream would not help. Maximum channel error 22, 16 of 60 pictures
   over 16. **Firefox's own software VP9 encoder gives exactly the same numbers**, so this is not
   the hardware. The saved hardware streams decode to error 2 with the right matrix.
2. **WebRTC cannot change a hardware encoder's bitrate mid-call.**
   [`FFmpegDataEncoder::ProcessReconfigure`](https://github.com/mozilla-firefox/firefox/blob/28b7a7bffb5f82828143d9ad63839ad263b598be/dom/media/platforms/ffmpeg/FFmpegDataEncoder.cpp#L287)
   applies a bitrate change only to `libx264` and Android's MediaCodec, and rejects it for
   `h264_vaapi`. A call keeps its starting bitrate until the resolution changes, so congestion
   control cannot lower it.

Both are patched in this project's Firefox build (table above); neither patch has run on the
phone yet.

## Before dropping the patched build or enabling Mali by default

1. Check whether Mozilla has fixed `EncoderConfigToDecoderConfig` (1101), `ProcessReconfigure`
   (1102), `FFmpegDataEncoder::SetBitrate` (1103) and the H.264 QP in `WebrtcMediaDataEncoder`
   (1104), so the patched build can be dropped.
2. Accept with the canvas WebCodecs case, a WebRTC loopback, `step` and `adapt`, never with the
   BT.709 control alone. Do not loosen the pixel check.
3. Mali: rerun all four on the S20 through the installed launcher with `"firefox_encode": true`
   before considering a default there.

## How to test

[`tests/video-encode/test-firefox-ffmpeg.py`](https://github.com/cnshing/debian-livecd-termux/blob/main/tests/video-encode/test-firefox-ffmpeg.py)
loads the runtime's codec libraries the way Firefox does. It checks an empty drain for H.264,
HEVC and VP9, and five streams per codec whose declared and real frame rates differ. The
WebCodecs probe is
[`tests/video-encode/webcodecs.html`](https://github.com/cnshing/debian-livecd-termux/blob/main/tests/video-encode/webcodecs.html)
(see [encode-chromium.md](encode-chromium.md)). Bitrate response:
`test-firefox-ffmpeg.py --library-dir <runtime>/ffmpeg/lib --trace NEW_DIR` (per-packet traces,
saved streams can be decoded and viewed). Congestion control:
`test-browser-encode.py firefox --mode step|adapt --out NEW_DIR` (the relay and pass criteria are
described in the script). Run Firefox with
`MOZ_LOG=FFmpegVideo:5,PlatformEncoderModule:5` and a private profile.

## Where things are

| What | Where |
| --- | --- |
| Runtime | `packages/android-firefox-video` (revision 6) |
| Full record | [ENCODING-EXYNOS.md](../ENCODING-EXYNOS.md) |
