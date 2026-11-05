# GPU rendering and hardware video without PRoot

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

Tested on the Note10+ (SM-N975U1, Android 11, Adreno 640).

**Shared integration applied:** GPU/video support now has an
[ABI-aware application layer](../native/ACCELERATION.md), a built private Bionic
VA-API driver, a shared glibc stack, and an independent MediaCodec service.
Firefox and mpv have launch profiles; stock Chromium still needs the new
VA-API-enabled package build. The later authorized
Firefox/mpv checks (`temp/docs/evidence/browsers/native-gpu-video/`)
started both applications: Firefox used software VP9 decoding; mpv selected
MediaCodec/GPU output but lacked test log evidence identifying the hardware codec.
Neither passed hardware validation. Existing live applications were not restarted.
Build and installation evidence (`temp/docs/evidence/browsers/native-gpu-video/`)
records what was applied. The results below describe the earlier Chrome work.

**This is experimental.** Google Chrome and Chromium render on the GPU natively, without PRoot.
The user requested application of the tested ION adapter on this phone, so Chrome now has a persistent
opt-in for VP9/HEVC hardware decoding. H.264 and AV1 remain in software. Fresh installations still default
to software video. The [test instructions](../../tests/browsers/README-native-video.md) describe the remaining qualification.

The [continuation investigation](android-video-allocators.md) found that unprivileged
ION allocation works through a read-only FD. A private adapter produces a shared NV12
dma-buf and passes VP9/HEVC pixel comparisons at both browser and GNOME compositor layers.
Native FFmpeg also passes VP9/H.264/HEVC decoding checks through NDK MediaCodec.
The adapter was explicitly applied to this phone; the general installer does not install it.
[New test instructions](../../tests/browsers/README-native-video.md)
describe the current coverage and remaining qualification.

The application follow-up (`temp/docs/evidence/browsers/native-gpu-video/`)
passes the installed HEVC case, but fullscreen compositor captures can retain an
older frame in VP9 and software-control tests. Those checks remain failures.
The user's fullscreen picture appeared normal in an Android screenshot; their
Chrome instance still predated application, so live hardware decoding awaits a
complete Chrome exit and relaunch.

| Browser | Rendering | Video |
| --- | --- | --- |
| Google Chrome | Vulkan, glibc Turnip | VP9/HEVC hardware on the opted-in phone with the ION adapter; H.264/AV1 software |
| Chromium | Vulkan, Bionic Turnip | Software. Termux's build has VA-API compiled out |
| Firefox | Unchanged | Unchanged |

## Turning it on

Both browsers stay on software rendering until the fullscreen fix is in the desktop's runtime. Do this with the
desktop stopped, from the Termux app and not a terminal inside the desktop:

```sh
~/.local/bin/livecd stop
~/.local/bin/livecd-apply-cogl-fix apply
~/.local/bin/livecd start
```

To undo it, stop the desktop and run `livecd-apply-cogl-fix rollback`. The launchers check the runtime's build
receipt for the fix because, without it, this path crashed GNOME Shell (`temp/docs/evidence/browsers/native-gpu-video/g3-orig-gpu-va/result.json`)
on the first fullscreen exit. `LIVECD_CHROME_GPU` and `LIVECD_CHROMIUM_GPU` override the check: `0` forces
software, and `1` skips it, which on an unpatched desktop risks that crash.

The ION adapter is installed separately at
`$PREFIX/libexec/livecd-browser/liblivecd_tva_ion-bf39f8bd.so`, matching the binary
from the passing private tests. The phone's
`~/.config/livecd-native/chrome-hardware-video` contains `1`, which the launcher
reads independently of the desktop's XDG profile. Fully quit and reopen Chrome to
use it; no desktop restart is needed. An explicit
`LIVECD_CHROME_HARDWARE_VIDEO=0 google-chrome` overrides that file. A missing adapter
keeps video on software rather than selecting the known wrong-color path.

## Check it yourself

