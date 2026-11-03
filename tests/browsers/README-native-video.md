# Native video regression checks

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../../docs/privacy.md).

These checks cover experimental native browser and video acceleration. They do
not qualify hardware decoding for default use. Results and the allocator investigation
are in [the research report](../../docs/browsers/android-video-allocators.md).

## Shared Firefox and mpv integration

`test-acceleration.py` runs the installed shared launcher with a private DRI3 X
server, D-Bus session, XDG directories and application profile. Firefox receives
the managed acceleration preferences in its disposable profile and owns a private
MediaCodec daemon. mpv uses its direct MediaCodec path. Neither uses the live
desktop's display, browser profile or shared daemon.

From the phone, with this directory and `private-lorie/` copied together:

```sh
python browsers/test-acceleration.py firefox --fixtures fixtures-v2 --out firefox-hardware
python browsers/test-acceleration.py mpv --fixtures fixtures-v2 --out mpv-hardware
```

Both checks require advancing video frames and an application process with Turnip
mapped and KGSL open. Firefox additionally requires WebRender and log evidence of
successful VA-API initialization and decoded VA-API frames. mpv requires
`mediacodec-copy`, `gpu-next`, and a named Android hardware codec component, rejecting
the known Google/Android software components. The default fixture is VP9; select
another numbered fixture with `--case`. The full clip must advance, and a captured
frame must pass the numbered reference's barcode, colors, PSNR and SSIM checks.
These checks do not qualify fullscreen/compositor presentation. For Firefox's
deliberately hidden H.264 VA profile, `--case chart-h264.mp4 --expect-software`
checks the software fallback and records `hardware_verified: false`.

Use `--startup-only` without `--fixtures` to stop as soon as the application's
Marionette or mpv IPC connection responds. This loads no video and records
`cancelled_after_start`, `ok: false`, and `hardware_verified: false`. Exit status
zero means the requested startup and cleanup completed, not that decoding passed.
Every run writes `result.json` and `isolation.json`; use a fresh `--out` directory.

The first shared-application run (`temp/docs/evidence/browsers/native-gpu-video/`)
started both applications, but Firefox decoded VP9 in software. mpv selected
MediaCodec and GPU output; its codec-identity check was blocked by suppressed test
logging. After fixes were authorized, the runner gained an explicit mpv log,
synchronous Firefox logs, a process-exit wait and numbered-frame pixel checks.
The [follow-up](../../docs/browsers/native-acceleration-checks.md) passes Firefox
VP9/HEVC and mpv VP9/H.264/HEVC through their installed acceleration launchers.
Firefox's private KGSL probe port is installed with
`prebuilt/native-video/setup.py --firefox-kgsl`; HEVC additionally needs VA-API
FFmpeg decoder libraries. These checks do not qualify fullscreen/compositor
presentation or every codec/stream.

The phone's desktop is in use. All browser input and windows stay on a private X
server. The host runner only reads Android focus through ADB. Android display
capture, rotation, reconnect and screen power tests require a separate agreed run.

## Host checks and fixtures

Requirements: Python 3, FFmpeg/FFprobe with libvpx, libx264 and libx265, SSH and ADB.
No Python imaging packages are required.

```sh
python3 tests/browsers/test-video-tools.py -v
python3 tests/browsers/make-video-fixtures.py /tmp/video-fixtures
```

The default corpus contains 48 frames at 12 fps, in VP9, H.264 with B frames, and
HEVC. Each has eight color patches, complementary frame-number barcodes, a grid,
asymmetric corner marker, and moving high-frequency detail. FFmpeg software
decodes each clip on the PC. The manifest records the source hash, every command,
FFmpeg version, encoded color metadata, clip hashes, and every reference hash.
Encoding explicitly sets frame metadata and verifies the resulting bitstream:
output metadata options alone left H.264/HEVC primaries and transfer unspecified
during harness bring-up.

Alignment, metadata, AV1 and 10-bit fixture generation are also supported:

