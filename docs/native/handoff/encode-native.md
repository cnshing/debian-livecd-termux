# Handoff: native hardware encoding (FFmpeg, GStreamer, Serein, OBS)

State on 2026-11-14. Shared rules and pass criteria: [README.md](README.md). Design and Adreno
detail: [ENCODING.md](../ENCODING.md). Exynos detail: [ENCODING-EXYNOS.md](../ENCODING-EXYNOS.md).

## Status

**Support is limited.** On by default wherever `android-vaapi` is installed (`native_encode` in
`acceleration.json`): the session preload presents the GPU as `/dev/dri/renderD128`, so programs
find the encoder with no settings.

| Program | Adreno (Note10+) | Mali (S20) |
| --- | --- | --- |
| Encoders found | H.264, HEVC (`OMX.qcom.*`) | H.264, HEVC, VP9 (`OMX.Exynos.*`). The phone also has VP8, MPEG-4 and H.263 encoders, which the bridge does not offer ([parity](s20-codec-parity.md)). The bridge sends 8-bit NV12 only |
| Daemon's own protocol test | passes | 28 of 30; both failures are an extra key frame (below) |
| FFmpeg `h264_vaapi`, `hevc_vaapi` | 46 of 46, live camera at 720p30 in real time | 46 of 46 with driver revision 7 and a VA-API FFmpeg, privately. Colours right only with added metadata (below) |
| GStreamer `vah264enc`, `vah265enc`; Serein | pass in a test prefix | camera key frames and pixels pass (revision 6); low bitrate and screen sharing fail |
| Found with no settings | yes | **no** on the installed revision 5; yes on unreleased 7 and 8 |
| OBS Studio | no recipe | no recipe |

## Why a fresh S20 gets no hardware encoder

1. **FFmpeg has no VA-API.** Found 2026-11-14: no release carried this project's `ffmpeg`.
   `ffmpeg` is in the v0.12.0 tarball's pin list but no `ffmpeg_*.deb` is in its pool, so APT
   fell back to Termux's build. In CI's video set (run 43414277233), `android-firefox-video`
   was built before `ffmpeg`; Termux's `firefox`, its dependency, depends on `ffmpeg`, so the
   builder downloaded Termux's `ffmpeg_9.0.2-2` and then printed `ffmpeg@9.0.2-100 built -
   skipping`, and the job still succeeded. Fixed on `fix/encode-native`: `android-firefox-video`
   build-depends on `ffmpeg` so the planner orders it first, a test checks the order, and the
   build step now fails when a recipe leaves no package. Needs a CI build and a fresh-install
   check on the phone.
2. **The driver cannot find the Mali GPU.** `android-vaapi` revision 5 (on main) presents only
   the Snapdragon GPU. Revisions 7 and 8, on the CI branch
   [`fix/chromium-webcodecs-shmem`](https://github.com/cnshing/debian-livecd-termux/tree/fix/chromium-webcodecs-shmem),
   present `/dev/mali0`, also when `/dev/dri` is missing, and pick CPU-backed surfaces on Mali.
   Revision 8 adds a lookup through an already-loaded libdrm when `RTLD_NEXT` fails (libdrm
   loaded as a local dependency, as in Firefox).
3. **GStreamer has no VA plugin.** `gst-plugins-va` is a recipe and is in the release, but no overlay installed it. The Video Player overlay installs it from `fix/encode-native`. Not yet checked on a phone.

## Faults in the encoded video

| Fault | Detail | Fix |
| --- | --- | --- |
| No colour metadata | Streams do not say which matrix they use. On the S20 the colour check failed until BT.709 primaries, transfer and matrix were added with `h264_metadata`/`hevc_metadata`; then 42–48 dB, maximum channel error 1 | The daemon should set MediaCodec's colour keys from the client's VA sequence parameters, or the bridge should write the VUI |
| Extra key frame in H.264 Baseline (Exynos) | The encoder inserts an IDR nobody asked for; programs that count key frames, such as Serein's check, reject the stream | Unknown; possibly firmware |
| Low bitrates overshoot (Exynos) | Serein's 600 kb/s all-intra stream came out at 2.556 Mb/s. Samsung's OMX code sets rate-control reaction coefficient 10 for standard CBR and 5 for video-call mode; the kernel treats 1–5 as intra-limited CBR | Try Samsung's `vendor.rtc-ext-enc-bitrate-mode.value` / `.bitrate`, after checking the installed encoder offers them. Do not use `rtc-ext-enc-low-latency`: it turns rate control off |
| `low-latency` refused (Exynos) | `configure failed with low-latency: -10000`; the daemon retries without it | Latency not measured |
| Bitrate follows the declared frame rate | VA-API has no timestamps, so the bitrate is spread over the declared rate. A client that declares the wrong rate gets the wrong bitrate. Firefox did this; its private FFmpeg now works it out from timestamps ([encode-firefox.md](encode-firefox.md)) | Could move into the driver for every client |

## Speed

- **One picture at a time**: the driver sends a picture and waits for its packet. 720p30 fits;
  1080p30 is at the limit on the Note10+ (22–35 ms a picture); not measured on the S20.
- **Every picture is copied**: Android gives apps no GBM or dma-buf allocator.
- **VA-API scaling is slow**: a 120-frame scale-and-transcode took 72 s. Serein's 720p
  screen-share pipeline managed 51 frames in 118 s, so screen sharing is not usable.

## Next steps

These serve the parity criterion; [s20-codec-parity.md](s20-codec-parity.md) adds VP8, 10-bit and
4K/8K work on top of them.

1. Done in code (above); build it in CI and check `apt-cache policy ffmpeg` on a fresh S20 install.
2. Rerun the full native suite on `android-vaapi` revision 8 on both phones, then merge 6–8 to
   main and install them. Keep the ordinary-process and GL/EGL checks: the preload is loaded
   into every desktop process.
3. Done in code: the Video Player overlay installs `gst-plugins-va`. Check on a phone.
4. Colour metadata in the daemon.
5. The Exynos bitrate-mode extension, accepting pixels, one output per input and bitrate
   together. Do not allow frame dropping in Serein's test.
6. The Baseline IDR, screen-share speed, and an OBS recipe (needs libpci and Termux's patch 0007
   dropped). Rename `packages/termux-va/0001-encoder-for-snapdragon-omx.patch`: it is what makes
   Exynos work too.

## How to test

The suites are in `tests/video-encode/`; [ENCODING.md](../ENCODING.md) ("Running the tests")
says how. They need VA-API builds of FFmpeg and GStreamer's `va` plugin in a prefix. Give them
`</dev/null` inside an `ssh 'bash -s'` script: their children read stdin. The camera suite
records whoever is in front of the phone; delete its media.

## Where things are

| What | Where |
| --- | --- |
| Driver encode changes | `packages/android-vaapi/0100-termux-va-encode.patch` (also used by the glibc driver) |
| Render-node preload | `packages/android-vaapi/render-node.c` |
| Daemon changes | `packages/termux-va/0001-encoder-for-snapdragon-omx.patch` |
| Session wiring | `native_encode()`, `start_video_daemon()` in `src/native/desktop.py` |
| Suites | `tests/video-encode/` |
