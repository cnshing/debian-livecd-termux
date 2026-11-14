# Handoff: native hardware decoding (mpv, FFmpeg, GStreamer)

State on 2026-11-14. "Native" means programs other than the browsers. Shared rules and pass
criteria: [README.md](README.md).

## Status

| Program | Adreno (Note10+) | Mali (S20) |
| --- | --- | --- |
| mpv, through its launcher | passes VP9, H.264 and HEVC: hardware decode plus numbered-frame pixels, Vulkan `gpu-next` rendering | passes VP9, H.264 and HEVC on its own route: VirGL on the vendor GLES driver for rendering, MediaCodec for decoding |
| FFmpeg `-hwaccel vaapi` | frame-exact VP9, HEVC, H.264 in development tests (2026-11-03) | HEVC frame-exact on three clips with `TERMUX_VA_HEVC_REORDER_PICS=0`; hangs without it |
| GStreamer `va` decoders | not tested | not tested; `gst-plugins-va` is not installed by any overlay |

**mpv is the one that works for users.** It does not use VA-API: the launcher passes
`--hwdec=mediacodec-copy --vd-lavc-o=ndk_codec=1` (`src/native/acceleration.py`), so FFmpeg
inside mpv calls MediaCodec directly. That is why H.264 works in mpv but not in the browsers.
mpv also opens SMB shares through a GIO bridge in the launcher, because there is no FUSE.

## Gaps for VA-API programs

These come from reading the code; none has been run on a phone.

1. **Programs started from the desktop session get the decoders, without the browser
   safeguards.** The session preload (`native_encode` in `src/native/desktop.py`) points libva
   at the bridge, and hides its decoders only when `native_decode` is `false` in
   `acceleration.json`. It does not set `TERMUX_VA_DISABLE_H264`, `TERMUX_VA_DISABLE_AV1` or, on
   Mali, `TERMUX_VA_HEVC_REORDER_PICS=0`. Those are set only for programs run through the
   launcher (`video_environment`). So FFmpeg run from a terminal with `-hwaccel vaapi` can hit
   the H.264 hang ([decode-h264.md](decode-h264.md)), and on Mali the HEVC stall. (ENCODING.md
   said the opposite until 2026-11-14; the code is as described here.)
2. **FFmpeg on a fresh S20 has no VA-API at all.** The phone has Termux's FFmpeg `9.0.2-1`; this
   project's `ffmpeg` `9.0.2-100` was not offered by its package source. See
   [encode-native.md](encode-native.md).
3. **The installed driver on the S20 cannot find the Mali GPU** for programs that scan
   `/dev/dri`: `android-vaapi` revision 5 presents only the Snapdragon GPU. Revisions 7 and 8
   present `/dev/mali0` but are not released ([encode-native.md](encode-native.md)).

## Next steps

1. Decide what the session should offer, then make it match the launcher. The simplest fix is
   to apply the same codec list and Mali variables in `native_encode()` as `video_environment`
   does, sharing the code. Add a host test beside the existing desktop tests.
2. Move mpv on Mali from VirGL to PanVK. It passed direct Vulkan rendering on PanVK in the
   desktop acceptance; the change is in `src/native/mali.py` and the mpv profile.
3. Install `gst-plugins-va` in the Video Player overlay and test GStreamer decoding.

## How to test

- mpv: `tests/browsers/test-native-mediacodec.py` decodes the numbered fixtures through FFmpeg's NDK MediaCodec path, the one mpv uses.
  `tests/browsers/test-acceleration.py mpv` runs mpv itself through the launcher.
- FFmpeg through the bridge: decode a clip with `-hwaccel vaapi -hwaccel_output_format vaapi`
  and compare every frame with a software decode (`-f framemd5`). Give it the same environment
  a desktop-session terminal has, not the launcher's, to test gap 1.

## Where things are

| What | Where |
| --- | --- |
| Session preload and decode switch | `native_encode()` in `src/native/desktop.py` |
| Launcher profiles (mpv flags, VA environment) | `src/native/acceleration.py` |
| mpv on Mali | `src/native/mali.py` |
| Adreno results | [native-acceleration-checks.md](../../browsers/native-acceleration-checks.md) |