| Where in Chrome | Software | GPU, as now |
| --- | --- | --- |
| `chrome://gpu`, Compositing | Software only | Hardware accelerated |
| `chrome://gpu`, `GL_RENDERER` | Disabled | Includes Turnip Adreno 640 |
| F12, ⋮, More tools, Media, then select the player | A software decoder | `VaapiVideoDecoder` for opted-in VP9/HEVC; software for H.264/AV1 |

Video should look normal. A green and purple picture with shifted copies is a failure of the shared-buffer path.

## What runs

| Part | Comes from | Role |
| --- | --- | --- |
| [Bionilux](https://github.com/theonuverse/bionilux) `4152b47`, [patched](../../overlays/Browser+Chromium/browsers/bionilux-0.5.0-browser.patch) | Built on the phone | Starts glibc Chrome and every glibc child, and keeps glibc's libraries away from Bionic programs |
| [Mesa for Android Container](https://github.com/lfdevs/mesa-for-android-container) 27.0.0-devel-20261025 | Hash-pinned archive | glibc Turnip for Vulkan |
| [19 Debian libraries](../../overlays/Browser+Chromium/browsers/chrome-gpu-libs.lock.json) | Hash-pinned, signed index | What that Mesa needs beyond Chrome's own libraries |
| [Mutter patch 0010](../../packages/gnome-48-mutter/0010-clip-pixmap-damage.patch) | This repository | The [fullscreen crash](fullscreen-investigation.md) fix |
| [Termux:VA](https://github.com/lfdevs/termux-va) `ae14813` | Built on the phone | Opt-in hardware video only: daemon that owns Android's MediaCodec |
| ION adapter `bf39f8bd…` | Explicitly applied tested glibc binary | Supplies a shared NV12 dma-buf through ION when `/dev/dma_heap/system` is absent |
| [Hardware video extension](../../overlays/Browser+Chromium/browsers/hardware-video/) | This repository | Tells YouTube AV1 is unavailable. Meant for hardware video, but stays installed |

[`install.sh chrome`](../../overlays/Browser+Chromium/browsers/install.sh) sets this up through
[`install-native-video.py`](../../overlays/Browser+Chromium/browsers/install-native-video.py), about 193 MB plus
the small programs. Only that second script has been run, on a phone that already had Chrome. The Bionilux command also
works for other glibc programs: `bionilux ./program`. It is explicit, and nothing is preloaded globally.

## Earlier results, before the ION adapter

| Case | Result | Evidence |
| --- | --- | --- |
| Chrome default, on the live `:0` | GPU compositing with Turnip, reported by `chrome://gpu` | Report (`temp/docs/evidence/browsers/native-gpu-video/live-about-gpu.txt`), before the first fix |
| Chrome default, color bars, private display | Correct colors, 6/6 fullscreen transitions, a process holds the GPU | Run (`temp/docs/evidence/browsers/native-gpu-video/f1-default-bars/result.json`) |
| Chrome default, YouTube, private display | Picture viewed and correct, 6/6 transitions, software AV1 | Screenshot (`temp/docs/evidence/browsers/native-gpu-video/f3-default-youtube/youtube-shell.png`) |
| Chromium, YouTube, private display | Picture viewed and correct, 12/12 transitions, software AV1 | Screenshot (`temp/docs/evidence/browsers/native-gpu-video/e5-chromium-youtube/youtube-shell.png`) |
| Chrome opt-in hardware video | **Fails:** red bar shows as 0, 103, 0 | Run (`temp/docs/evidence/browsers/native-gpu-video/f2-optin-bars-expect-fail/result.json`) |

**Treat this as lightly tested.** The default path has few runs, and only one of them compares pixels automatically.
Not tested: the first fix on the live display, long sessions, high resolutions, DRM video, and a clean install.

**The earlier runs under the evidence directory (`temp/docs/evidence/browsers/native-gpu-video`) named `e2`, `e3`, `g4`, `b1`, `b2` and
`yt*`** show that hardware decoding runs and that fullscreen survives. They did not check the picture, and
one saved screenshot (`temp/docs/evidence/browsers/native-gpu-video/e2-youtube/youtube-shell.png`) plainly shows the color bug.

## What was actually wrong before

The [earlier report](chrome-native-source-and-proot.md) blamed descriptor ownership violations and treated them as a
likely PRoot or glibc incompatibility. Changing one thing at a time showed otherwise:

| libpci | `--disable-crashpad-for-testing` | Result |
| --- | --- | --- |
| Debian's (`temp/docs/evidence/browsers/native-gpu-video/a-baseline-realpci-crashpadon/result.json`) | Absent | GPU process exits 6 times, browser dies, 0 violations |
| Empty stub (`temp/docs/evidence/browsers/native-gpu-video/b-stubpci-crashpadon/result.json`) | Absent | GPU process survives on Turnip, 0 violations |
| Empty stub (`temp/docs/evidence/browsers/native-gpu-video/c-stubpci-crashpadoff/result.json`) | Present | GPU process survives, 53 violations |
| Software control (`temp/docs/evidence/browsers/native-gpu-video/e-software-crashpadoff/result.json`) | Present | Page works, 83 violations |

1. **The violations came from our own diagnostic flag.** They appear with it and never without it.
2. **`libpci` was killing the GPU process.** ANGLE loads `libpci.so.3` if it can find one. On Android `/proc/bus/pci` is
   denied, and libpci's default error handler calls `exit(1)`. Only the Debian guest has this library. The GPU stack
   here does not contain it, and the installer refuses to install it.
3. **Xvfb has no DRI3,** so presentation could not work on it. Tests now use a
   [private Termux:X11 server](../../tests/browsers/private-lorie/README.md), which cannot reach Android's screen.

## Other changes

- **Bionilux** re-executed itself when Chrome ran `/proc/self/exe`, which took down the network service. It also dropped
  other preloads for child processes, and passed `LD_LIBRARY_PATH` to Bionic programs. [The patch](../../overlays/Browser+Chromium/browsers/bionilux-0.5.0-browser.patch)
  fixes the first, and adds `BIONILUX_LIBRARY_PATH` and `BIONILUX_EXTRA_PRELOAD`, which reach glibc programs only. A Bionic
  child of a glibc program was seen to get neither variable, and ran normally.
- **Vulkan, not GLES.** Termux:VA's documented `--use-angle=gles-egl` recipe
  left fullscreen by itself (`temp/docs/evidence/browsers/native-gpu-video/f2-canvas-kgsl/result.json`), even on a plain canvas.

## Limits

- **Security:** see the [browsers page](README.md#security). GPU rendering exposes more driver code to web pages.
- **Hardware video has more problems beyond the colors.** One H.264 clip stops at frame 31 every time (`temp/docs/evidence/browsers/native-gpu-video/h264-b3.mp4/browser.log`),
  and if the daemon dies the video stops with a decode error (`temp/docs/evidence/browsers/native-gpu-video/e4-daemon-killed/result.json`).
- Termux:VA and this Mesa are young projects with one maintainer, and this Mesa is a development snapshot.
- [`test-browsers.py chrome`](../../tests/browsers/test-browsers.py) times out navigating to `example.com`. **The original launcher
  fails the same way,** so this work did not cause it. Details (`temp/docs/evidence/browsers/native-gpu-video/other-checks.txt`).

## Repeat the tests

The [regression guide](../../tests/browsers/README-native-video.md#host-checks-and-fixtures) explains fixture generation and test commands.
`--window-size` larger than the screen makes the window fill the work area, the geometry that crashes. Without it the original
library also passed, as did a software-rendered canvas with it (`temp/docs/evidence/browsers/native-gpu-video/g1-orig-sw/result.json`), although
that crashes on Xvfb. So a pass with the original library is not evidence of safety on any display.
