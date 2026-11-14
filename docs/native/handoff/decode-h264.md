# Handoff: H.264 hardware decoding through VA-API

State on 2026-11-14. This affects every VA-API client on every phone: Chromium, Chrome,
Firefox and native FFmpeg or GStreamer. mpv is not affected, because it calls MediaCodec
directly. Shared rules and pass criteria: [README.md](README.md).

## Status

**Off by default everywhere.** `disabled_va_codecs` defaults to `['h264', 'av1']`, and the
launcher turns each entry into `TERMUX_VA_DISABLE_H264=1` (`src/native/acceleration.py`). Every
browser decodes H.264 in software. H.264 is still the most common format on the web, so this
fix is worth the most of any decode work left.

Hardware H.264 decode does work when the stream suits the bridge's guess. FFmpeg through the
bridge decoded 1080p30 frame-exact against software (300 of 300 frames, Adreno, 2026-11-03).

## The bug

The bridge lives in `src/gallium/frontends/va/tva_bridge.c` of the pinned
[mesa-for-android-container](https://github.com/lfdevs/mesa-for-android-container) source that
`packages/android-vaapi` builds. MediaCodec wants an H.264 byte stream with SPS and PPS, but
VA-API hands the driver parsed parameters, not the original headers. So the bridge rebuilds the
SPS and PPS from those parameters.

VA-API does not carry the PPS field `num_ref_idx_l0_default_active_minus1`. The bridge guesses
`min(maxrefs, 3) - 1`. When the guess is wrong **and** the stream uses weighted prediction
(`weighted_pred_flag=1`), slices that rely on the default count get their `pred_weight_table`
read with the wrong length. MediaCodec then misparses them and drops frames. The VA client waits
for a picture that never comes: `vaSyncSurface` never returns and the player hangs, with no
fallback to software.

x264 with `-preset fast` produces such streams. The repository fixtures use `-preset medium`
(3 references, where the guess happens to be right), so **a passing fixture proves nothing**.

The bridge also guesses H.264's `max_num_reorder_frames` (2 when there are more than two
references). On Mali, expect the same stall that HEVC had (Exynos holds back exactly as many
pictures as declared; see [decode-firefox.md](decode-firefox.md)).

## The fix

1. **Make the failing control first.** Add a fixture encoded with x264 `-preset fast` and
   weighted prediction to `tests/browsers/make-video-fixtures.py` and its manifest. Confirm that
   it hangs or drops frames through the bridge today.
2. **Give MediaCodec the right PPS.** Two ways:
   - Recover the real default counts. VA-API's slice parameters carry each slice's active
     count (`num_ref_idx_l0_active_minus1`, and `l1` for B slices) but not
     `num_ref_idx_active_override_flag`. The slice data buffer holds the whole slice NAL, header
     included, so the bridge can read that flag itself. A slice with the flag at 0 uses the PPS
     default, so its active count is the true default. Rebuild the PPS with it, and resend the
     PPS if a later slice shows a different value. Check this layout against the clients that
     matter (FFmpeg, Chromium) before relying on it.
   - Or pass the stream's original PPS through, where the client gives one. VA-API has no
     standard field for it, so this only works for a client-specific path.
3. **Reorder count on Mali.** Add a variable like `TERMUX_VA_HEVC_REORDER_PICS` for H.264
   (`max_num_reorder_frames` in the rebuilt SPS VUI) and set it to 0 on Mali in the launcher.
4. **Only then** remove `h264` from the default in `src/native/acceleration.py`, with a host
   test, and rerun Chromium, Chrome and Firefox on both phones, the new fixture included.

The patch belongs in `packages/android-vaapi` as a new `01xx` patch.
`packages/android-vaapi-glibc` applies every `01xx` patch of the Bionic recipe, so Chrome gets
it too.

## How to test

- Without a browser: decode the new fixture with FFmpeg through the driver
  (`-hwaccel vaapi`) and compare every frame with a software decode. The script that did this for
  HEVC on the S20 (`hevc-latency.py`) is not in Git; it decodes a clip through the driver and
  compares frame by frame. A small version of it belongs in `tests/video-encode/` or
  `tests/browsers/`.
- Then the browser harnesses in [decode-chromium.md](decode-chromium.md) and
  [decode-firefox.md](decode-firefox.md) with the H.264 fixtures and `disabled_va_codecs` set to
  `['av1']` in a private config.

## Where things are

| What | Where |
| --- | --- |
| Bridge source | `src/gallium/frontends/va/tva_bridge.c` in the source `packages/android-vaapi/build.sh` fetches |
| Existing bridge patches | `packages/android-vaapi/01xx-*.patch` (0103 is the HEVC reorder count, a model for item 3) |
| Codec defaults | `video_environment` in `src/native/acceleration.py` |
| Fixtures | `tests/browsers/make-video-fixtures.py` |
