# Handoff: Firefox hardware encoding

State on 2026-11-14. Shared rules and pass criteria: [README.md](README.md).

## Status

**Off, by the user's decision of 2026-11-14. Do not spend more work on it** unless Mozilla fixes
the two problems below or the user changes the decision.
`media.use-remote-encoder.video.platform` stays at Firefox's default (off outside Nightly), and
the launcher sets nothing for encoding. That one preference gates WebCodecs and WebRTC hardware
encoding together.

What this means for users: this Firefox has no software H.264 encoder (no OpenH264 plugin), so
it cannot send H.264 in WebRTC or WebCodecs at all. An H.264 call connects with zero frames.
VP9 calls use its software encoder and work.

## What was made to work

With the preference on and the private runtime `android-firefox-video` revision 5 (on the CI
branch only), Firefox does reach the Exynos encoders:

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
   ([`0102-follow-real-picture-rate.patch`](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/packages/android-firefox-video/0102-follow-real-picture-rate.patch))
   declares at most 60 fps (otherwise 30) and scales the bitrate from the interval between
   timestamps, averaged over 32 pictures. Its device test passes 18 of 18 (1.80–2.06 Mb/s against
   2 Mb/s); revision 4 failed 6.

All of this is harmless while the preference is off and is kept on the CI branch.

## The two problems left, both in Firefox

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

Fixing either means patching and building Firefox (a job comparable to Chromium's), or a fix
from Mozilla. Both would be small patches in those two functions.

## If it is reopened

1. Check whether Mozilla has fixed either function in the Firefox Termux ships.
2. Merge `android-firefox-video` revision 5 and `android-vaapi` revision 8 to main.
3. Set the preference in the launcher's managed `user.js` block (`firefox_preferences` in
   `src/native/acceleration.py`), on Mali, gated by the package version.
4. Accept with the canvas WebCodecs case and a WebRTC loopback, never with the BT.709 control
   alone. Do not loosen the pixel check.

## How to test

On the CI branch:
[`tests/video-encode/test-firefox-ffmpeg.py`](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/tests/video-encode/test-firefox-ffmpeg.py)
loads the runtime's codec libraries the way Firefox does. It checks an empty drain for H.264,
HEVC and VP9, and five streams per codec whose declared and real frame rates differ. The
WebCodecs probe is
[`tests/video-encode/webcodecs.html`](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/tests/video-encode/webcodecs.html)
(see [encode-chromium.md](encode-chromium.md)). Run Firefox with
`MOZ_LOG=FFmpegVideo:5,PlatformEncoderModule:5` and a private profile.

## Where things are

| What | Where |
| --- | --- |
| Runtime | `packages/android-firefox-video` (revision 5 on the CI branch; main has revision 2) |
| Full record | [VIDEO-ENCODING-HANDOFF.md](../VIDEO-ENCODING-HANDOFF.md), [ENCODING-EXYNOS.md](../ENCODING-EXYNOS.md) |