```sh
python3 tests/browsers/make-video-fixtures.py /tmp/video-601 --codecs vp9 --size 854x480 --matrix smpte170m --range pc
python3 tests/browsers/make-video-fixtures.py /tmp/video-10bit --codecs hevc --size 1366x768 --ten-bit
python3 tests/browsers/make-video-fixtures.py /tmp/video-av1 --codecs av1
```

Generation of these variants was checked on the PC. Their Android playback has
not been qualified. The corpus does not yet include film content, open GOPs,
midstream resolution changes, or the full resolution/encoder matrix in the handoff.

## Prepare an isolated phone workspace

Copy `tests/browsers/`, the generated corpus as `fixtures-v2/`, and
`overlays/Browser+Chromium/browsers/google-chrome` as `google-chrome`, into a fresh
phone directory, for example `$HOME/.cache/native-video-test`. Make the launcher
executable. Keep `private-lorie/` and its DEX together.

```sh
# On the phone, from that workspace:
python browsers/test-fullscreen.py chrome --browser-command ./google-chrome \
  --x-server lorie --browser-flag=--window-size=1280,1100 --require-gpu \
  --media-dir fixtures-v2 --fixture-manifest fixtures-v2/manifest.json \
  --case chart-vp9.webm --cycles 6 --out ./chrome-vp9
python browsers/test-native-mediacodec.py fixtures-v2 ./native-ffmpeg
```

The browser harness always supplies a private socket. `--private-daemon` starts
`termux-va` directly and stops only that child. It never invokes the global
Termux:VA lifecycle helpers. The Chrome launcher treats either a supplied socket
or socket directory as caller-managed and does not auto-start a daemon for it.

The host matrix runs these cases, checks that SSH and ADB identify the same boot,
checks Android focus before/after each run, and downloads evidence without browser
profiles. Use a new `--out` for each invocation:

```sh
python3 tests/browsers/run-phone-video-suite.py --ssh termux \
  --remote-root /data/data/com.termux/files/home/.cache/native-video-test \
  --adb-serial YOUR_SERIAL --out /tmp/native-video-results
```

The matrix covers Chrome GPU with VP9/H.264, Chromium GPU with VP9, Chrome software
on Lorie and Xvfb, and the wrong-color hardware negative control. Chrome's default
HEVC case is an explicit capability check: the suite requires its observed
`DEMUXER_ERROR_NO_SUPPORTED_STREAMS` with zero frames and no decoder. It prints
`EXPECTED_UNSUPPORTED`; it does not count that case as correct decoded pixels.

## What passes a pixel case

After six fullscreen cycles, seek to frames 12 and 36, fullscreen and windowed.
Wait for `requestVideoFrameCallback`, then independently identify the image by its
barcode. Capture both CDP and GNOME's compositor, normalize the video rectangle,
and compare with the PC reference for that exact frame. The comparison requires:

- Correct frame number, readable complement/sync bits and valid reference hash.
- Maximum color-channel error of 16 across eight patches.
- Whole-frame PSNR >=28 dB and SSIM >=0.90, measured at half source resolution.

The common half-resolution comparison reduces differences between FFmpeg and GPU
chroma reconstruction. Full normalized images are retained. CSS hides native
controls for fixture captures, and the fullscreen notification expires before
capture. Startup overview is dismissed before the transition test; overview that
appears during testing still fails the compositor check. Contact-sheet columns
are reference, CDP, compositor; the JSON sidecar names the images. Open the sheet
before reporting success.

`isolation.json` compares the live server, shell and shared daemon PIDs/start times
and display sockets. Focus changes also fail the host suite, even if caused by the
person using the phone; inspect the recorded before/after values before attributing
such a failure to the test.

