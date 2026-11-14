# Handoff: hardware video encoding

> **Start with the per-feature pages in [handoff/](handoff/README.md)** (encoding and decoding,
> one page each for Chromium, Chrome, Firefox and native programs). This page is the longer
> record they were drawn from.

State on 2026-11-13, for whoever takes encoding next. It covers both phones: the Note10+
(Snapdragon 855, Adreno 640, Android 11), where native encoding was built, and the Galaxy S20
(`x1s`, Exynos 990, Mali-G77, Android 13), where the browsers were tested. Decoding is not
covered here; see [MALI-GPU-STATUS.md](MALI-GPU-STATUS.md).

Read [ENCODING.md](ENCODING.md) for the design and the Adreno results, and
[X1S-BROWSER-VERIFICATION.md](X1S-BROWSER-VERIFICATION.md) for the browser runs. This page says
what works, what is blocked and by what, and what to do next. Paths under `temp/` are local
files that Git ignores.

The packages, tests and probes named below are on the `fix/chromium-webcodecs-shmem` branch
until they pass on the phone; only the documentation is on main.

## Checkpoint — 2026-11-14 06:40 UTC (Nov 13 Pacific)

**Browser hardware encoding is still not enabled by default.** Native encoding
already uses hardware where the driver is installed.

- **Worktree and branch:** `/home/cs/debian-livecd-termux/temp/encoding-ci-worktree`, the
  single CI branch `fix/chromium-webcodecs-shmem`. The root checkout holds other work: leave it.
