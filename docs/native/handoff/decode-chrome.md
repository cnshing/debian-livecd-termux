# Handoff: Google Chrome hardware decoding

State on 2026-11-14. Chrome is Google's prebuilt arm64 glibc binary, run under Bionilux. It
cannot be patched, so every fix lives in the driver or the launcher. Shared rules and pass
criteria: [README.md](README.md).

## Status

**On by default** for VP9 and HEVC. H.264 and AV1 decode in software. Chrome is not in the
offline install: it downloads only when the phone is online.

| Codec | Adreno (Note10+) | Mali (S20) |
| --- | --- | --- |
| VP9 | passes, including a fresh install (2026-11-10, contact sheet checked) | **decodes in hardware but fails acceptance**: 192 frames out of the hardware decoder, but one of four comparisons scores SSIM 0.8987 against 0.90 |
| HEVC | passes | passes: 190 frames out of `OMX.Exynos.hevc.dec`, 4 of 4 |
| H.264 | software, by default | software, by default ([decode-h264.md](decode-h264.md)) |

## What it depends on

| Piece | Why |
| --- | --- |
| `android-vaapi-glibc` | The same bridge and patches built for glibc. On Adreno it sits beside the prebuilt Turnip stack; on Mali (revision 1) it brings its own softpipe driver and ION surfaces. It applies every `01xx` patch of the Bionic recipe |
| Shared VA completion adapter | Waits on `vaSyncSurface2` (500 ms limit) after `vaEndPicture`, for the same stale-frame reason as Chromium |
| Shared-buffer colour fallback | Without it Chrome shows wrong colours (negative control) |
| `TERMUX_VA_HEVC_REORDER_PICS=0` on Mali | Same HEVC stall as Chromium |
| ANGLE on the glibc PanVK (Mali) or Turnip (Adreno) | GPU compositing |

## Open problems

1. **The VP9 SSIM miss on Mali.** Frame numbers and colours are right, and the other three
   comparisons score 0.905 to 0.909. Only the windowed compositor capture of frame 36 misses.
   Software Chrome scores 0.921 there. The packaged driver and the earlier research build give
   the same score. The working guess is chroma upsampling in ANGLE's Vulkan NV12 path; nobody
   has shown it. Do not lower the threshold.
2. **H.264**: [decode-h264.md](decode-h264.md).
3. The user reported **black tearing in Chrome** on Adreno in early November. It was never
   reproduced: [decode-frame-sync.md](decode-frame-sync.md).

## Next steps

1. VP9 on Mali: compare the frame-36 capture with Chromium's (same phone, same driver code,
   Bionic) and with software Chrome, channel by channel. If only chroma differs, look at how
   ANGLE samples the NV12 import on PanVK.
2. Rerun on the Note10+ with the Mali-era glibc driver to confirm Adreno did not regress.

## How to test

The same harness as Chromium with `google-chrome` and `--browser-command` pointing at the
installed wrapper. The phone-wide matrix is `tests/browsers/run-phone-video-suite.py` (six
fullscreen cycles per case, private GNOME Shell on a private Termux:X11 server).

## Where things are

| What | Where |
| --- | --- |
| glibc driver recipe | `packages/android-vaapi-glibc` |
| Completion and colour adapters | `overlays/Browser+Chromium/browsers/` |
| Results | [X1S-BROWSER-VERIFICATION.md](../X1S-BROWSER-VERIFICATION.md), [native-acceleration-checks.md](../../browsers/native-acceleration-checks.md) |
