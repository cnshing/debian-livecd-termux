# Video handoffs, one per feature

State on 2026-11-15. All the work below is on main (PR #12).

**Acceptance criterion:** feature parity with the S20's own encoding and decoding: every
hardware codec Android offers on that phone, up to its limits.
[s20-codec-parity.md](s20-codec-parity.md) has the target, the gaps and the order of work. The
other pages feed into it.

Each page covers one feature: what works, what is broken and why, and the
next steps in order. They are written to stand on their own. Evidence kept outside Git (under
`temp/` or on the phone) is named only where it helps; nothing here depends on it.

Two phones were used:

- **Note10+**, Snapdragon 855, Adreno 640, Android 11 ("Adreno" below).
- **Galaxy S20**, `x1s` / SM-G981B, Exynos 990, Mali-G77, Android 13, stock kernel, no root
  ("Mali" or "S20" below).

## Where each feature stands

| Feature | Adreno | Mali (S20) | On by default? | Page |
| --- | --- | --- | --- | --- |
| Chromium decode | VP9, HEVC, H.264 hardware pass (revision 3, 2026-11-16) | VP9, HEVC hardware pass (revision 3 with the dma-heap bridge, 2026-11-15) | yes; AV1 software, H.264 software on Mali | [decode-chromium.md](decode-chromium.md) |
| Chrome decode | VP9, HEVC, H.264 pass (2026-11-16) | HEVC passes; VP9 decodes in hardware but misses one SSIM check | yes; AV1 software, H.264 software on Mali | [decode-chrome.md](decode-chrome.md) |
| Firefox decode | VP9, HEVC, H.264 pass (2026-11-16) | VP9, HEVC pass, on a Zink desktop only | yes; AV1 software, H.264 software on Mali | [decode-firefox.md](decode-firefox.md) |
| H.264 decode, every VA-API client | passes: FFmpeg, GStreamer, all three browsers (2026-11-16) | off | yes on Adreno; Mali browser runs still to do | [decode-h264.md](decode-h264.md) |
| Frame sync: stale frames, flicker, tearing | one stale frame in 13 runs under load | not seen | n/a | [decode-frame-sync.md](decode-frame-sync.md) |
| Note10+ Chrome typing: last character missing or caret rewinds | reproduced; stale DRI3 present in glibc Turnip, fixed in android-vaapi-glibc 14, installed and verified | not tested | n/a | [note10-chrome-typing.md](note10-chrome-typing.md) |
| Note10+ flickering black or see-through rectangles (Chrome, video) | user report 2026-11-18, not reproduced | not tested | n/a | [note10-gpu-rectangles.md](note10-gpu-rectangles.md) |
| S20 PanVK presentation over raw DRI3 instead of MIT-SHM readback | n/a | not started; needs a present fence wait first | no (software path) | [s20-panvk-raw-dri3.md](s20-panvk-raw-dri3.md) |
| Native decode: mpv, FFmpeg, GStreamer | mpv passes VP9, H.264, HEVC | mpv passes on its GLES route | mpv yes; VA-API clients see decoders | [decode-native.md](decode-native.md) |
| Native encode: FFmpeg, GStreamer, Serein | passes | passes in private tests; fresh-install blockers fixed on main, not rechecked | yes where `android-vaapi` is installed | [encode-native.md](encode-native.md) |
| Chromium encode | WebRTC and WebCodecs H.264 pass on hardware (2026-11-16); no VP9 encoder | WebRTC and WebCodecs (H.264, VP9) pass on hardware with revision 3; rerun from CI 43676101303 on 2026-11-15 | yes, revision 3+ on both | [encode-chromium.md](encode-chromium.md) |
| Chrome encode | WebRTC H.264 passes with the crop-fixed source-built glibc driver (2026-11-16) | WebRTC H.264/VP9 passes on Exynos (Bionilux 0.5.0-2 netlink fix); WebCodecs crash cannot be patched | yes with the qualified driver; WebCodecs pages still crash Chrome's GPU process | [encode-chrome.md](encode-chrome.md) |
| Firefox encode | WebRTC/WebCodecs H.264 pictures pass; midstream bitrate reduction fails (2026-11-16) | both Firefox bugs patched in this project's Firefox build; opt-in `firefox_encode`; not yet run on the phone | off on Adreno; Mali stays opt-in | [encode-firefox.md](encode-firefox.md) |
| `/dev/dma_heap` emulated on `/dev/ion` for kernels without DMA-BUF heaps (the S20's 4.19) | needed too (ION, no heap) | done: the preload provides the heap; bridges use only the heap; verified installed | yes, on phones with ION and no heap | [dmabuf-s20.md](dmabuf-s20.md) |
| **Parity with the S20's codecs** | n/a | not met: H.264 decode off; VP8, MPEG-4 and H.263 not offered; 10-bit, 4K and 8K untested | n/a | [s20-codec-parity.md](s20-codec-parity.md) |
| **Parity with the Note10+'s codecs** | incomplete: VP8 VA frontend, P010 transport/HDR, encode metadata/rate control, high resolutions | unchanged | only verified paths enabled | [Note10+ report](../ADRENO-640-PARITY.md), [remaining driver work](note10-codec-parity.md) |

AV1 is disabled on every phone. Neither the Snapdragon 855 nor the S20 has an AV1 decoder, so
software AV1 is parity.

## The shared path

Every hardware codec goes the same way. Only the program at the top differs.

```text
program's VA-API code (Chromium, Chrome, Firefox's FFmpeg, FFmpeg, GStreamer va)
  → libva → termuxva_drv_video.so      packages/android-vaapi (Bionic), android-vaapi-glibc (Chrome)
  → Unix socket                        compressed data in, pictures out (decode) or the reverse (encode)
  → termux-va daemon                   packages/termux-va
  → Android MediaCodec → the phone's hardware codecs
```

Android lets an ordinary app reach the codecs only through MediaCodec. The V4L2 device nodes
behind them (`/dev/video*`) are denied to Termux by SELinux, so V4L2-based Linux drivers cannot
be used without root.

mpv is the exception: it calls MediaCodec directly through FFmpeg
(`--hwdec=mediacodec-copy`), without VA-API.

The launcher (`src/native/acceleration.py`) sets each browser's driver and environment by
device. `~/.config/livecd-native/acceleration.json` holds the user's choices: `hardware_video`,
`disabled_va_codecs` (default `['av1']` on Adreno, `['h264', 'av1']` on Mali), `native_encode` and `native_decode`.

## Rules for anyone using the phones

These were learned the hard way. They apply to every page here.

- **The phone's display is shared with the user.** Never send input to the live `:0` display;
  run tests on a private Xvfb or Termux:X11 display. Never stop a process you did not start.
- **Claim the phone first.** Write `busy` on line 1 of `temp/PHONE-STATUS` (under
  `PHONE-STATUS.lock`) before using it, and `available` after.
- **Never loop a crashing browser GPU process.** Keep `MemAvailable` at 3 GB or more between
  browser runs. On 2026-11-11 a WebCodecs crash loop plus back-to-back browser runs made Android
  kill Termux and the running desktop.
- **Give probes their own `XDG_CONFIG_HOME`**, or they write crash dumps into the user's profile.
- **Camera tests record whoever is in front of the phone.** Delete their media after checking
  and keep it out of evidence.
- **Builds go through GitHub CI.** Chromium takes most of a six-hour job.
- **A daemon started before an upgrade keeps serving the old code** until it restarts. Check
  which daemon answered (its log, `<socket>.encoders`) before blaming the driver.
- **Stop the desktop before replacing `android-vaapi`.** Every desktop process preloads one of
  its libraries.
- **Installing on the S20** goes through its local apt repository (`~/debian-livecd-termux/repo`,
  pinned at 1001). A bare `dpkg -i` is downgraded by the next upgrade.

## What counts as passing

- **Decode:** the decoder log shows hardware frames out (for Chromium and Chrome,
  `VaapiVideoDecoder` and no software decoder), and numbered frames 12 and 36 match their
  references at both the browser and the compositor layer (PSNR at least 28 dB, SSIM at least
  0.90). Open the captures and look at them; a metric alone is not a pass.
- **Encode:** the daemon log shows an encoder session with pictures in and out, **and** the
  output decodes in software to the right pictures. A listed encoder or profile is not an encode.
- Do not loosen a pixel threshold to make a run pass. Run a negative control that should fail,
  to show the check can fail.

## Older, longer records

- [ENCODING.md](../ENCODING.md), [ENCODING-EXYNOS.md](../ENCODING-EXYNOS.md): encoding design and
  results.
- [MALI-GPU-STATUS.md](../MALI-GPU-STATUS.md), [X1S-BROWSER-VERIFICATION.md](../X1S-BROWSER-VERIFICATION.md),
  [X1S-FIREFOX-VIDEO.md](../X1S-FIREFOX-VIDEO.md): Mali decode results.
- [ACCELERATION.md](../ACCELERATION.md),
  [native-acceleration-checks.md](../../browsers/native-acceleration-checks.md): the launcher and
  the Adreno results.
