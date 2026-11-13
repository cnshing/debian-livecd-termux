# Firefox hardware video on Mali (Galaxy S20, x1s)

State on 2026-11-12. Firefox on the S20 (Exynos 990, Mali-G77) decodes **VP9 in hardware**
while rendering on Zink over PanVK. HEVC and H.264 decoding stay in software, and encoding is
untested; the [handoff](#handoff-what-is-left) below covers those three.

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

## What it needs

| Piece | Where | Why |
| --- | --- | --- |
| `android-vaapi` ≥ revision 4 | `0102-own-gallium-driver-variable.patch` | The VA driver's private Mesa has only softpipe. It read the application's `GALLIUM_DRIVER`, and Firefox's is `zink`, so the driver failed to start inside Firefox. It now reads `TERMUX_VA_GALLIUM_DRIVER` |
| `mesa` ≥ 26.2.6-103 | `0023-zink-skip-missing-dmabuf-fence-semaphores.patch` | PanVK's kbase backend cannot create SYNC_FD semaphores. Zink's `submit_queue` read one per dma-buf plane from an empty array and crashed Firefox on its first imported frame |
| `android-firefox-video` ≥ 9.0.2-1 | `stage.py` | Firefox's graphics probe accepts Zink on PanVK with `/dev/mali0`, as it does Turnip with KGSL. Without a render device Firefox never runs its VA-API probe. The package depends on the two versions above |
| Launcher | `src/native/acceleration.py` | On Mali: `MOZ_DRM_DEVICE=/dev/mali0`, Firefox keeps its own `GALLIUM_DRIVER`, and `TERMUX_VA_DISABLE_HEVC=1` |

Frame export itself comes from the ION dma-buf surfaces of `tva_ion_winsys.h` (android-vaapi 3).
Firefox's GL is on PanVK only when the desktop renderer is Zink (`gpu_enabled`); on a software
desktop Firefox stays on software rendering and software video.

VirGL, the earlier Firefox GL route on this phone, cannot do this: Mesa's vtest winsys has no
`resource_from_handle`, so it cannot import a dma-buf at all.

## How to test

`temp/gpu-x1s/firefox-virgl-race.py` (local, not in Git; copy on the phone in `~/gpu-x1s/`) runs
Firefox on a private Termux:X11 display with a private codec daemon and checks decoder logs,
numbered frames and isolation. `~/gpu-x1s/panvk-run.sh LABEL` wraps it:

```sh
FFAPP=$HOME/gpu-x1s/ffv1/application MESA=$HOME/gpu-x1s/mesa-103/lib \
  bash ~/gpu-x1s/panvk-run.sh LABEL            # VP9
CLIP=chart-hevc.mp4 ... bash ~/gpu-x1s/panvk-run.sh LABEL TERMUX_VA_DISABLE_HEVC=1
```

`ffv1`, `mesa-103` and `vaapi-patched4` are private extractions of the CI packages; nothing is
installed on the phone yet. Once the packages are installed, the maintained
`tests/browsers/test-acceleration.py firefox` should replace this harness; it has not been run on
Mali. Host checks: `python3 tests/packaging/test-firefox-video.py`.

## Handoff: what is left

### 1. HEVC decoding stalls

- **Symptom** (`race-video-hevc-panvk1`): Firefox starts the VA-API HEVC decoder, the daemon logs
  `handshake ok: decoder video/hevc`, then `failed to send format descriptor` and
  `session end: 6 units in, 0 frames out`. Playback hangs; Firefox does not fall back.
- **Cause, as far as known:** Exynos's HEVC decoder returns its first frame only after about 18
  pictures, and the bridge waits a bounded time per picture
  ([X1S-BROWSER-VERIFICATION.md](X1S-BROWSER-VERIFICATION.md), Chromium has the same failure).
  Not confirmed inside the bridge for Firefox's call sequence.
- **Current handling:** the launcher sets `TERMUX_VA_DISABLE_HEVC=1` for Firefox on Mali. Verified
  (`race-pkg-hevc-off1`): Firefox then lists HEVC as software decode only, plays the clip in
  software with correct frames 12/36, and never contacts the daemon. HEVC encode stays listed.
- **To fix:** make the bridge (`tva_bridge.c` in Termux:VA, patched by
  `packages/android-vaapi/0101-complete-implicit-sync-decodes.patch`) tolerate a decoder that
  holds several pictures before its first output: queue input without waiting for a matching
  output, and block only in `vaSyncSurface`/export for the surface actually requested. mpv decodes
  HEVC on this phone through MediaCodec directly, so the decoder itself is fine. Then remove the
  `TERMUX_VA_DISABLE_HEVC` line and its test, and rerun the HEVC clip expecting VA-API frames.

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
  only then take `h264` out of the default. On Mali, check the Exynos decoder's first-frame
  latency too (item 1).

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
- Adreno regression: the Note10+ uses the same probe patch and the same VA variable. Rerun
  `tests/browsers/test-acceleration.py firefox` there after installing.
- Firefox gets PanVK only on a Zink desktop. Chromium gets it whatever the desktop uses; doing the
  same for Firefox is a small change in `gpu_enabled`, untested.
- `TERMUX_VA_SYNC_END_PICTURE` is set for Chromium only. Firefox passed the frame checks without
  it; a long soak with seeking has not been run.
