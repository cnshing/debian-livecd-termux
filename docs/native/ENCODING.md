# Hardware video encoding for native programs

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

**Hardware encoding has limited support.** This page covers the Snapdragon phone. For Samsung
Exynos phones, including what does not work there and why, see
[ENCODING-EXYNOS.md](ENCODING-EXYNOS.md).

Built and tested on the connected Galaxy Note10+
(Snapdragon 855, Adreno 640, Android 11), with Termux:VA `ae14813` and Mesa for
Android Container `eb3e7fd4`. Nothing here is installed on the phone yet, and the
live desktop was not used.

**Question:** can native Termux programs use the phone's hardware encoders
through Termux:VA the way Linux programs use VA-API, so that a program that
encodes the [camera](../termux-camera-investigation.md) works without being
patched or configured for this phone?

**Answer: yes, for H.264 and HEVC.** Programs find the encoder where Linux
keeps it, as `/dev/dri/renderD128`, and use it through their usual VA-API code.
Nothing names a device, a driver or a `TERMUX_VA_*` setting. Serein's own
camera-encoder test selects `vah264enc` and is served by the Snapdragon's
hardware AVC encoder. FFmpeg's `h264_vaapi` and `hevc_vaapi` record the live
camera at 1280×720, 30 fps, in real time. Every encoded frame matches the frame
the camera gave. Programs still need builds with their standard VA-API option
on, which Termux leaves off; see [what programs need](#what-programs-need).

```text
program (GStreamer va, FFmpeg VA-API, ...)
  → libva → open /dev/dri/renderD128      liblivecd-render-node.so: KGSL as a DRM render node
  → kgsl_drv_video.so (Mesa VA bridge)     driver name from the node; settings applied by itself
  → Unix socket, one raw NV12 picture in, one access unit out
  → termux-va → MediaCodec: OMX.qcom.video.encoder.avc / .hevc
```

## Browsers on the Galaxy S20 / Mali-G77 (2026-11-15)

On Mali (`/dev/mali0`) the launcher turns on `AcceleratedVideoEncoder` for
Chromium and Chrome (`command_line()` in
[`acceleration.py`](../../src/native/acceleration.py)). Firefox needs an opt-in.
On Adreno (Note10+, 2026-11-16) it is on for Chromium only: WebCodecs H.264 passed 60 of 60
frames on `OMX.qcom.video.encoder.avc` (maximum colour error 10) and WebRTC H.264 287 frames,
received picture viewed. Chrome stays off there: on Adreno it uses the prebuilt glibc driver,
which encodes the 16-aligned surface without the crop, so a 640x360 call arrives as 640x368 with
a green band at the bottom. The Snapdragon 855 has no VP9 encoder, and Chromium offers no
VA-API HEVC encoding.

| Browser | Default on Mali | WebRTC H.264/VP9 | WebCodecs `VideoEncoder` |
| --- | --- | --- | --- |
| Chromium (this project's build) | **On** from `156.0.8078.79-3`; older revisions stay off | Passes: 286 and 284 frames, received 640x360 pictures viewed | Passes: H.264 and VP9, 60 of 60 frames on the Exynos encoders, maximum colour error 12 |
| Google Chrome (prebuilt, Bionilux) | **On**, by the user's decision, for WebRTC | Passes with Bionilux `0.5.0-2`: 278 and 280 frames, received frames viewed | **Crashes the GPU process**; the page gets `OperationError: Encoding error.` This cannot be fixed outside Chrome |
| Firefox | Off; opt in with `"firefox_encode": true` | Passed at 640x360 with an earlier private runtime | 60 of 60 frames, but wrong colours from Firefox's own BT.709 label; the patched build below relabels it, untested on the phone |

**Chromium.** Revision 1 crashed: WebCodecs on Linux asks for GPU-memory-buffer
input, which is shared memory here, and a `gfx::NATIVE_PIXMAP` check in the GPU
process aborted. Revision 2
([`0100-termux-webcodecs-shmem.patch`](../../packages/chromium/0100-termux-webcodecs-shmem.patch))
sends shared memory instead, and revision 3
([`0101-termux-vaapi-upload-nv12.patch`](../../packages/chromium/0101-termux-vaapi-upload-nv12.patch))
lets VA-API upload the resulting NV12 frames. Encoding does not need the
dma-heap library. WebCodecs needs `bitrateMode: "constant"`, because Chromium
refuses variable bitrate on VA-API outside ChromeOS. Never add
`--video-capture-use-gpu-memory-buffer`. Not yet tested: MediaRecorder, HEVC
WebCodecs, and any Adreno phone. Revision 3 reaches users only once the
packages build on main has published it.
[Handoff](handoff/encode-chromium.md).

**Chrome.** WebRTC used to find no network interfaces under Bionilux, because
Android's SELinux refuses Chrome's netlink socket. Bionilux `0.5.0-2`
(`packages/bionilux/0002-netlink-route.patch`) reports the refused bind as
success and answers the interface dump from `ioctl()`. Chrome's WebCodecs path
always requests GPU-memory-buffer input, and Chrome is prebuilt, so it cannot be
patched. With the encoder on, a page that asks WebCodecs for hardware encoding
crashes Chrome's GPU process. [Handoff](handoff/encode-chrome.md).

**Firefox.** [`packages/firefox`](../../packages/firefox) builds Firefox with
two patches. One labels WebCodecs output BT.601, the matrix Firefox actually
converts with. The other lets WebRTC change a VA-API encoder's bitrate
mid-call. The opt-in applies only on Mali, and only when the installed
`android-firefox-video` manifest lists its encoders. The patched build has not
been tested on the phone. [Handoff](handoff/encode-firefox.md).

In every browser the Exynos encoders refuse MediaCodec's `low-latency` key, so
the daemon retries without it, and call latency is unmeasured. Playback and
package status are in the [browser verification](X1S-BROWSER-VERIFICATION.md).
The Adreno investigation below is historical; its statements about installation
and browser builds apply to that test session.

## Testing at the boundaries instead of per program

Programs do not talk to the encoder themselves. They call one of a few client
libraries, and those libraries find a device and drive VA-API in their own
ways. The suite tests each of those boundaries with pixel checks, and each check
has a control that must fail:

| Boundary | Used by | Suite |
| --- | --- | --- |
| Device discovery: `/dev/dri`, `stat`, sysfs, `drmGetVersion`, `drmGetDevice2`, `vaGetDisplayDRM` | Every VA-API program | `test-render-node.sh`, `va-probe.c` |
| GStreamer `va` plugin, `vah264enc`/`vah265enc` | Serein, GNOME programs, GStreamer pipelines | `test-gstreamer.py` (Serein's camera and screen-share pipelines, element for element) |
| libavcodec `h264_vaapi`/`hevc_vaapi` | `ffmpeg`, OBS's VAAPI encoder, other libavcodec programs | `test-ffmpeg.py` |
| The Termux:VA protocol | The driver | `test-daemon.py` |
| Camera to encoder in real time | Webcam and streaming programs | `test-camera-encode.sh` |

Browsers have their own VA-API clients. The original Adreno suite did not cover
them; the Mali browser results are [above](#browsers-on-the-galaxy-s20--mali-g77-2026-11-15).

## Results

From the final runs, `run-phone-tests.sh` against the stack layout
`build-native.py` produces. The camera results come from the run just before the
final one, with the same driver and daemon.

| Check | Result |
| --- | --- |
| Hardware encoders listed by the daemon | `video/avc OMX.qcom.video.encoder.avc`, `video/hevc OMX.qcom.video.encoder.hevc`. No VP9 hardware: the request is refused, not run in software |
| Key frames, H.264 Constrained Baseline/Main/High and HEVC Main | IDR exactly at each requested picture (0, 30, 45, 46, 89), with SPS and PPS before each; no others |
| Pixels, protocol test | 43.5–46 dB on every plane; a one-frame shift fails 89 of 90 frames, swapped chroma 90 of 90 |
| Bitrate | 1 and 6 Mb/s targets give 1.00 and 6.01 Mb/s; a change from 6 to 0.6 Mb/s mid-stream takes effect (6.07 to 0.56 Mb/s) |
| Device discovery | All checks pass with the preload and fail without it; libdrm reports a platform device with the device-tree name |
| What the preload must not change | Mesa's GL renderer, X11 and surfaceless, same output; bash, Python and clang run; stat, open and close cost 18 µs either way |
| `TERMUX_VA_DECODE=0` | GStreamer lists `vah264enc vah265enc` only, against all four elements without it |
| Serein's own test, `camera::encode_linux` | "Synthetic camera encoder test using vah264enc", passes; served by `OMX.qcom.video.encoder.avc`. Without the setup it names no backend |
| Serein's `discord-voice` tests | 67 passed, 1 ignored, identically with and without the setup |
| Serein camera pipeline, replica | 60 of 60 access units, each an IDR with parameter sets, Constrained Baseline, 622 kb/s for 600; 45–46 dB at 8 Mb/s. With key-int-max 30, Serein's check rejects 56 of 60 |
| Serein screen share, VA memory | IDR every 60 pictures; Y 37.2, U 32.8, V 30.1 dB (see limits) |
| FFmpeg, uploaded pictures, all four profiles | 120 pictures, IDR every 30, parameter sets on each, right `profile_idc`, 36–46 dB |
| FFmpeg, 640×360 and 854×480 | Decode at that size, 36–46 dB. Before the crop fix both came out 640×368 |
| FFmpeg MP4 | Key-frame flags on every IDR; seeking to 1 s and 3 s decodes the right picture |
| GPU transcode, `-hwaccel vaapi`, `scale_vaapi`, `hevc_vaapi` | Runs; 42.0, 39.7, 38.3 dB against the scaled source |
| Live camera, `h264_vaapi` and `hevc_vaapi`, 1280×720 | 300 of 300 and 301 of 301 frames in 10.6 s; `ffmpeg` 28–31% of one core; every frame 41–53 dB against the camera's own frame; key frame every 30; seeking works |
| Live camera through Serein's encoder | 62 of 62 pictures accepted at 600 kb/s; 49–52 dB at 8 Mb/s |
| Round trip per picture, protocol test | 720p 16.5–22.4 ms; 1080p 22–35 ms, depending on load |

The pictures were opened, not only scored: a VA-memory difference image located
that path's loss, and a decoded camera frame against its neighbors exposed a test
error (below).

## What was changed

All changes are generic: none is specific to a program.

- **Daemon** ([patch](../../prebuilt/native-video/daemon-patches/0001-livecd-encoder.patch)).
  On this phone `AMediaCodec_configure` failed for every encoder: ACodec rejects the
  Android 11 `low-latency` key for OMX encoders. Upstream tested only Codec2
  (`c2.qti.*`) phones. The daemon now retries once without it. VA-API clients choose
  picture types, so a key frame follows each per-picture request instead of a fixed
  one-second period. Parameter sets precede every key frame, and the target bitrate
  can change mid-stream, as WebRTC changes it. The daemon writes its hardware
  encoders to `<socket>.encoders` and refuses Android's software ones.
- **VA driver** ([patch](../../prebuilt/native-video/mesa-patches/0100-livecd-termux-va-encode.patch)).
  Sends those requests, advertises only the listed encoders, and encodes the visible
  picture. Clients code 16-aligned surfaces and crop through the SPS. With no
  configuration, where KGSL is usable, it applies the bridge's KGSL settings itself.
  `TERMUX_VA_DECODE=0` hides the decoders. 31 unconditional per-call `stderr`
  traces, which every VA program printed, now need `DMD_VA_LOG`.
- **Build** ([`build-native.py`](../../prebuilt/native-video/build-native.py)).
  Mesa's H.264 and HEVC encoder front ends are now built. The stack carries
  `kgsl_drv_video.so` for libva's name lookup, and the render-node preload with its
  sysfs folder. Each library's run path keeps `$PREFIX/lib`; the installed stack's
  `libva-x11` could not load without it, since Bionic does not use a program's run
  path for a library's dependencies.
- **Render node** ([`livecd-render-node.c`](../../prebuilt/native-video/livecd-render-node.c)).
  The phone's own `/dev/dri/card0` and `renderD128` are the display controller's,
  and SELinux denies them to apps, so scanning programs found nothing. The preload
  presents KGSL in their place, as the camera preload presents cameras. Unhandled
  `syscall()` calls go to the next definition, so it composes with other device
  preloads.
- **Session** ([`desktop.py`](../../src/native/desktop.py), [`setup.py`](../../prebuilt/native-video/setup.py)).
  `setup.py --native-encode on` records the choice. The next session adds the preload,
  after the start-up probe, and points libva at the stack's drivers. It offers
  the decoders too, unless `native_decode` is `false`, and starts the daemon if none listens.
  Unlike the launcher, it does not hide H.264 or AV1 decoding
  ([handoff](handoff/decode-native.md)).

## What programs need

| Program | Status |
| --- | --- |
| Serein (packaged) | Already compiles its Linux camera encoder for Android and tries `vah264enc`; needs only GStreamer's `va` plugin. [`packages/gst-plugins-va`](../../packages/gst-plugins-va) adds that plugin beside Termux's `gst-plugins-bad` without replacing it. The recipe's patch applies; the package has not been built in the Termux builder |
| GStreamer programs | The same package |
| `ffmpeg`, libavcodec programs | Termux's FFmpeg needs `--enable-vaapi` and `libva`. A test build of 9.0.2 needed only that, plus `-Wno-error=incompatible-function-pointer-types` for libv4l2 and `--disable-xlib`. No recipe yet: Termux's FFmpeg is in its main repository, which `tools/recipes.py` does not stage, and replacing it affects every program that links it |
| OBS Studio | Termux's recipe removes VAAPI on purpose (its patch 0007) and builds without V4L2. Restoring both needs a recipe override and libpci, which Termux does not package. Not built or tested |
| Chromium (Termux) | Our VA-API build, revision 3 or later, encodes WebRTC and WebCodecs H.264/VP9 on Mali and H.264 on Adreno, on by default on both |
| Google Chrome | Glibc stack under Bionilux `0.5.0-2`. WebRTC encodes on Mali, on by default there; WebCodecs hardware encoding crashes its GPU process |
| ungoogled-chromium | Glibc stack; encoding untested and not enabled |
| Firefox | Opt-in only (`firefox_encode`), with the patched [`packages/firefox`](../../packages/firefox) build; not yet phone-tested. See the [handoff](handoff/encode-firefox.md) |

## Limits

- **One picture at a time.** The driver sends a picture and waits for its packet.
  720p30 has room; 1080p30 is at the edge (22–35 ms against 33 ms). Overlapping
  pictures would need protocol and daemon changes.
- **Copies.** A camera picture is copied by the camera node, uploaded into a VA
  surface, read back by the driver, sent over the socket and copied into
  MediaCodec's buffer. `ffmpeg` used 28–31% of one core for 720p30. Importing
  camera buffers as dma-bufs was not attempted.
- **VA post-processing is lossy.** Mesa converts through RGB, so saturated chroma
  edges bleed. Through `vapostproc`, NV12 to NV12 scored V 30.6 dB at 20 Mb/s,
  against 50 dB without it. That is Mesa's VA post-processor, not the bridge.
  Serein's screen share uses it to convert RGB, where some loss is inherent.
- **Codecs.** No VP9 hardware encoder on this SoC, no AV1 encoder, 8-bit only.
- **Untested:** Termux's own `libva` 2.24.1, which libva's driver ABI should
  accept; the mirror and the package server returned 404. Also untested: this
  setup in the running desktop, and alongside the browser launchers' own preloads.
- **The camera pixel check cannot see frame order in a still scene.** A
  half-second shift failed only 5 of 300 frames with the phone lying still. The
  synthetic tests carry that check.

The running shared daemon was left alone. A daemon started before setup keeps
serving, unpatched, until it restarts; this phone's would fail every encoder.

## Running the tests

On the phone, after `build-native.py` and with VA-API builds of FFmpeg and
GStreamer's `va` plugin in a prefix:

```sh
bash tests/video-encode/run-phone-tests.sh --stack ~/.local/opt/livecd-native/acceleration/bionic \
  --daemon ~/.local/opt/livecd-native/acceleration/service/bin/termux-va \
  --clients PREFIX --out NEW_DIR </dev/null
```

The camera suite runs when `android-v4l2` is installed, using its
camera node and V4L2 preload. It opens the front camera through a private PipeWire; it records
whoever is in front of the phone. It writes those frames under the output
directory, so delete them after checking. Two harness errors were found on the
way and fixed:

- FFmpeg's raw output repeated a frame on timestamp jitter, shifting the
  comparison by one. A decoded frame matched its neighbor at 45.6 dB.
- `-t` placed after `-i` stopped only one of two outputs.
