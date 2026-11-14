# Handoff: Firefox hardware decoding

State on 2026-11-14. Firefox is Termux's build. Its hardware decoding comes from
`android-firefox-video`: a port of Mozilla's graphics probe plus VA-API FFmpeg libraries, under
`$PREFIX/lib/android-firefox-video`. Shared rules and pass criteria: [README.md](README.md).

## Status

**On by default** for VP9 and HEVC. H.264 and AV1 decode in software.

| Codec | Adreno (Note10+) | Mali (S20) |
| --- | --- | --- |
| VP9 | passes, fresh install 2026-11-10 (`hardware_verified: true`) | passes: 354 pictures in and 354 frames out; frames 12 and 36 correct at browser and compositor; 569 WebGL frames beside it, none wrong |
| HEVC | passes | passes: 369 in, 369 out of `OMX.Exynos.hevc.dec`. The installed launcher was checked on 2026-11-13 with `tests/browsers/test-acceleration.py firefox` |
| H.264 | software, by default | software, by default ([decode-h264.md](decode-h264.md)) |

**On Mali, only on a Zink desktop.** Firefox's GL uses PanVK only when the desktop renderer is
Zink (`gpu_enabled`). On a software desktop it renders and decodes in software.

## What it depends on

| Piece | Why |
| --- | --- |
| `android-firefox-video` ≥ 9.0.2-2 | The probe accepts Zink on PanVK with `/dev/mali0`, as it does Turnip with KGSL. Without a render device Firefox never runs its VA-API probe. A manifest ties it to one Firefox build. A mismatch starts Firefox in software with a warning |
| `android-vaapi` ≥ 4 | The driver reads `TERMUX_VA_GALLIUM_DRIVER`, not the application's `GALLIUM_DRIVER` (Firefox's is `zink`, which the driver's private Mesa lacks) |
| `android-vaapi` ≥ 5 and `TERMUX_VA_HEVC_REORDER_PICS=0` on Mali | Without it HEVC hangs: `6 units in, 0 frames out`, no fallback |
| `mesa` ≥ 26.2.6-103 (`0023-zink-skip-missing-dmabuf-fence-semaphores`) | PanVK cannot create SYNC_FD semaphores. Zink read one per dma-buf plane from an empty array and crashed Firefox on the first imported frame |
| Launcher on Mali | `MOZ_DRM_DEVICE=/dev/mali0`; Firefox keeps its own `GALLIUM_DRIVER` |

## Open problems

1. **A new Firefox breaks hardware decoding until the package is rebuilt.** The manifest check
   is there because the probe port is tied to one Firefox build. Termux updates Firefox on its
   own schedule; after an update, Firefox decodes in software until `android-firefox-video` is
   rebuilt. Watch for it after each Firefox release.
2. **H.264**: [decode-h264.md](decode-h264.md). Firefox reports `H264 SWDEC`.
3. **Flicker.** The user reported Firefox video flickering back and forth on Adreno in early
   November. It was never reproduced: [decode-frame-sync.md](decode-frame-sync.md).
4. Firefox on a software desktop on Mali could use PanVK as Chromium does, with a small change
   in `gpu_enabled`. Untested.
5. Not run: seeking, a soak, and `TERMUX_VA_SYNC_END_PICTURE` (set for Chromium only; Firefox
   passed without it).

## Next steps

1. After each Termux Firefox update, rebuild `android-firefox-video` and rerun
   `tests/browsers/test-acceleration.py firefox` on both phones.
2. Soak and seek with VP9 and HEVC, watching for flicker.

## How to test

```sh
# On the phone, from a short directory holding browsers/ and fixtures-v2/
python browsers/test-acceleration.py firefox --fixtures fixtures-v2 --out f1
python browsers/test-acceleration.py firefox --fixtures fixtures-v2 --case chart-hevc.mp4 --out f2
```

It checks browser pixels and keeps the VA-API init, frame and software-codec evidence even when
playback fails. Host checks:

```sh
python3 tests/packaging/test-firefox-video.py
python3 tests/browsers/test-video-tools.py AccelerationEvidence -v
```

## Where things are

| What | Where |
| --- | --- |
| Probe port and FFmpeg | `packages/android-firefox-video` (`stage.py`) |
| Launcher | `firefox_preferences`, `video_environment` in `src/native/acceleration.py` |
| Results and history | [X1S-FIREFOX-VIDEO.md](../X1S-FIREFOX-VIDEO.md) |
