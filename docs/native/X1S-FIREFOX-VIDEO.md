# Firefox hardware video on Mali (Galaxy S20, x1s)

State on 2026-11-12. Firefox on the S20 (Exynos 990, Mali-G77) decodes **VP9 and HEVC in
hardware** while rendering on Zink over PanVK. H.264 decoding stays in software, and encoding is
untested; the [handoff](#handoff-what-is-left) below covers those two.

## What works

Private display, fresh profile, `chart-vp9.webm`, with the CI-built packages staged privately
(run `race-pkg-vp9-1`):

| Check | Result |
| --- | --- |
| Renderer | WebRender on `zink Vulkan 1.3(Mali-G77 MC11 (MESA_PANVK))`; WebGL 1/2 readback correct |
| Decoder | `VA-API FFmpeg init successful`; 354 pictures in, 354 frames out of Android's VP9 decoder; no export failure, no software fallback |
| Pixels | numbered frames 12 and 36 correct at the browser and GNOME layers (captures opened and checked) |
| Stability | 569 WebGL frames beside the video, none wrong; Firefox alive at the end; live session untouched |

The same run before the fixes is the negative control: 0 VA-API frames
(`vaExportSurfaceHandle failed`), or a crash on the first imported frame.

HEVC, `chart-hevc.mp4`, same setup with android-vaapi 5 and `TERMUX_VA_HEVC_REORDER_PICS=0`
(run `race-hevc-r0b`):

| Check | Result |
| --- | --- |
| Decoder | `VA-API FFmpeg init successful`, `HEVC SWDEC HWDEC`; 369 pictures in, 369 frames out of `OMX.Exynos.hevc.dec`; no fallback |
| Pixels | numbered frames 12 and 36 correct at the browser and GNOME layers (captures opened and checked) |
| Stability | 302 further frames played beside WebGL; Firefox alive at the end; live session untouched |
| Control | same build without the variable (`race-hevc-control`): `6 units in, 0 frames out`, playback hangs |

Outside Firefox, FFmpeg through the same driver decodes three HEVC clips with every frame
identical to software decoding, with the variable at 0 and at 1: the fixture (48 frames), a 720p
x265 clip with open GOPs (CRA and RASL pictures, 150 frames) and a 1080p clip encoded with 8
B-frames and 5 references (150 frames). Without the variable FFmpeg hangs on the fixture.

## What it needs

| Piece | Where | Why |
| --- | --- | --- |
| `android-vaapi` ≥ revision 4 | `0102-own-gallium-driver-variable.patch` | The VA driver's private Mesa has only softpipe. It read the application's `GALLIUM_DRIVER`, and Firefox's is `zink`, so the driver failed to start inside Firefox. It now reads `TERMUX_VA_GALLIUM_DRIVER` |
| `android-vaapi` ≥ revision 5 (HEVC) | `0103-hevc-reorder-count.patch` | See [HEVC](#hevc-why-it-stalled) below. The bridge takes the reorder count it declares from `TERMUX_VA_HEVC_REORDER_PICS` |
| `mesa` ≥ 26.2.6-103 | `0023-zink-skip-missing-dmabuf-fence-semaphores.patch` | PanVK's kbase backend cannot create SYNC_FD semaphores. Zink's `submit_queue` read one per dma-buf plane from an empty array and crashed Firefox on its first imported frame |
| `android-firefox-video` ≥ 9.0.2-2 | `stage.py` | Firefox's graphics probe accepts Zink on PanVK with `/dev/mali0`, as it does Turnip with KGSL. Without a render device Firefox never runs its VA-API probe. The package depends on mesa -103 and android-vaapi 5 |
| Launcher | `src/native/acceleration.py` | On Mali: `MOZ_DRM_DEVICE=/dev/mali0`, Firefox keeps its own `GALLIUM_DRIVER`, and `TERMUX_VA_HEVC_REORDER_PICS=0` |

Frame export itself comes from the ION dma-buf surfaces of `tva_ion_winsys.h` (android-vaapi 3).
Firefox's GL is on PanVK only when the desktop renderer is Zink (`gpu_enabled`); on a software
desktop Firefox stays on software rendering and software video.

VirGL, the earlier Firefox GL route on this phone, cannot do this: Mesa's vtest winsys has no
`resource_from_handle`, so it cannot import a dma-buf at all.

## HEVC: why it stalled

VA-API does not carry `sps_max_num_reorder_pics`, so the bridge, which rebuilds the VPS and SPS
for MediaCodec, declares `min(DPB size - 1, 3)`. Exynos's decoder holds back exactly as many
pictures as the SPS declares. The fixture's real count is 2 and the bridge declared 3, so the
decoder released the first picture only after a fourth arrived. Firefox's FFmpeg submits three
(the real count plus one) and then waits for the first: both sides wait, the daemon logs
`6 units in, 0 frames out` (three parameter sets and three pictures), and Firefox does not fall
back. The earlier explanation, a first frame after about 18 pictures, was wrong.

With `TERMUX_VA_HEVC_REORDER_PICS=0` the decoder returns each picture as soon as it is decoded.
The order no longer matches display order, which does not matter: the bridge pairs each frame
with its input unit by index. The launcher sets it for Firefox on Mali only. Unset, the bridge
declares what it did before, because its source says Qualcomm's decoder stops returning frames
at 0.

The `vendor.rtc-ext-dec-low-latency.enable` MediaCodec key and turning `low-latency` off changed
nothing.

## How to test

`temp/gpu-x1s/firefox-virgl-race.py` (local, not in Git; copy on the phone in `~/gpu-x1s/`) runs
Firefox on a private Termux:X11 display with a private codec daemon and checks decoder logs,
numbered frames and isolation. `~/gpu-x1s/panvk-run.sh LABEL` wraps it:

```sh
FFAPP=$HOME/gpu-x1s/ffv1/application MESA=$HOME/gpu-x1s/mesa-103/lib \
  bash ~/gpu-x1s/panvk-run.sh LABEL            # VP9
CLIP=chart-hevc.mp4 ... bash ~/gpu-x1s/panvk-run.sh LABEL \
  RACE_VA_STACK=$HOME/gpu-x1s/vaapi-5 TERMUX_VA_HEVC_REORDER_PICS=0   # HEVC
```

`ffv1`, `mesa-103`, `vaapi-patched4` and `vaapi-5` are private extractions of the CI packages;
nothing is installed on the phone yet. In such an extraction, point the links in
`lib/va-client` at `$PREFIX/lib`, or Firefox's probe reports `libva-drm.so.2 is missing` and
every codec silently decodes in software. `~/gpu-x1s/hevc-latency.py OUTDIR DAEMON CLIP` (local
copy `temp/gpu-x1s/hevc-latency.py`) decodes a clip with FFmpeg through the driver, without a
browser, and compares every frame with software decoding. Once the packages are installed, the maintained
`tests/browsers/test-acceleration.py firefox` should exercise the installed launcher; it has not
been run on Mali. It accepts the selected GPU's matching library and device pair (PanVK with Mali,
or Turnip with KGSL) instead of requiring Turnip on every phone, and its result keeps the last
playback state and the VA-API init, frame and software-codec evidence even when playback fails.
It checks browser pixels; the private harness above still supplies the compositor captures and
the concurrent WebGL workload. Host checks:

```sh
python3 tests/packaging/test-firefox-video.py
python3 tests/native/test-graphics.py
python3 tests/browsers/test-video-tools.py AccelerationEvidence -v
```

## Handoff: what is left

### 1. HEVC: what is left

Firefox on Mali now decodes HEVC in hardware (above). Not done:

- **The launcher path is untested on the phone.** The harness set the variable by hand; the
  launcher line and its host test (`tests/packaging/test-firefox-video.py`) are new. The final CI
  driver (run 43362735995) is byte-identical to the one tested.
- **Chromium on Mali** has the same failure and still decodes HEVC in software. Its end-of-picture
  wait needs each picture back before the next goes in, which a count of 0 should give. Set the
  variable for Chromium in `acceleration.py` and run its HEVC case.
- **Other phones.** On Adreno nothing changes. A count of 1 is never more than a reordering
  stream's real count and also gave identical frames here, so it may be a better default than 3
  for every decoder; that needs a run on the Note10+ first.
- **End of stream with the old value.** With 3 declared, the decoder keeps the last three
  pictures, and the bridge's terminal drain only fires for the newest unit, so a client waiting
  on an older one hangs (FFmpeg did). Irrelevant at 0; still there on other phones if a stream's
  real count is below what the bridge declares.
- Seeking and a long soak have not been run for HEVC.

### 2. H.264 decoding is off everywhere

- Not specific to Mali. `disabled_va_codecs` defaults to `['h264', 'av1']`, so every browser on
  every phone decodes H.264 in software; Firefox here reports `H264 SWDEC HWENC`.
- **Why it is off:** VA-API does not carry `num_ref_idx_l0_default_active_minus1`, so the bridge
  rebuilds the PPS with a guess (`min(maxrefs,3)-1`). When the guess is wrong and
  `weighted_pred_flag=1`, MediaCodec misparses `pred_weight_table`, drops frames, and
  `vaSyncSurface` never returns. x264 `-preset fast` streams trigger it; the repository fixtures
  (preset medium) do not, so a passing fixture proves nothing.
- **To fix:** pass the original PPS (or the real default reference counts, recoverable from the
  slice headers' `num_ref_idx_active_override_flag` and counts) to MediaCodec instead of the
  rebuilt one, add a `-preset fast` fixture with weighted prediction as the failing control, and
  only then take `h264` out of the default. The bridge also guesses H.264's
  `max_num_reorder_frames` (2 when there are more than two references), so on Mali expect the
  stall of item 1 and give H.264 the same kind of variable.

### 3. Encoding in Firefox is untested

- **State:** with the probe fixed, Firefox reports `HARDWARE_VIDEO_ENCODING available` and
  `HWENC` for H.264, VP9 and HEVC on the S20 (the daemon lists `OMX.Exynos.AVC/HEVC/VP9.Encoder`).
  That is the probe's profile list, not an encode. On Adreno the feature was blocklisted
  (`VIDEO_ENCODING_MISSING`) before; recheck there with the new probe.
- **To test:** a page using WebCodecs `VideoEncoder` with
  `hardwareAcceleration: 'prefer-hardware'` for `avc1.42001f`, `vp09.00.10.08` and `hvc1`, plus
  `MediaRecorder` and a WebRTC loopback; `MOZ_LOG=FFmpegVideo:5,PlatformEncoderModule:5`. Accept
  only if the daemon log shows an encoder session with frames in and out and the output decodes
  to the right pictures in software. [ENCODING.md](ENCODING.md) has the bridge's own encode checks
  and the rate-control and packed-header facts Chromium tripped over.
- **Likely obstacles:** Firefox's VA-API encoder wants specific rate-control modes and packed
  headers from the driver's encode config; what Termux:VA reports has not been compared with what
  Firefox asks for. Input frames reach the encoder as CPU or dma-buf surfaces; the upload path on
  the software backend is unexercised.

### 4. Smaller items

- Nothing here is installed on the S20; install the three packages and rerun through the real
  launcher (`livecd-native` Firefox entry), not the harness.
- Another PanVK port for kbase, [JimVulkan/mali-panvk](https://github.com/JimVulkan/mali-panvk)
  (Mesa 27, lists the S20's G77 as tested), advertises `VK_KHR_external_semaphore_fd` and dma-buf
  import and imports Android hardware buffers. Not tried here. If it creates SYNC_FD semaphores,
  the Zink patch above is unnecessary with it; hardware-buffer import could let decoded frames
  reach the GPU without the software copy.
- Adreno regression: the Note10+ uses the same probe patch and the same VA variable. Rerun
  `tests/browsers/test-acceleration.py firefox` there after installing.
- Firefox gets PanVK only on a Zink desktop. Chromium gets it whatever the desktop uses; doing the
  same for Firefox is a small change in `gpu_enabled`, untested.
- `TERMUX_VA_SYNC_END_PICTURE` is set for Chromium only. Firefox passed the frame checks without
  it; a long soak with seeking has not been run.
