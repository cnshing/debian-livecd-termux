# Handoff: Chromium hardware decoding

State on 2026-11-14. Chromium here is this project's source build (`packages/chromium`,
156.0.8078.79, Bionic, VA-API enabled). Shared rules and pass criteria:
[README.md](README.md).

## Status

**On by default** for VP9 and HEVC. H.264 and AV1 decode in software.

| Codec | Adreno (Note10+) | Mali (S20) |
| --- | --- | --- |
| VP9 | passes: `VaapiVideoDecoder`, browser and compositor pixels, fullscreen cycles, fresh install 2026-11-10 | passes: 200 frames out of the hardware decoder, 4 of 4 frame comparisons, through the installed launcher 2026-11-13 |
| HEVC | not accepted on the source build (see below) | passes: 198 frames out of `OMX.Exynos.hevc.dec`, 4 of 4 |
| H.264 | software, by default | software, by default ([decode-h264.md](decode-h264.md)) |
| AV1 | software; no hardware decoder | software; never tried |

## What it depends on

| Piece | Why |
| --- | --- |
| `android-vaapi` ≥ 2 | Private `libva.so.2` / `libva-drm.so.2` aliases. Chromium dlopens those names; Termux's libva has unversioned files |
| Bounded wait at `vaEndPicture` (`TERMUX_VA_SYNC_END_PICTURE=1`, set by the launcher for Chromium) | Without it the compositor shows an older frame than the browser captured. `LIVECD_VA_DISABLE_COMPLETION=1` is the negative control |
| `android-vaapi` ≥ 3 on Mali | ION dma-buf surfaces, so ANGLE can import decoded frames |
| `TERMUX_VA_HEVC_REORDER_PICS=0` on Mali (launcher) | Exynos's HEVC decoder holds back as many pictures as the bridge declares (3). Chromium's per-picture wait then fails and it falls back to software. At 0 the decoder returns each picture at once |
| ANGLE on Vulkan: PanVK on Mali, Turnip on Adreno | GPU compositing |

## Open problems

1. **HEVC on Adreno.** The launcher sets the reorder variable on Mali only. Chromium's source
   build has passed VP9 on Adreno but not HEVC; the earlier prebuilt Debian Chromium passed both.
   The likely cause is the same reorder stall, but the bridge's source says Qualcomm's decoder
   stops returning frames at 0. Try a count of 1 on the Note10+ (it gave identical frames on the
   S20) before changing the default.
2. **H.264** is the most common web format and is software everywhere. See
   [decode-h264.md](decode-h264.md).
3. **One stale compositor frame** in 13 Adreno runs under concurrent encoder load. See
   [decode-frame-sync.md](decode-frame-sync.md).
4. Not run: a 30-minute soak, seeking, and the Adreno regression with the Mali-era packages
   (`android-vaapi` 5 and later).

## Next steps

1. On the Note10+, run HEVC with `TERMUX_VA_HEVC_REORDER_PICS=1` and `=0`; if one passes, set it
   in `video_environment` in `src/native/acceleration.py` with a host test.
2. After the H.264 bridge fix, take `h264` out of the default disabled list and rerun both
   phones.
3. The soak and seek runs.

## How to test

```sh
# On the phone, from a short directory holding browsers/ and fixtures-v2/
python browsers/test-fullscreen.py chromium --browser-command "$PREFIX/bin/chromium-browser" \
  --x-server lorie --renderer zink --browser-flag=--window-size=1280,1100 \
  --require-gpu --require-hardware-decode --private-daemon --media-dir fixtures-v2 \
  --fixture-manifest fixtures-v2/manifest.json --case chart-vp9.webm --cycles 2 --out c1
```

Use `--case chart-hevc.mp4` for HEVC. Keep `--out` short: a long path pushes the private
`va.sock` past the socket path limit. The fixtures are regenerated from the manifest's FFmpeg
command; check their hashes. Host checks: `python3 tests/packaging/test-mali-acceleration.py`.

## Where things are

| What | Where |
| --- | --- |
| Launcher environment and flags | `video_environment`, `command_line()` in `src/native/acceleration.py` |
| ION surfaces | `packages/android-vaapi/tva_ion_winsys.h` |
| HEVC reorder count | `packages/android-vaapi/0103-hevc-reorder-count.patch` |
| Results | [X1S-BROWSER-VERIFICATION.md](../X1S-BROWSER-VERIFICATION.md), [native-acceleration-checks.md](../../browsers/native-acceleration-checks.md) |

## Outcome of the 2026-11-14 attempt (agent decode-chromium)

Nothing changed in code. Step 1 needs the Note10+, which was not attached (`adb devices`
listed only the x1s). Step 2 is waiting on the H.264 bridge fix ([decode-h264.md](decode-h264.md)).
Step 3, the soak and seek runs, needs the x1s, and another agent had claimed it in
`temp/PHONE-STATUS` (a 20-cycle qualification). So all three next steps are still open as written above.