- **Chromium revision 2 is not built yet.** The dependency bootstrap
  [43538498322](https://github.com/cnshing/debian-livecd-termux/actions/runs/43538498322)
  compiled for 2 h 20 min and then failed to upload: an artifact refuses the colon in
  `ca-certificates-java_1:2026.10.20-1_all.deb`. The browser job would have failed the same
  way after its own build. `058ebe1` leaves the epoch out of uploaded file names and restores
  the builder's names from each package's control fields. The bootstrap was restarted as
  [43564525031](https://github.com/cnshing/debian-livecd-termux/actions/runs/43564525031)
  at 06:04 UTC and starts the browser build itself when it succeeds. Do not start a
  duplicate, and **do not change `packages/chromium` while the chain runs**: the dependency
  artifact is named by that recipe's hash, and the browser job would not find it.
- **Firefox hardware encoding will not be enabled (user's decision, 2026-11-14).** Its two
  remaining problems are in Firefox itself; see "Firefox: known problems" below. Do not
  spend more work on it unless Mozilla fixes them or the user changes this decision.
  Chromium revision 2 is the browser encoding path.
- **Phone:** released, `temp/PHONE-STATUS` says available. Revision 5 is extracted at
  `~/gpu-x1s/eaccept-ff5b` on the S20, not installed. LAN SSH works through
  `temp/gpu-x1s/encoding-acceptance-20261113/ssh-lan`; the phone was off the network
  between about 01:35 and 05:55 UTC.
- **Evidence:** `temp/gpu-x1s/encoding-acceptance-20261113/`: `firefox5-control-logs.tgz`,
  `firefox5-rate-logs.tgz` (no browser profiles), the probes `accept-firefox-webrtc5.py` and
  `accept-firefox-webcodecs5.py`, and the runners `run5.sh` and `runff.sh`.

**Next:** when the Chromium chain finishes, stage revision 2 privately and run
constant-bitrate WebCodecs with saved-stream software pixel checks, then H.264 and VP9
WebRTC.

## Firefox: known problems (not pursued)

On 2026-11-14 the user decided to leave Firefox's hardware encoding off and document why.
`media.use-remote-encoder.video.platform` stays at Firefox's default (off outside
Nightly), and the launcher sets nothing for encoding. These two problems remain, and both
are in Firefox's own code, above anything this project ships. Fixing them means patching
and building Firefox, a job comparable to Chromium's six-hour build, or a fix from Mozilla.

1. **WebCodecs mislabels a canvas's colours.** Firefox converts canvas pixels to YUV with
   the BT.601 matrix, then gives the page a decoder configuration that says BT.709
   (`VideoEncoder::EncoderConfigToDecoderConfig` hardcodes it). Its decoder prefers that
   configuration to the stream's own signalling, so the page decodes with the wrong matrix:
   maximum channel error 22, 16 of 60 pictures over 16. Firefox's own software VP9 encoder
   gives exactly the same numbers, so this is not the hardware.
2. **WebRTC cannot change a hardware encoder's bitrate mid-call.**
   `FFmpegDataEncoder::ProcessReconfigure` applies a bitrate change only to `libx264` and
   Android's MediaCodec. For `h264_vaapi` it rejects it, so a call keeps the bitrate its
   encoder started with until the resolution changes. Congestion control cannot lower it.

Related facts for anyone reopening this:

- This Firefox has no software H.264 encoder (no OpenH264 plugin). Without the hardware
  encoder it cannot send H.264 at all: an H.264 call connects with zero frames, and
  WebCodecs reports H.264 unsupported. VP9 calls use its software encoder and work.
- The HEVC WebCodecs configuration tested is unsupported, and `MediaRecorder` was never run
  with hardware encoding.
- The work that does run is kept, and is harmless while the preference is off:
  `android-firefox-video` 9.0.2-5 (I420 upload, empty-drain fix, frame rate from
  timestamps) and `tests/video-encode/test-firefox-ffmpeg.py`. The frame-rate problem it
  fixed (Firefox declaring 450 fps for a 30 fps call) is described below.

## Firefox: frame rate and colour controls (2026-11-14)

### The WebRTC failure was the declared frame rate

Firefox's WebRTC sender does not tell the encoder the capture rate. It passes libwebrtc's
`VideoCodec::maxFramerate`, which
[`VideoStreamFactory::SelectFrameRate`](https://github.com/mozilla-firefox/firefox/blob/28b7a7bffb5f82828143d9ad63839ad263b598be/dom/media/webrtc/libwebrtcglue/VideoStreamFactory.cpp#L336)
computes as the H.264 level's macroblock rate over the picture size: 108,000 for level 3.1,
so 450 fps at 320x180, 211 at 480x270 and 117 at 640x360. The three requests in the old log
are those three sizes. VA-API has no timestamps, and the daemon numbers pictures at the
declared rate, so the Exynos encoder spread the bitrate over 450 pictures a second while
about 27 arrived.

| Run on the S20, same page, 30 fps canvas | Sent | Received | Colour check |
| --- | --- | --- | --- |
| Revision 4, as Firefox declares | 86 kb/s of a 288 kb/s target | 320x180, never larger | fails (the page requires 640 wide; earlier run also two samples off) |
| Revision 4, page caps the sender at `maxFramerate: 30` | 156 kb/s | 640x360 | passes |
| Revision 5, as Firefox declares | 155 kb/s | 640x360, 246 encoded, 245 decoded | passes |

The cap is the only difference between the first two rows, so the rate is the cause.
Revision 5 (`0102-follow-real-picture-rate.patch`, CI
[43566269511](https://github.com/cnshing/debian-livecd-termux/actions/runs/43566269511))
gives the driver the declared rate up to 60 fps, otherwise 30, and scales the rate-control
bitrate by the interval measured from the pictures' timestamps. The three hardware sessions
then open at `fps=30/1` and change bitrate once or twice each. VP9 WebRTC still uses
Firefox's software encoder and passes.

`tests/video-encode/test-firefox-ffmpeg.py` now encodes five streams per codec whose declared
and real rates differ. Revision 4 fails two per codec, 1.0 of 2.0 Mb/s for "450 declared,
30 sent" and for "30 declared, 15 sent"; revision 5 passes all 18 checks at 1.80 to 2.06 Mb/s.

**Still open for WebRTC:** Firefox applies a bitrate change on the fly only to `libx264` and
Android's MediaCodec
([`ProcessReconfigure`](https://github.com/mozilla-firefox/firefox/blob/28b7a7bffb5f82828143d9ad63839ad263b598be/dom/media/platforms/ffmpeg/FFmpegDataEncoder.cpp#L287)).
For `h264_vaapi` it rejects the change, so the stream keeps the bitrate its encoder was
created with until the resolution changes and a new encoder starts. Congestion control
cannot lower it in between. This runtime cannot change that. For scale: this Firefox has
no OpenH264 plugin, so without the hardware encoder it sends no H.264 at all (the earlier
"connected, 0 frames").

### The WebCodecs canvas colour error is Firefox's own

The same canvas page was run with `hardwareAcceleration: "prefer-software"`:

| Encoder | Chunks, decoded | Maximum channel error | Pictures over 16 |
| --- | --- | --- | --- |
| Firefox software VP9 (`libvpx-vp9`, no daemon client) | 60, 60 | 22 | 16 |
| Hardware VP9, revision 5 | 60, 60 | 22 | 16 |
| Hardware H.264, revision 5 | 60, 60 | 22 | 16 |

Firefox converts a canvas to I420 with BT.601 and then describes the stream as BT.709 in the
decoder configuration it hands the page
([`EncoderConfigToDecoderConfig`](https://github.com/mozilla-firefox/firefox/blob/28b7a7bffb5f82828143d9ad63839ad263b598be/dom/media/webcodecs/VideoEncoder.cpp#L605)).
Its decoder takes a complete configured colour space over the stream's own
(`VideoDecoder.cpp`, line 873), so writing BT.601 into the stream would not change what the
page sees. The hardware encoder keeps the pixels it is given: the saved streams decode to
error 2 with the matrix they were converted in. Software H.264 could not be compared; this
Firefox reports it unsupported.

Both hardware runs kept 60 units in and 60 packets out with two key frames and no bitrate
change. Do not loosen the page's check. The user decided not to enable Firefox on this
basis (see "Firefox: known problems").

## Acceptance in progress (2026-11-13)

The Linux/Bionic WebCodecs adapter now has a shared-memory input patch in
`packages/chromium/0100-termux-webcodecs-shmem.patch` (Chromium revision 2).
It selects both `kShmem` and CPU frame preparation; its Chromium regression test
covers ordinary CPU and mappable shared-image frames. The patch applies to the
prepared source, but that C++ regression test has not been compiled or run.

[Packages CI run 43421748237](https://github.com/cnshing/debian-livecd-termux/actions/runs/43421748237)
hit its six-hour job limit at 28,875/28,941 Ninja actions, without a compiler error.
The adapter compiled for both host and target; its regression test remains unrun.
Host tools consumed about 1¾ hours of that job. A dependency-only bootstrap
builds and uploads the exact dependency packages, then automatically dispatches
the normal Chromium build with a fresh six-hour window. Its first run, 43538498322,
lost its packages at upload; 43564525031 replaced it (checkpoint above). The browser job reuses
matching dependency artifacts from the same single CI branch,
`fix/chromium-webcodecs-shmem`; build flags are unchanged. The bootstrap does not
publish an apt repository or a Chromium artifact. The S20 still has revision 1.
A fresh isolated baseline on its installed stack passed H.264 (283 browser frames,
285 daemon packets) and VP9 (280 browser frames, 282 daemon packets), with correct
received colours and no GPU crash. The daemon names Exynos hardware encoders for
both sessions. This baseline does not accept the WebCodecs fix.

The initial installed-runtime Firefox WebCodecs baseline was probed through its launcher and a private
profile/display. With `hardwareAcceleration: "prefer-hardware"` and constant
bitrate, `isConfigSupported` returned false for `avc1.42001f`, `vp09.00.10.08`,
and `hvc1.1.6.L93.B0`. No encoder session was opened. The `HWENC` profile listing
therefore does not establish an accepted Firefox encode. Private revision 4 follow-up
results below supersede this baseline for the experimental runtime.

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
VAAPI encoders and an I420-to-NV12 upload adapter; it built successfully in
[CI 43427375309](https://github.com/cnshing/debian-livecd-termux/actions/runs/43427375309)
on the same CI branch. Private H.264 and VP9 WebCodecs runs with
`media.use-remote-encoder.video.platform=true` still return `EncodingError` before
any daemon encoder session. VP9 logs `Cannot open a VA display from DRM device
(null)` after selecting render node 0. A private RDD-sandbox-disabled diagnostic
returns the same failure; no sandbox setting has changed by default. A standalone
ctypes probe initializes all three new encoders and their upload pools successfully,
but this is not acceptance of frame encoding. Resolve Firefox VA display creation
before proceeding to software-decode/pixel acceptance. No Firefox preference
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

### Firefox follow-up: local libdrm, empty drain, and colour metadata

Promoting the installed libdrm to global visibility in a private diagnostic lets
revision 3 open the VA display and send **60 VP9 frames through
`OMX.Exynos.VP9.Encoder`**. The existing global DRM shim can miss libdrm loaded as
a local dependency; emulated render-node descriptors then fall through to a missing
function. Revision 8 adds a Bionic-only lookup through an already-loaded libdrm
handle when `RTLD_NEXT` fails. It does not promote the library globally.

Firefox then drains and recreates its encoder, and drains the empty replacement.
FFmpeg's hardware encoder base dereferences `pic_end` when it is NULL in that
case (`input_order == decode_delay == 0`). The RDD process dies, the flush fails,
and the page receives only 59 of the 60 hardware packets. Revision 4 of the private
Firefox runtime guards this timestamp adjustment. Both fixes built successfully in
[CI 43436860855](https://github.com/cnshing/debian-livecd-termux/actions/runs/43436860855),
commit `ab84dd2`, on the same CI branch. The device regression
`tests/video-encode/test-firefox-ffmpeg.py` loads the codec libraries locally and
checks an empty drain for H.264, HEVC and VP9. **All three pass on the new CI
artifacts without the global-libdrm workaround.**

On revision 4 plus driver revision 8, Firefox WebCodecs H.264 and VP9 both
return **60 chunks, two key frames, and 60 decoded pictures**, with no encode or
flush error and no RDD crash. Hardware sessions report 60 input units and 60 output
packets each. The saved streams decode in standalone software with maximum channel
error 2. Firefox's own decoder configuration still gives error 22 (16 of 60 pictures
exceed 16). The tested HEVC configuration remains unsupported, without an encoder
session. These are private runtime/profile tests; no installed preference changed.

Firefox WebRTC also now reaches the Exynos H.264 encoder: 232 daemon units/packets,
230 browser frames encoded and decoded, connected ICE. **Its received colour check
fails**, so it is not accepted. VP9 uses software, encodes 198 and decodes 196 frames,
and passes colours. The H.264 session requests `fps=450/1` despite an approximately
30 fps canvas; investigate this rate metadata alongside colour propagation before
claiming bitrate or latency qualification.

Driver revision 8 passes the native discovery suite (compiler smoke skipped).
An initial GLX comparison lost its Xvfb server to a segmentation fault after the
first client's connection closed. The harness now uses `-noreset` to keep its private
server alive between clients. With that change GLX and surfaceless EGL match with
and without the preload, and the suite reports zero unexpected results. The live
`:0` desktop and shared daemon remained running throughout.

The saved 59 VP9 pictures decode correctly in standalone software FFmpeg, maximum
RGB channel error **2**. Firefox's supplied decoder configuration instead gives
maximum error **22** (15 frames exceed 16). Forcing BT.601 interpretation gives 2;
forcing BT.709 reproduces 22. The elementary stream leaves its colour space
unspecified. Mozilla's pinned
[`VideoEncoder::EncoderConfigToDecoderConfig`](https://github.com/mozilla-firefox/firefox/blob/28b7a7bffb5f82828143d9ad63839ad263b598be/dom/media/webcodecs/VideoEncoder.cpp#L605)
hardcodes BT.709 in the output decoder configuration, independent of the actual
input conversion. This is still a browser-visible acceptance failure; do not hide
it by loosening pixel checks or changing the page's decoder configuration.

Evidence is in `firefox3-followup-logs.tgz` (logs/results, no browser profiles),
`firefox3-vp9-chunks.json`, and `firefox3-vp9-matrix.txt` under the local acceptance
directory. The diagnostic scripts and source copies are retained there too.

### Explicit BT.709 input control

A further private revision 4/driver 8 diagnostic constructs limited-range I420
frames with BT.709 coefficients and explicit `VideoFrame.colorSpace` metadata.
H.264 and VP9 each produce **60 chunks, two key frames, and 60 browser-decoded
pictures**, with clean flush and no encoder error. Browser maximum channel error
is 12, with zero pictures above 16. Each Exynos session reports 60 inputs and 60
packets. Standalone software decode forced to BT.709 gives maximum error 2;
default/BT.601 interpretation gives 21 (17 pictures above 16). Together with the
canvas results above, this demonstrates that the hardware preserves the two input
matrices while output signalling remains insufficient. This control is not
acceptance of ordinary canvas input or WebRTC.

The reusable [WebCodecs phone probe](https://github.com/cnshing/debian-livecd-termux/blob/fix/chromium-webcodecs-shmem/tests/video-encode/webcodecs.html)
accepts `codec=avc1.42001f` or `vp09.00.10.08` and `input=canvas` or `bt709` in its
query string. Serve on localhost/HTTPS through a private browser session; inspect
`window.RESULT` and confirm hardware use in the private daemon log. The committed probe was also exercised on the phone with VP9/BT.709: 60 chunks,
60 decoded pictures, clean flush, maximum error 12. Optional
`save=1` posts chunks to `/chunks` for independent software decoding. Preserve the
canvas case as the acceptance gate rather than replacing it with this control.

The anomalous WebRTC rate originates before FFmpeg/VA: the existing Mozilla log
already says `Request platform encoder ... frameRate=450`.
[`WebrtcMediaDataEncoder::CreateEncoder`](https://github.com/mozilla-firefox/firefox/blob/28b7a7bffb5f82828143d9ad63839ad263b598be/dom/media/webrtc/libwebrtcglue/WebrtcMediaDataEncoderCodec.cpp#L258)
passes `VideoCodec::maxFramerate` directly into `EncoderConfig`, and
`FFmpegVideoEncoder` copies that value to `AVCodecContext::framerate`. The source
was traced and fixed on 2026-11-14 (section above), in Firefox's private FFmpeg
rather than the driver, so other VA clients keep their declared rates.

Evidence: `firefox4-bt709-{avc,vp9}-run.txt`, private daemon logs, saved chunks and
software-decode results in the local acceptance directory; `firefox4-bt709-logs.tgz`
contains the results, daemon logs and chunks (gzip integrity checked). LAN SSH on port 8022
remains available when wireless ADB discovery disappears; verify the saved x1s
host key before connecting.

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
| Firefox | reported blocklisted (`VIDEO_ENCODING_MISSING`) before the probe fix; not rechecked | **not pursued, off by decision.** Installed hardware encode fails. Private revision 5: H.264 WebRTC loopback passes in hardware; WebCodecs H.264/VP9 produce 60/60 with the same canvas colour error as Firefox's software encoder; HEVC config unsupported |
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

1. **Accept the already-patched Chromium revision 2 after the CI chain completes**,
   then add `AcceleratedVideoEncoder` to Chromium's features
   on Mali in `command_line()` of `src/native/acceleration.py`, with a host test beside
   `test_glibc_mali_driver_precedes_the_prebuilt_mesa` in
   `tests/packaging/test-mali-acceleration.py` (that test currently asserts the flag is
   absent). Require confirmed hardware frames, a clean flush, independently software-decoded
   correct pixels and a passing WebRTC loopback without a GPU crash. A successful
   software fallback alone does not qualify a hardware default. Gate by fixed package
   revision; leave prebuilt Chrome and older Chromium builds unchanged. The receipt
   `share/doc/chromium/livecd-vaapi.json` has no revision, and adding a field means another
   six-hour build, so read the installed package's version from dpkg instead.
2. **Firefox: nothing.** Its hardware encoding stays off by the user's decision; see
   "Firefox: known problems".
3. **Chrome networking** (blocker 3), then rerun the Chrome WebRTC loopback.
4. **Qualify Mali revision 8 for deployment** (blocker 4), retaining the existing
   native tests. Revision 7 passed 46/46 FFmpeg checks; revision 8 passes native
   discovery and the Firefox local-library/empty-drain regressions. Rerun the full
   native encoding suite on revision 8 before treating those as its results.
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
