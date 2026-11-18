# Note10+ GPU and hardware video parity investigation

Device: Galaxy Note10+ SM-N975U1, Snapdragon 855 / Adreno 640, Android 11.
Measurements started 2026-11-16. This is a dated device qualification record;
general driver capabilities belong to the [upstream sources](../../README.md#upstream-support-and-local-verification).
It does **not** establish complete feature parity.

The original Claude worker was `a25ae11189da88823`, “Note10+ SD855 capability
parity”, in session `bb1b5005-2d30-4906-b8de-c5b75fd81909`. It stopped at its
usage limit. Codex continued its uncommitted work in `/home/cs/wt-parity-note10`.
Local evidence is under `temp/parity-note10-20261116/`; its `resume/` directory
preserves the original changes and records continuation results.

## Changes qualified during continuation

Chrome selects the patched source-built glibc VA driver, already included in
`android-vaapi-glibc`, when a validated stack contains it. That driver uses
CPU-written dma-buf surfaces while Android MediaCodec executes the hardware
codec; Turnip still renders Chrome. The prebuilt glibc VA driver omitted cropping
for 16-aligned encoder surfaces. No per-phone setting is needed. Without the
source-built variant Adreno Chrome keeps encoding off. Explicit video overrides
still apply. Mali retains its existing driver and encoding policy.

Private launcher result: Chrome H.264 WebRTC, 288 pictures encoded and returned
by `OMX.qcom.video.encoder.avc`, correct 640x360 size and five sets of colour
checks including the last rows. Saved pictures were inspected. The prebuilt
driver control failed the size check. Original worker's HEVC, H.264 and fast
H.264 private fullscreen playback tests passed with the same driver.

Commit `75a4a98`; [CI 44025524103](https://github.com/cnshing/debian-livecd-termux/actions/runs/44025524103)
passed and produced livecd-desktop `0.2.0-25`. The CI package was installed
through the phone's local APT repository. The installed module's SHA256
matches the tested source (`d7320e5234b5190d35b53d348667b991913388c38dda842b83d4b2884ee3cc5c`),
and the profile link resolves to that APT-owned module.

Through the actual installed `google-chrome` command, H.264 WebRTC passed
with **286 hardware-encoded pictures**, correct 640x360 size, correct colours
and no GPU crash. H.264, HEVC and VP9 then passed the private fullscreen suite
with GPU and hardware decode required, two fullscreen cycles per codec.
`livecd validate` passed **30/30** after installation. Before the upgrade,
the same installed-launcher encoder check failed hardware acceptance with
zero hardware sessions, while its software picture was correct.

Default delivery is the existing installation chain: `install.sh` installs
`src/native/packages.txt` (including livecd-desktop), the default
`Browser+Chromium` overlay installs Chrome's `android-vaapi-glibc` and
`termux-va`, and the installed Chrome wrapper imports the checked launcher
module. The runtime selects the patched driver from the validated manifest;
there is no new per-phone opt-in. A final APT simulation for livecd-desktop
and android-vaapi-glibc reports zero changes. The existing published v0.12.0
release was deliberately not refreshed; it does not acquire this new
controller until rebuilt or upgraded.

Deployment note: APT aborted before changing packages on the initial
`--no-download` attempts (fdsan close-ownership error). Staging the verified
archive in Termux's actual cache, `/data/data/com.termux/cache/apt/archives`,
then using ordinary APT installation succeeded without network downloads.
The desktop was restored after each failed attempt and is running after
the successful upgrade. The earlier direct invocation of `validate.py`
lacked the session environment; the authoritative result is `livecd validate`.

## Android baseline measured on this phone

The extended [CodecInfo tool](../../tests/native/codec-info/CodecInfo.java) and
its [raw device output](../../tests/native/codec-info/note10-2026-11-16.jsonl)
record profiles, levels, colour formats, size/rate ranges, performance points,
bitrate modes, vendor/software flags and optional features. The running
MediaCodec registry is authoritative for availability on this installation;
the vendor XML also contains commented or unregistered codecs.

Android reports some Qualcomm components ending in `h263sw` or `mpeg4sw` as
hardware accelerated even though they are software implementations. The
vendor XML itself labels their capabilities `h263-sw`/`mpeg4-sw`; the phone
ships `libOmxSwVdec.so` and `libOmxSwVencMpeg4.so`. They are excluded from the
hardware target. The native decoder regression now rejects these components
as hardware evidence instead of treating every non-Google codec as hardware.

These are declarations, **not measured throughput**. Width and height maxima
are ranges, not proof that every combination is supported. 4K/8K rates below
are the registry's limits for 3840x2160 and 7680x4320, rounded down.

| Hardware component (`OMX.qcom.video.*`) | Profiles / level | Size range | 4K / 8K fps limit | Bitrate max |
| --- | --- | --- | --- | --- |
| `decoder.avc` | Baseline, Main, High, Constrained Baseline/High; level 6; no High10 | 96–8192 × 96–4320 | 120 / 30 | 220 Mb/s |
| `decoder.hevc` | Main, Main10, Main10 HDR10; high tier level 6 | 96–8192 × 96–4320 | 120 / 30 | 220 Mb/s |
| `decoder.vp9` | Profile 0, profile 2, profile 2 HDR; level 6.1 | 96–8192 × 96–4320 | 120 / 30 | 220 Mb/s |
| `decoder.vp8` | Main; version 3 | 96–4096 × 96–2304 | 32 / unavailable | 100 Mb/s |
| `encoder.avc` | Baseline, Main, High, Constrained Baseline/High; level 5.2 | 96–4096 × 96–2304 | 60 / unavailable | 160 Mb/s |
| `encoder.hevc` | Main and Main10 HDR10; high tier level 6; plain Main10 not separately listed | 96–4096 × 96–2304 | 60 / unavailable | 160 Mb/s |
| `encoder.vp8` | Main; version 0 | 96–4096 × 96–2304 | 32 / unavailable | 40 Mb/s |

Decode components list adaptive playback. None lists low-latency, tunnelled,
partial-frame or frame-parsing support in this dump. HEVC's encoder lists
CBR/VBR/CQ; AVC and VP8 list VBR only, even though the bridge's AVC CBR requests
work on this firmware. Inspect performance-point and achievable-rate fields
in the raw output rather than substituting these maxima for benchmarks.
No hardware AV1, VP9 encoder or MPEG-2 codec is registered. MPEG-4 and H.263
are vendor software, not hardware gaps. The separately present MPEG-2 vendor
XML is empty. Google/Android software codecs are also recorded in the dump.

Secure AVC/HEVC/VP9 decoders are registered separately (`*.secure`, up to
4096×2304, with 4K60 limits and 3 concurrent instances). They are DRM/protected
output paths, outside this task's non-secure video target. No HEVC HDR10+ or
VP9 HDR10+ profile was listed. HLG and a working HDR display path were not
qualified. Profile values are interpreted using Android's
[profile/level constants](https://developer.android.com/reference/android/media/MediaCodecInfo.CodecProfileLevel).
The [Qualcomm product brief](https://www.qualcomm.com/content/dam/qcomm-martech/dm-assets/documents/prod_brief_qcom_sd855.pdf)
describes broader platform HDR capabilities; it does not establish that the
desktop pipeline exposes them on this firmware.

## Decode routes

“VA” below means the installed bridge used by FFmpeg VA-API, GStreamer's `va`
elements and the three browsers. mpv uses FFmpeg's separate NDK MediaCodec
route by default. No new decode default was enabled during this continuation.

| Feature | FFmpeg VA / GStreamer VA | Chromium / Chrome / Firefox | FFmpeg MediaCodec / mpv | Status |
| --- | --- | --- | --- | --- |
| AVC 8-bit, HEVC Main, VP9 profile 0 | On | On; Chrome now uses the source-built VA driver | On | Baseline; private Chrome playback rechecked with the new driver |
| VP8 decode | Not advertised | Software | Hardware; 48/48 ordered pictures passed with `OMX.qcom.video.decoder.vp8` | VA needs a Gallium VP8 frontend, not a launcher flag |
| HEVC Main10 / VP9 profile 2 input | Not advertised | Software | Hardware decode passed 48/48 per codec, **output is 8-bit NV12** | These RGB checks do not qualify preserved 10-bit precision |
| Actual P010 output | Missing transport/surfaces | Missing through VA | NDK format probe succeeds; FFmpeg's tested route still outputs NV12 | [10-bit handoff](handoff/note10-codec-parity.md) |
| MPEG-4 Part 2 | Not advertised | Software | Qualcomm software decoder returned 48/48; hardware check correctly fails | Outside the hardware target |
| AV1 | Disabled for hardware; software available | Software | Software | No hardware on this phone |
| 4K/8K limits, sustained rate, HDR output | Not qualified | Not qualified | Not qualified here | Declared capabilities are not acceptance results |

The 10-bit probe is reproducible with
[`probe-bytebuffer.c`](../../tests/native/codec-info/probe-bytebuffer.c).
With YUV420Flexible requested, both hardware decoders return Qualcomm linear
Venus P010 (`0x7fa30c0a`): 96x96, stride **256 bytes**, slice height 96,
36864 bytes per output frame. The `--nv12` negative control returns format 21,
stride 96, 13824 bytes and exits 1. Explicitly requesting P010 on the older
probe had silently produced NV12; always inspect the negotiated format.
This small grey-frame probe proves a ByteBuffer route exists, not full pixel
precision, crop, HDR metadata, browser presentation or throughput.

## Encode routes

| Feature | FFmpeg VA / GStreamer VA | Chromium | Chrome | Firefox |
| --- | --- | --- | --- | --- |
| AVC hardware encode | Existing default | Existing WebRTC/WebCodecs default | **New WebRTC default** with the validated source-built driver | Experimental call/pixel tests pass; default remains off |
| HEVC Main encode | Existing default | Not offered by tested VA WebCodecs path | Not qualified | Not qualified |
| VP8 hardware encode | Missing bridge/protocol entry | Software | Software | Software |
| VP9 / AV1 hardware encode | Not offered by daemon | Software | Software | Software |
| Main10 / HDR10 HEVC encode | Bridge takes NV12 only | Not qualified | Not qualified | Not qualified |

Firefox `159.0-101` / android-firefox-video `9.0.2-6` passed H.264 WebRTC
(244 encoded / 243 decoded, 640x360) and WebCodecs (60/60, maximum channel
error 4, correct BT.601 metadata). Its five fixed/frame-rate cases passed
at 1.974–2.035 Mb/s for 2 Mb/s. **It failed the midstream bitrate decrease:**
the remaining 60 pictures averaged 1.151 Mb/s for a 500 kb/s request. The
daemon received 499995 b/s and reported no MediaCodec rejection. Therefore
the proposed default was not shipped; Mali's existing opt-in remains intact.
The earlier x1s reconfiguration fixes (`675ee1c`) were already included.
This test measures immediately after submission without aligning output
packet timestamps or allowing convergence, whereas the older daemon test
skips 15 pictures after a target change. The result does not establish an
ignored bitrate update; a longer timestamp-aligned trace is still needed.
See [Firefox handoff](handoff/encode-firefox.md).

Chromium's MediaRecorder did invoke Qualcomm's AVC encoder at 1280x720, but
the software-decoded output failed colour checks (saturation 0.83/lightness
0.54 instead of 0.70/0.45). Interpreting the samples as full-range BT.709
recovers the intended colour; this diagnoses missing/wrong colour signalling,
not an accepted workaround. Chrome's MediaRecorder control had correct colour
but ran **no hardware encoder session**. Neither is a hardware MediaRecorder
pass. Chrome's prebuilt WebCodecs native-pixmap crash remains unresolved.

FFmpeg advertises `vp8_mediacodec`, but a direct synthetic VP8 encode attempt
at 640x360 aborted in Android's CodecLooper with stack-protector failure
after configuring `OMX.qcom.video.encoder.vp8`; the recording was empty.
The advertised encoder is not a verified substitute for the missing VA path.

## GPU comparison on this installation

Stock `cmd gpu vkjson` reports Qualcomm Vulkan **1.1.128**, 59 device
extensions and protected memory. The installed desktop's **device** reports
Turnip Vulkan **1.3.354**, 169 extensions; its loader's instance version
1.4.368 is not the GPU's version. Both report a 16384 maximum 2D image
dimension. Stock SurfaceFlinger reports GLES 3.2; desktop Zink reports
OpenGL 4.6 and GLES 3.2 on Turnip. Live GNOME Shell was passively checked:
it maps `libvulkan_freedreno.so` and holds `/dev/kgsl-3d0`.

| Native capability / client | Desktop evidence / gap |
| --- | --- |
| Graphics + Vulkan compute | Turnip exposes graphics and compute; no new compute benchmark in this continuation |
| Android hardware buffers | `VK_ANDROID_external_memory_android_hardware_buffer` is stock-only in these dumps; desktop VA uses dma-bufs instead |
| Android timing/presentation | Stock-only `VK_GOOGLE_display_timing`, `VK_KHR_shared_presentable_image`; X11 presentation is a different path |
| Qualcomm render-pass extensions | Stock-only `VK_QCOM_render_pass_store_ops`, `VK_QCOM_render_pass_transform`; not supplied by launcher changes |
| Protected graphics | Stock protectedMemory true; Turnip false; outside the non-secure media target |
| Vulkan Video | Neither dump advertises `VK_KHR_video_*`; MediaCodec remains the video engine |
| OpenCL | Stock: vendor OpenCL 2.0, unreachable from Termux (namespace). Desktop: Termux's `clvk` (OpenCL 3.0, OpenCL C 1.2) on Turnip through `ocl-icd`, installed by `install.sh` only when `/dev/kgsl-3d0` exists. **Installed pass 2026-11-18** (APT clvk 0.0.20261102.231234, session environment): exact hash/SAXPY/local-memory reduction/matmul, wrong-reference control fails, FFmpeg `avgblur_opencl` 43.9 dB and `unsharp_opencl` 49.5 dB against the CPU filters (pictures inspected). Outside the desktop session (no `VK_ICD_FILENAMES`) clvk picks llvmpipe, which the test rejects. Rusticl not chosen: it pulls in clang (~190 MB installed) against clvk's 91 MB |
| WebGL / WebGPU | `tests/browsers/test-web-graphics.py`, installed launchers (livecd-desktop 0.2.0-31): WebGL 1/2 exact pictures (float targets, transform feedback) and compositor presentation pass on Turnip in Chromium 156, Chrome 157 and Firefox 159. **Firefox WebGPU is on by default on Adreno** and passes render, compute (matmul, 2^20 hash, workgroup reduction) and canvas presentation; with `LIVECD_FIREFOX_GPU=0` WebGPU is absent and WebGL is software (control). `livecd validate` 30/30. Chromium/Chrome WebGPU stay off: Dawn lists the Turnip Vulkan adapter as *Available* (chrome://gpu), but `requestAdapter` returns null by default and, with `--enable-unsafe-webgpu`, Chromium's adapter selection hands out the SwiftShader CPU adapter (power-preference flags do not change it), whose JIT segfaults in the GPU process (gdb stack entirely in `libvk_swiftshader.so`). Fix needs a Chromium adapter-selection patch (source-built Chromium only) |
| Vulkan video / protected memory | Unreachable with the current drivers: Turnip 26.2 has no `VK_KHR_video_*` on a6xx and the stock driver lists none either; protected memory needs the KGSL secure context that only the vendor driver uses, and Turnip reports `protectedMemory` false. MediaCodec remains the video engine |

Stock GLES exposes 99 extension names; desktop Zink 167. Stock-only names
include Qualcomm foveation/motion-estimation/tiled-rendering extensions,
`GL_EXT_YUV_target`, `GL_EXT_protected_textures`, and framebuffer-fetch
variants. These counts are API inventories, not a claim that a larger count
provides native feature parity. Raw lists are under the evidence directory's
`gpu/`. Use [Mesa's Turnip documentation](https://docs.mesa3d.org/drivers/freedreno.html)
for driver capabilities rather than treating this one comparison as a second
upstream support matrix. Termux's
[vendor OpenCL recipe](https://github.com/termux/termux-packages/blob/master/packages/opencl-vendor-driver/build.sh)
also records that Qualcomm's vendor driver lacks the ICD extension expected
by that route; copying a library alone does not qualify OpenCL.

## Remaining work and acceptance

Complete driver work is still required for VP8 and preserved 10-bit/HDR.
The [implementation handoff](handoff/note10-codec-parity.md) identifies the
frontend, protocol and buffer changes. Firefox rate control needs further
qualification; Chromium MediaRecorder colour metadata needs fixing and rerunning. High-resolution
throughput, OpenCL, WebGPU and stock-only graphics extensions remain gaps or
unqualified paths; no defaults were changed for those rows.

Shared production file changed: `src/native/acceleration.py`, plus the
livecd-desktop package revision. Mali uses the same source-built driver,
reorder safeguards and encoding policy as before; its host regressions pass.
The S20 was not accessed. No camera or Bluetooth test was run, no Android
settings/permissions changed, and no release was edited or published.
Temporary SSH access adopted from the paused worker was removed at completion:
its authorized key, dedicated listener and USB forward, plus the staged setup
script and public key. The desktop remains running. No test process started
by this continuation remains; the predecessor's private daemon PID 23856 was
left untouched, as was the desktop's shared video daemon. Evidence remains
under `~/parity`, `~/p` and the host evidence directory.

Reproduce the browser tests with synthetic input, their own display, daemon
socket and profile:

Reproduce a browser encoder test with synthetic input, its own display, daemon
socket and profile:

```sh
python tests/video-encode/test-browser-encode.py chrome --out ~/p/chrome-encode
```

Use a new short output path for every run. The test fails on wrong size,
colour, missing hardware sessions or GPU crash. Firefox experiments require
`--firefox-encode`; that switch does not change the installed default. Do not
run the hardware Chrome WebCodecs path repeatedly: its prebuilt binary's native
pixmap assertion remains unresolved ([details](handoff/encode-chrome.md)).

## Session lane results (2026-11-17)

Evidence: `temp/parity-note10-20261116/session/`.

**ION contiguous surfaces in the desktop session** (android-vaapi 14 / -glibc 6, commits
92a2416..11ddca4): see [DMA-HEAP-ION.md](DMA-HEAP-ION.md#the-desktop-session-bridge-scoped-ion-2026-11-17-note10).
Bridge-scoped, no session preload, so Turnip/PanVK allocation is unchanged by construction.
Debug-staged on the phone: 12/12 surfaces contiguous from ION, 48/48 frames bit-exact;
`LIVECD_DMA_HEAP_ION=0` control falls back. Installed-package verification is pending the
install queue.

**Chrome compositor stale frame.** Repetition harness: the installed `google-chrome` under
`tests/browsers/test-fullscreen.py` (VP9, one fullscreen cycle, frames 12 and 36 at the browser
and GNOME Shell layers), run back to back.

| Run set | Runs | Stale shell frame |
| --- | --- | --- |
| Baseline, android-vaapi 11/12 (0101 completion + 0106 late-frame drop installed) | 50 | 1 (frame 13 shown for 36, persistent across 4 captures) |
| Negative control `LIVECD_VA_DISABLE_COMPLETION=1` | 20 | 20 (every run, both frames) |
| Baseline with `DMD_VA_LOG=1` tracing | 60 | 0 (one harness ffmpeg error, not a stale frame) |

So the completion wait plus 0106 brings the failure from 100% to about 1-2%; the residual is not
fixed. The trace shows each picture's copy completes inside `vaEndPicture` (the later
`vaSyncSurface` waits 0.01 ms), so the residual stale picture is not an unfinished bridge copy:
the remaining candidates are consumer-side (Chrome not re-presenting the window after a paused
seek, or GPU reads without a cache invalidate). A software-decode control at the same scale is
still needed to separate those. Not on by default; nothing changed.

**4K/8K throughput** (installed android-vaapi 12, FFmpeg, frames kept on VA surfaces, 300-frame
clips decoded as fast as possible; all VA outputs bit-exact against software, NV12 framemd5):

| Clip | VA bridge | FFmpeg NDK MediaCodec | Registry limit |
| --- | --- | --- | --- |
| H.264 4K60 40 Mb/s | 56 fps wall (5.38 s incl. start) | 71 fps | 120 |
| HEVC 4K60 30 Mb/s | 69 fps | 85 fps | 120 |
| VP9 4K60 30 Mb/s | 83 fps | 83 fps | 120 |
| HEVC 8K30 60 Mb/s (60 frames) | 16 fps | 20 fps | 30 |
| H.264 4K60 VA encode (hwupload + h264_vaapi) | 10.8 fps | — | 60 |
| HEVC 4K60 VA encode | 11.6 fps | — | 60 |

4K30 decode sustains on every codec; 4K60 sustains for HEVC and VP9 and is marginal for H.264.
8K30 decode does **not** sustain (MediaCodec itself only reached 20 fps here), and 4K encode
through the bridge is far below real time (the CPU upload and NV12 copy into shared memory
dominate). Do not advertise 8K or 4K encode. A concurrent test from another lane was running
during the measurement, so these are lower bounds.
