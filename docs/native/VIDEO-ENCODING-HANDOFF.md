# Handoff: hardware video encoding

State on 2026-11-13, for whoever takes encoding next. It covers both phones: the Note10+
(Snapdragon 855, Adreno 640, Android 11), where native encoding was built, and the Galaxy S20
(`x1s`, Exynos 990, Mali-G77, Android 13), where the browsers were tested. Decoding is not
covered here; see [MALI-GPU-STATUS.md](MALI-GPU-STATUS.md).

Read [ENCODING.md](ENCODING.md) for the design and the Adreno results, and
[X1S-BROWSER-VERIFICATION.md](X1S-BROWSER-VERIFICATION.md) for the browser runs. This page says
what works, what is blocked and by what, and what to do next. Paths under `temp/` are local
files that Git ignores.

## Acceptance in progress (2026-11-13)

The Linux/Bionic WebCodecs adapter now has a shared-memory input patch in
`packages/chromium/0100-termux-webcodecs-shmem.patch` (Chromium revision 2).
It selects both `kShmem` and CPU frame preparation; its Chromium regression test
covers ordinary CPU and mappable shared-image frames. The patch applies to the
prepared source, but that C++ regression test has not been compiled or run.

The patched browser is building in [Packages CI run 43421748237](https://github.com/cnshing/debian-livecd-termux/actions/runs/43421748237)
on the single CI branch `fix/chromium-webcodecs-shmem`. The S20 still has revision 1.
A fresh isolated baseline on its installed stack passed H.264 (283 browser frames,
285 daemon packets) and VP9 (280 browser frames, 282 daemon packets), with correct
received colours and no GPU crash. The daemon names Exynos hardware encoders for
both sessions. This baseline does not accept the WebCodecs fix.

Firefox WebCodecs was also probed through its installed launcher and a private
profile/display. With `hardwareAcceleration: "prefer-hardware"` and constant
bitrate, `isConfigSupported` returned false for `avc1.42001f`, `vp09.00.10.08`,
and `hvc1.1.6.L93.B0`. No encoder session was opened. The `HWENC` profile listing
therefore still does not establish an accepted Firefox encode.

Next: stage the CI binary privately and run WebCodecs with constant bitrate and
software decode/pixel checks, followed by the H.264/VP9 WebRTC loopback. Stop the
owned browser at the first GPU fatal error. Enable encoding by default only after
acceptance; prebuilt Chrome does not carry this patch. Local evidence and probe
copies are in `temp/gpu-x1s/encoding-acceptance-20261113/`.

## Other acceptance results (2026-11-13)

The private `android-vaapi` revision 7 build from [CI 43426043093](https://github.com/cnshing/debian-livecd-termux/actions/runs/43426043093)
passes native discovery on the S20: an emulated `/dev/dri/renderD128`, libdrm's
platform-bus identity, VA profiles, GLX and surfaceless EGL, and ordinary shell/Python
file operations. This also works when Android has no `/dev/dri` directory.
The driver selects CPU-backed surfaces automatically on Mali; encoding still uses
Exynos MediaCodec hardware. The compiler smoke check was skipped because the phone
has no compiler. Alternating installed revision 5 and private revision 7 preload
benchmarks measured about 21 microseconds per file-operation round for both.

Revision 7 also passes **46/46 FFmpeg checks**: H.264 profiles and HEVC, decoded
pixels, uncropped dimensions, key frames, MP4 seeking, VA post-processing/transcode,
bitrate, and deliberately corrupted negative controls. The measured 1 and 6 Mb/s
streams are 0.96 and 5.78 Mb/s. Post-processing is slow: the 120-frame scale/transcode
took 72 seconds. These packages are staged privately, not installed into the desktop.

Serein's GStreamer camera pipeline on revision 6 produces 60/60 accepted IDR access
units with parameter sets and correct Constrained Baseline. At 8 Mb/s its decoded
pixels exceed 47 dB PSNR. **Its 600 kb/s all-intra target fails**, producing 2.556 Mb/s.
The 720p VA-memory screen-share pipeline processes 51 frames in 118 seconds and
hits the 120-second timeout. Do not claim real-time screen sharing or add this
pipeline to defaults yet.

Firefox's installed private FFmpeg was built with encoders disabled. Merely loading
a full VAAPI FFmpeg still fails: Firefox submits I420 without a hardware frames
context, while these encoders normally require VA surfaces. Revision 3 adds private
VAAPI encoders and an I420-to-NV12 upload adapter; it is building in
[CI 43427375309](https://github.com/cnshing/debian-livecd-termux/actions/runs/43427375309)
on the same CI branch. It still needs phone acceptance with a private
`media.use-remote-encoder.video.platform=true` preference. No Firefox preference
has changed by default. Firefox's installed WebRTC VP9 software loopback passed
199 frames with correct colours; H.264 connected but produced no frames. Its VP8
MediaRecorder output decoded in software to all four expected colour sections
(maximum channel error 2), without a daemon encoder session. Browser paused-video
seek/readback stayed on the first picture, so that readback alone is not an encode oracle.

A fresh prebuilt Chrome loopback still has zero ICE candidates and zero frames.
The existing Bionilux `getifaddrs` fallback is bypassed by Chromium's direct
`AddressTrackerLinux` netlink enumeration. Termux Chromium's pinned
`1013-chromium-net-address-tracker.patch` handles denied multicast subscription and
link enumeration; prebuilt Chrome lacks that adaptation. No Chrome fix is accepted.

### Exynos kernel lead

The supplied [d2s MFC source](https://github.com/ianmacd/d2s/blob/d1d4fb4aa21d6f4c9b9f36caf15bc1a3c21d4e39/drivers/media/platform/exynos/mfc/mfc_enc_param.c#L217)
separates frame/macroblock rate control, bitrate, frame rate, and CBR mode. A reaction
coefficient at most 5 chooses intra-limited CBR; 6–10 chooses fixed CBR; larger values
choose VBR. The intra-size ratio applies only to the first mode. This is a lead for
the low-rate all-intra overshoot, not proof of its cause. The repository targets
Exynos 9820-family configs; the attached x1s reports `universal990` and kernel
`4.19.87-27102101`. Establish the installed OMX-to-V4L2 mapping before changing controls.
The daemon currently requests standard MediaCodec CBR. The kernel control values
are not MediaFormat key names and cannot simply be passed through it.

### LineageOS x1s source trace

The [x1s dependencies](https://github.com/LineageOS/android_device_samsung_x1s/blob/lineage-23.2/lineage.dependencies)
lead to `universal9830-common`, whose [media package list](https://github.com/LineageOS/android_device_samsung_universal9830-common/blob/96d43e19d657df7d8c8732973150b0b722df989c/device-common.mk#L187)
builds Exynos OMX AVC/HEVC/VP9 encoders and decoders plus `libstagefrighthw`.
On the attached stock phone, the AVC, HEVC and VP9 encoder XML elements are identical
to this LineageOS configuration. This confirms the component declarations, not
binary equivalence or acceptance of every vendor extension.

The path is Android MediaCodec/Stagefright → Exynos OMX → `ExynosVideoEncoder.c`
→ `Codec_OSAL_SetControls` in `ExynosVideo_OSAL.c` → V4L2 → MFC firmware.
[BoardConfig9830.mk](https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_config/blob/3626ce714e847cae429883a612d4ec9de79389e7/BoardConfig9830.mk)
enables DMA-buf and non-cached graphic buffers, HEVC/VP9 encoding and WFD codecs,
with `BOARD_USE_CSC_HW=false`. Native Android buffer sharing relies on these ROM
services; it does not provide Chromium's Linux native-pixmap allocator in Termux.

In [H.264 encoder setup](https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_openmax/blob/15ab30812af9fe39fff2ae3cd867d7e954c73881/openmax/component/video/enc/h264/Exynos_OMX_H264enc.c#L582),
standard CBR sets `CBRPeriodRf=10`, video-call CBR sets 5 and fixed slices, and
skip-frame CBR additionally permits dropping frames. The OSAL passes this coefficient
to `V4L2_CID_MPEG_MFC51_VIDEO_RC_REACTION_COEFF`. The
[actual universal9830 kernel](https://github.com/LineageOS/android_kernel_samsung_universal9830/blob/0d6cd86ea14b8ff28f9099a4c122cd7d96d71434/drivers/media/platform/exynos/mfc/mfc_enc_param.c#L363)
has the same 5/10 mode thresholds as the earlier d2s lead.

`openmax.mk` enables `USE_SKYPE_HD`; H.264 registers `rtc-ext-enc-bitrate-mode`.
Its [vendor-extension adapter](https://github.com/LineageOS/android_hardware_samsung_slsi-linaro_openmax/blob/15ab30812af9fe39fff2ae3cd867d7e954c73881/openmax/osal/Exynos_OSAL_Android.cpp#L4891)
accepts integer fields `value` (OMX control-rate enum) and `bitrate` (target bps).
The candidate MediaFormat names are therefore
`vendor.rtc-ext-enc-bitrate-mode.value` and
`vendor.rtc-ext-enc-bitrate-mode.bitrate`; enumerate/verify support on the installed
codec before using them. Do not substitute a MediaCodec bitrate-mode enum for an
OMX enum or allow frame dropping in Serein's one-output-per-input test.

Its separate `rtc-ext-enc-low-latency.enable` extension is **not** equivalent to the
standard `low-latency` key: H.264 setup disables rate control and enables per-frame
QP when this extension is enabled. The decoder's low-latency path instead sets
output display delay to zero. Neither is a safe blanket encoder fix.

The supplied [RTMP ingest notes](https://github.com/dimadesu/android-rtmp-ingest)
use direct FFmpeg MediaCodec with CBR and a named Qualcomm HEVC encoder on an S20 FE.
They also report unstable HEVC playback. They offer a useful direct-MediaCodec
comparison, but do not validate Exynos, the Linux VA upload path, or browser defaults.

Evidence: `temp/gpu-x1s/encoding-acceptance-20261113/`, including
`native-discovery7-run.txt`, `native-ffmpeg7-run.txt`, and `exynos-source/`.
The phone outputs are `~/gpu-x1s/en-discover7` and `~/gpu-x1s/en-ffmpeg7`.

## How encoding reaches the hardware

Every client goes the same way; only the first hop differs.

```text
client's own VA-API code (FFmpeg, GStreamer va, Chromium, Firefox)
  → libva → termuxva_drv_video.so        packages/android-vaapi (Bionic), android-vaapi-glibc (Chrome)
  → Unix socket: one NV12 picture in, one access unit out
  → termux-va daemon                      packages/termux-va
  → MediaCodec hardware encoder           OMX.qcom.* on the Note10+, OMX.Exynos.* on the S20
```

The daemon lists its hardware encoders in `<socket>.encoders` and refuses Android's software
ones. On the S20 that file reads `video/avc OMX.Exynos.AVC.Encoder`,
`video/hevc OMX.Exynos.HEVC.Encoder`, `video/x-vnd.on2.vp9 OMX.Exynos.VP9.Encoder`. The Note10+
has AVC and HEVC only.

## State

| Client | Note10+ (Adreno) | S20 (Mali) |
| --- | --- | --- |
| The daemon's own protocol test | passes: key frames, pixels, bitrate | 28 of 30 pass. The 2 failures are an extra, unrequested IDR in H.264 Baseline |
| FFmpeg `h264_vaapi`, `hevc_vaapi` | pass, including the live camera at 720p30 in real time | pass with a privately extracted FFmpeg, after adding BT.709 metadata to the stream (below). The S20 has Termux's stock FFmpeg installed, which has no VA-API |
| GStreamer `vah264enc`, `vah265enc`; Serein | pass in the test prefix | private camera IDRs/pixels pass; low bitrate and screen-share speed fail (above) |
| Programs finding the encoder with no settings | yes: the session preload presents KGSL as `/dev/dri/renderD128` | private revision 7 passes; installed revision 5 still needs explicit setup |
| Chromium, WebRTC | not run | **works behind a flag**: H.264 and VP9 loopback, hardware encoder and decoder, about 284 frames each, received colours exact |
| Chromium, WebCodecs `VideoEncoder` | not run | **crashes the GPU process** (Chromium CHECK) |
| Google Chrome, WebRTC | not run | cannot connect: no network interfaces under Bionilux |
| Google Chrome, WebCodecs | not run | same crash as Chromium |
| Firefox | reported blocklisted (`VIDEO_ENCODING_MISSING`) before the probe fix; not rechecked | installed hardware encode fails; VP9 WebRTC software passes; private encoder fix building |
| MediaRecorder, any browser | not run | Firefox VP8 software output passes; hardware encode not accepted |

**Browser hardware encoding is off by default everywhere.** No launcher passes
`AcceleratedVideoEncoder`. Native encoding (`native_encode` in
`~/.config/livecd-native/acceleration.json`) is on by default wherever `android-vaapi` is
installed.

## The blockers, with their causes

### 1. WebCodecs aborts Chromium's GPU process

- **What happens:** with `--enable-features=AcceleratedVideoEncoder` and a constant-bitrate
  request, the encoder reaches `kEncoding`, creates one input surface, and the GPU process
  dies with SIGTRAP. Chromium restarts it three times and then turns GPU acceleration off for
  the session. Same in Chromium and Chrome, with `android-vaapi` 2 and 3.
- **Cause, from Chromium's source:** on Linux `VideoEncodeAcceleratorAdapter` always asks for
  `StorageType::kGpuMemoryBuffer` (`media/video/video_encode_accelerator_adapter.cc`, under
  `#if IS_LINUX`, no switch). The GPU process then runs `CreateGpuMemoryBufferHandle()`, which
  does `CHECK_EQ(handle.type, gfx::NATIVE_PIXMAP)`
  (`media/gpu/chromeos/platform_video_frame_utils.cc`). Here GPU memory buffers are shared
  memory, because there is no GBM or dma-buf allocator. This reading fits the crash
  (minidump `temp/gpu-x1s/panvk-runs/54-gpu-crash.dmp`, pc `chrome+0x84fba78`) but the dump has
  not been symbolised against it.
- **Also needed:** `bitrateMode: "constant"`. Chromium refuses VBR on VA-API outside ChromeOS,
  and WebCodecs defaults to variable.
- **Fix, in `packages/chromium`:** either make the adapter use `kShmem` when the platform has
  no native pixmaps, or make `CreateGpuMemoryBufferHandle()` return a failure instead of
  aborting, so the page gets a software encoder. Chromium's build takes most of a six-hour CI
  job, so get the patch right against the source first. Chrome is prebuilt and cannot take it.

### 2. WebRTC works, but enabling it enables the crash

- WebRTC sends ordinary memory (`kShmem`, I420) unless `--video-capture-use-gpu-memory-buffer`
  is passed (`rtc_video_encoder.cc`, `IsZeroCopyEnabled`), and the driver uploads it with
  `vaDeriveImage`/`vaPutImage`. That is the path that works. **Never add that switch.**
- The same feature flag turns on blocker 1 for any page that uses WebCodecs with
  `prefer-hardware`. So the flag cannot go into `src/native/acceleration.py` for Chromium
  until blocker 1 is patched. For Chrome it is the user's decision whether WebRTC encoding is
  worth that crash; nobody has made it.
- The Exynos encoders reject MediaCodec's `low-latency` key (`configure failed with
  low-latency: -10000`); the daemon retries without it. Latency in a real call has not been
  measured.

### 3. Chrome has no network for WebRTC

- 0 ICE candidates, connection state `new`, log line
  `Could not bind NETLINK socket: Permission denied`. Chrome cannot list network interfaces
  under Bionilux. This is not a video problem, and it probably breaks every Chrome WebRTC call
  today, hardware or not.
- Look at how Chrome enumerates interfaces (netlink, then `getifaddrs`) against what Bionilux
  forwards: `overlays/Browser+Chromium/browsers/bionilux-0.5.0-browser.patch` and
  `packages/bionilux`. The Bionic Chromium on the same phone does gather candidates, so
  compare what the two do; why the bind is denied has not been established.

### 4. Native discovery on Mali: accepted privately, pending deployment

Revision 7 presents `/dev/mali0` as the VA render node, including its directory
when `/dev/dri` is absent, and selects the CPU surface backend automatically.
Discovery and 46 FFmpeg checks pass (details above). The installed revision 5 still
has the KGSL-only behavior. Retain the ordinary-process and GL/EGL checks when
changing this preload, which is loaded into every desktop process.

### 5. Colour metadata is missing from encoded streams

- On the S20, `h264_vaapi` and `hevc_vaapi` output failed the colour-patch check until BT.709
  primaries, transfer and matrix were added with `h264_metadata`/`hevc_metadata` (commands in
  [X1S-GPU-VERIFICATION.md](X1S-GPU-VERIFICATION.md)). After that: 42 to 48 dB, maximum channel
  error 1.
- Nothing adds that metadata automatically. Either the daemon should set the MediaCodec colour
  keys from what the client's VA sequence parameters carry, or the bridge should write the VUI.
  Not checked on the Note10+, whose tests compared decoded pixels and passed.

### 6. Smaller ones

- **Extra IDR in H.264 Baseline on Exynos** (the 2 daemon-suite failures). A client that
  counts key frames, as Serein's check does, would reject the stream. Evidence on the phone:
  `~/gpu-x1s/encode-daemon/`, host log `temp/gpu-x1s/encode-daemon-run.txt`.
- **`packages/termux-va/0001-encoder-for-snapdragon-omx.patch`** is named for the Snapdragon
  but is what makes Exynos work too. Rename it when it is next touched.
- **One picture at a time.** The driver waits for each packet: 720p30 fits, 1080p30 is at the
  edge on the Note10+ (22 to 35 ms per picture). Not measured on the S20.
- **`gst-plugins-va`** is a recipe but no overlay installs it, so Serein's encoder has nothing
  to call on a fresh install. **OBS** has no recipe (needs libpci and Termux's patch 0007
  dropped).

## What to do next, in order

1. **Patch Chromium for blocker 1**, then add `AcceleratedVideoEncoder` to Chromium's features
   on Mali in `command_line()` of `src/native/acceleration.py`, with a host test beside
   `test_glibc_mali_driver_precedes_the_prebuilt_mesa` in
   `tests/packaging/test-mali-acceleration.py` (that test currently asserts the flag is
   absent). Accept only when the WebCodecs probe either encodes or falls back without a GPU
   process crash, and the WebRTC loopback still passes.
2. **Run Firefox.** It needs no flag: a page with WebCodecs `VideoEncoder`
   (`hardwareAcceleration: 'prefer-hardware'`, `avc1.42001f`, `vp09.00.10.08`, `hvc1`),
   `MediaRecorder`, and a WebRTC loopback, with
   `MOZ_LOG=FFmpegVideo:5,PlatformEncoderModule:5`. Likely obstacles: the rate-control modes
   and packed headers Firefox wants against what the driver reports, and the upload path of
   the software surface backend.
3. **Chrome networking** (blocker 3), then rerun the Chrome WebRTC loopback.
4. **Deploy accepted Mali revision 7** (blocker 4), retaining the existing native tests.
   Investigate the all-intra bitrate mode through the LineageOS OMX mapping above;
   accept pixels, one output per input, and bitrate together. Screen-share VPP still
   needs performance work.
5. **Colour metadata** (blocker 5) and the Baseline IDR.
6. Adreno: nobody has run any browser encode on the Note10+. Do it after 1.

## How to test

Host checks, no phone:

```sh
python3 tests/packaging/test-mali-acceleration.py
python3 tests/packaging/test-firefox-video.py
```

On the S20, private display, private daemon (tools are on the phone, copies in
`temp/gpu-x1s/`):

```sh
cd ~/gpu-x1s/browser-tests
# WebRTC loopback from a canvas; checks the received picture's colour, prints ICE state.
bash webrtc-run.sh chromium h264,vp9 ~/gpu-x1s/vaapi-5
# WebCodecs, one codec. This is the run that crashes the GPU process: read the rules first.
XDG_CONFIG_HOME=$PWD/OUT/config EXP_VA_ROOT=~/gpu-x1s/vaapi-5 timeout -k 10 300 \
  dbus-run-session -- python encode-probe-one.py chromium $PWD/OUT
```

`exp-launcher.py` runs a browser through the installed launcher and takes `EXP_FEATURES`
(appended to `--enable-features`), `EXP_ENV` (JSON) and `EXP_VA_ROOT` (a private driver
tree). `~/gpu-x1s/unify/unify-launch.py` does the same through a private copy of the
launcher code.

The native suite ([ENCODING.md](ENCODING.md), "Running the tests") needs VA-API builds of
FFmpeg and GStreamer's `va` plugin in a prefix. Give it `</dev/null` inside an `ssh 'bash -s'`
script: its children read stdin.

Accept an encode only when the daemon log shows an encoder session with frames in and out
**and** the output decodes in software to the right pictures. A hardware string or a profile
list is not an encode.

## Rules learned the hard way

- **Never loop a crashing GPU process, and check memory between browser runs**
  (`MemAvailable` at least 3 GB). On 2026-11-11 the WebCodecs crash loop plus back-to-back
  Chrome runs made Android kill Termux and the running desktop.
- **Set `XDG_CONFIG_HOME` for encode probes.** Early ones wrote crash dumps into the real
  `~/.config/chromium/Crash Reports`.
- **The camera suite records whoever is in front of the phone.** Delete its media after
  checking and keep it out of evidence.
- A daemon started before a `termux-va` upgrade keeps serving the old code until it
  restarts. Check which daemon answered (`<socket>.encoders`, the daemon log) before blaming
  the driver.
- Private displays only; never the live `:0`. Mark `temp/PHONE-STATUS` busy first. Do not stop
  processes you did not start. Builds go through GitHub CI.

## Where things are

| What | Where |
| --- | --- |
| Driver encode changes | `packages/android-vaapi/0100-termux-va-encode.patch` (shared by the glibc driver) |
| Daemon changes | `packages/termux-va/0001-encoder-for-snapdragon-omx.patch` |
| Render-node preload | `packages/android-vaapi/render-node.c` |
| Session wiring | `native_encode()`, `start_video_daemon()` in `src/native/desktop.py` |
| Browser flags | `command_line()` in `src/native/acceleration.py` |
| Native suites | `tests/video-encode/` |
| Browser probes | phone `~/gpu-x1s/browser-tests/encode-probe*.py`, `webrtc-run.sh`; host `temp/gpu-x1s/encode-probe*.py` |
| Browser evidence | `temp/gpu-x1s/panvk-runs/51` to `54` (WebCodecs, crash dump), `64` to `66` (Chrome, WebRTC) |
| Native S20 evidence | `temp/gpu-x1s/va-encode-pixel-results.json`, `encode-daemon-run.txt`; phone `~/gpu-x1s/encode-daemon/` |
| Earlier notes | `temp/gpu-x1s/BROWSER-VIDEO-HANDOFF.md`, `CHROME-VIDEO-FINDINGS.md` |