The installed-launcher rerun retained an old fullscreen frame in GNOME's capture
while CDP was current; this also occurred with the software-decoding control.
These checks remain failures. To investigate unredirection, pass
`--composited-fullscreen` to the harness or host runner. It
loads a tiny extension only in the private XDG profile, calls
`global.compositor.disable_unredirect()`, and requires its activation marker in the
shell log. This did not reliably resolve the stale-frame failure. Captures retry
up to four times for frame-identity errors, preserving every attempt; a same-frame
pixel mismatch is never retried. The result records this mode, and the live desktop
is unaffected. `--x-server-flag` can scope additional diagnostic options to the
private server. Neither `-disable-gpu-present` nor `-legacy-drawing` resolved the
failure in the follow-up runs. See the
application evidence (`temp/docs/evidence/browsers/native-gpu-video/`).

After application, verify the actual installed launcher and the persistent opt-in
with `--installed-chrome /absolute/remote/bin/google-chrome` and `--only` selections
`installed-hardware-vp9`, `installed-hardware-hevc`, `installed-software-override`,
and `installed-color-negative`. The hardware cases leave the environment override
unset and own a private daemon, so they exercise the user's saved configuration.
The software case explicitly requires `VpxVideoDecoder`; the negative control sets
`LIVECD_TVA_ION_FALLBACK=0` and must fail on corrupt pixels with `VaapiVideoDecoder`.
A stale-frame failure alone does not satisfy that control.

Host controls prove rejection of swapped channels, flipped images, repeated
frames, tampered references, wrong decoder/failure reasons, and unrelated startup
crashes. Launcher checks cover missing, unpatched and patched receipts; overrides
unset/0/1; hardware unset/off/on behavior; and caller-owned endpoints. These are
controlled launcher subprocesses, not a substitute for Bionilux ABI tests. Library
exclusion checks plant regular files and dangling symlinks for each forbidden name.

## Optional allocator and Cogl experiments

The [buffer probe](probe-android-buffers.c) compiles as Bionic with Termux Clang:

```sh
clang --target=aarch64-linux-android29 -O2 -Wall -Wextra \
  browsers/probe-android-buffers.c -landroid -o probe-android-buffers
./probe-android-buffers
```

The glibc-only [ION adapter](ion-dma-heap.c) is a diagnostic preload, not installed
by the product. Unpack Debian `libc6-dev-arm64-cross`, `linux-libc-dev-arm64-cross`
and `libva-dev` into one sysroot. The tested versions were 2.41-11cross1,
6.12.38-1cross1 and 2.22.0-3 respectively. On the phone:

```sh
bash browsers/build-ion-experiment.sh "$PWD/sysroot" "$PWD/ion-dma-heap.so"
```

Create `chrome-experimental` from the candidate launcher by removing only
`BIONILUX_EXTRA_PRELOAD` from its `unset` line and appending
`${LIVECD_TEST_EXTRA_PRELOAD:+:$LIVECD_TEST_EXTRA_PRELOAD}` to its hardware preload
assignment. This keeps the diagnostic library confined to glibc browser children.
`--ion-experiment --ion-shim /absolute/remote/ion-dma-heap.so` adds traced control
and ION-enabled VP9 cases, plus ION-enabled HEVC. The paired VP9 cases differ only
in `LIVECD_TVA_ION_FALLBACK=1`; both use `TERMUX_VA_CONTIGUOUS_DMABUF=1`.

The optional Cogl crash control needs an original library, matching Cogl typelib
pointed at that private library, and the GI redirect in `fullscreen-xshm-trace.c`.
Compile the typelib using `g-ir-compiler --includedir=RUNTIME/lib/mutter-16`.
Pass `--original-cogl /remote/private/libmutter-cogl-16.so` and
`--cogl-gi-preload /remote/gi-trace.so`. The suite accepts only an abort after a
fullscreen transition with `FULLSCREEN_INVALID_SHM_READ` in the log and the original
library mapped. An introspection startup abort is rejected.

Remaining qualification includes Firefox/direct/unmodified binary controls,
real-key fullscreen cycles, playback/fault injection, Bionilux's existing smoke
failures, clean installs/updates/uninstall, a two-hour soak, performance measurements,
and Android's actual display. Keep hardware decoding opt-in until those pass and
the user agrees to the displayed result.
