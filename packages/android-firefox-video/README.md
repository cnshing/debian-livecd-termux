# Firefox hardware video on Android

This package builds Mozilla's pinned upstream graphics/VA probe with the existing
KGSL and Mali adaptation and FFmpeg 9.0.2's VA-API decoder libraries. The Browser overlay
installs it with `android-vaapi`; no home-directory build is required.

`$PREFIX/lib/android-firefox-video/application` holds the patched `gfxtest` and a
copy of Firefox's small executable loader. Other Firefox assets are symlinks to
the installed package. The copy makes Firefox locate the patched probe through
its executable directory. Private GBM/DRM aliases satisfy the probe's desktop
library names. `ffmpeg/lib` contains the versioned decoder libraries Firefox
dlopens, with VA-API enabled. These libraries do not replace the system FFmpeg.

The probe adaptation only treats Zink as accelerated on the GPU the launcher
names in `MOZ_DRM_DEVICE`, after opening it: Turnip Adreno with `/dev/kgsl-3d0`, or
PanVK Mali with `/dev/mali0` ([state and limits](../../docs/native/X1S-FIREFOX-VIDEO.md)). The upstream VA probe still queries
the driver's actual capabilities. A manifest records hashes of the Firefox loader
and application.ini present in the builder. The launcher uses the package only
when both match the installed Firefox; otherwise it reports the mismatch and
starts the current Firefox with software decoding. Rebuild this recipe and bump
its revision when Termux updates or rebuilds Firefox.

Sources and patches match the previously validated development builders under
`prebuilt/native-video/`. The probe's four upstream files are hash-pinned by
`probe.lock.json`. `stage.py` applies the narrow probe change and stages the guarded
runtime. The standard FFmpeg configure and Android tempfile patches are included.

Host selection/fallback checks: `python3 tests/packaging/test-firefox-video.py`.
Artifact validation: `python3 tests/packaging/check-browser-video-artifacts.py OUTPUT`.
Device qualification uses the private-display Firefox runner in
`tests/browsers/test-acceleration.py`, including decoder logs, GPU evidence and
numbered-frame pixel checks.

Revision 3 also builds `h264_vaapi`, `hevc_vaapi`, and `vp9_vaapi`. Firefox's GTK
encoder submits I420 frames without creating a VA frame pool. The private
`0100-cpu-input-vaapi-encoders.patch` creates that pool, converts I420 to NV12,
and uploads each frame before the usual VA encoder submission. It preserves
timestamps, key-frame requests and colour properties; existing VA-frame clients
keep their original path. The CPU-input path uses 8-bit frames and no B frames.

This is awaiting device acceptance. The package records its CPU-input encoder
capability in the runtime manifest, but does not change Firefox's remote platform
encoder preference. Enable that preference only in private acceptance profiles
until daemon frame counts, software decoding and pixel checks pass. A `HWENC`
graphics-probe listing alone does not prove that Firefox can encode.

Revision 4 fixes an empty-encoder drain crash in FFmpeg's shared hardware encoder
base. Firefox recreates the encoder after a drain, then drains that fresh encoder
to confirm there is no more output. Timestamp adjustment must skip the missing
last picture. It also requires android-vaapi revision 8, whose DRM shim resolves
libdrm loaded with local visibility by Firefox. Neither change enables Firefox's
remote platform encoder preference.

On the phone, `tests/video-encode/test-firefox-ffmpeg.py --library-dir PATH` checks
local library loading and an empty drain for all three encoders. Use the session
VA environment and a private daemon. Browser acceptance must additionally check
flush, frame count, and software-decoded pixels.
