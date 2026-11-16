# Handoff: Chromium hardware decoding

State on 2026-11-14. Chromium here is this project's source build (`packages/chromium`,
156.0.8078.79, Bionic, VA-API enabled). Shared rules and pass criteria:
[README.md](README.md).

## Status

**On by default** for VP9 and HEVC. H.264 and AV1 decode in software.

| Codec | Adreno (Note10+) | Mali (S20) |
| --- | --- | --- |
| VP9 | passes: `VaapiVideoDecoder`, browser and compositor pixels, fullscreen cycles, fresh install 2026-11-10 | passes: 200 frames out of the hardware decoder, 4 of 4 frame comparisons, through the installed launcher 2026-11-13. Again on 2026-11-15 with revision 3 and the dma-heap bridge (SSIM 0.909, 0 dropped frames, frames viewed; `--require-gpu` finds the GPU process holding `/dev/mali0` with PanVK mapped) |
| HEVC | not accepted on the source build (see below) | passes: 198 frames out of `OMX.Exynos.hevc.dec`, 4 of 4. Again on 2026-11-15 with revision 3 and the dma-heap bridge (SSIM 0.911, frames viewed) |
| H.264 | software, by default | software, by default ([decode-h264.md](decode-h264.md)) |
| AV1 | software; no hardware decoder | software; never tried |

## What it depends on

| Piece | Why |
| --- | --- |
| `android-vaapi` ≥ 2 | Private `libva.so.2` / `libva-drm.so.2` aliases. Chromium dlopens those names; Termux's libva has unversioned files |
| Bounded wait at `vaEndPicture` (`TERMUX_VA_SYNC_END_PICTURE=1`, set by the launcher for Chromium) | Without it the compositor shows an older frame than the browser captured. `LIVECD_VA_DISABLE_COMPLETION=1` is the negative control |
| `android-vaapi` ≥ 11 on Mali: `libandroid-dma-heap.so`, loaded by the launcher | DMA-BUF surfaces, so ANGLE can import decoded frames. With `LIVECD_DMA_HEAP_ION=0` Chromium falls back to `VpxVideoDecoder` (checked 2026-11-15), so the library is required on ION-only phones |
| `TERMUX_VA_HEVC_REORDER_PICS=0` on Mali (launcher) | Exynos's HEVC decoder holds back as many pictures as the bridge declares (3). Chromium's per-picture wait then fails and it falls back to software. At 0 the decoder returns each picture at once |
| ANGLE on Vulkan: PanVK on Mali, Turnip on Adreno | GPU compositing |

## Open problems

1. **HEVC on Adreno: passes since 2026-11-16.** On the v0.12.0 fresh install of the Note10+
   (revision 3, `android-vaapi` 11 with the dma-heap preload), `test-fullscreen.py
   --require-hardware-decode` passed HEVC with no reorder override: 298 units in, 295 frames out,
   pictures checked. VP9 and H.264 passed in the same run.
2. **H.264** is on by default on Adreno and still software on Mali. See
   [decode-h264.md](decode-h264.md).
3. **One stale compositor frame** in 13 Adreno runs under concurrent encoder load. See
   [decode-frame-sync.md](decode-frame-sync.md).
4. Not run: a 30-minute soak and seeking. The Adreno regression with the Mali-era packages
   passed on 2026-11-16.

## Next steps

1. Run the H.264 browser harnesses on the S20, then take `h264` out of Mali's default disabled
   list too (done for Adreno on 2026-11-16).
2. The soak and seek runs.

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

## H.264 (not yet run)

All three next steps above are still open. Step 2 is no longer blocked: android-vaapi revision 10
and later (on main) rebuild the PPS from the slice headers ([decode-h264.md](decode-h264.md)). To
test, set `disabled_va_codecs=['av1']` in a private config, set `TERMUX_VA_H264_REORDER_FRAMES=0`
on Mali, and make the fixture with `make-video-fixtures.py --codecs h264-fast`.
