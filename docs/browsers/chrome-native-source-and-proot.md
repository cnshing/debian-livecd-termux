# Native Chrome source check and PRoot fallback attempt

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> **Superseded for GPU work.** The conclusions below about descriptor violations are wrong: those
> came from `--disable-crashpad-for-testing`, and libpci's `exit(1)` was what killed the GPU process.
> Chrome now uses the GPU natively, without PRoot. See
> [GPU rendering and hardware video](native-gpu-and-video.md). The source-access findings still stand.

Investigated in the requested order. **Neither attempt produced
a usable GPU-accelerated Google Chrome.** No default browser launcher, desktop
backend, installed graphics library or guest package was changed.

## Native source route

Google Chrome's publicly available base is Chromium. A Bionic desktop port of
that code already exists: the phone has Termux Chromium 156.0.8078.47, whose ELF
interpreter is Android's `/system/bin/linker64`.

The source-access preflight checked Chromium tag **156.0.8078.79**, commit
`a21ce95c24ce3964416f09ae1862f53f319eb4d0`. Its
[`chrome_build.gni`](https://chromium.googlesource.com/chromium/src/+/a21ce95c24ce3964416f09ae1862f53f319eb4d0/build/config/chrome_build.gni)
states that official Chrome branding requires extra Google-internal resources.
Its [`DEPS`](https://chromium.googlesource.com/chromium/src/+/a21ce95c24ce3964416f09ae1862f53f319eb4d0/DEPS)
references `https://chrome-internal.googlesource.com/chrome/src-internal.git`.
An unauthenticated fetch of that repository returned **HTTP 401 Unauthorized**.
Google also distinguishes its own distribution and added API keys from the
public Chromium build in its
[Chrome/Chromium comparison](https://chromium.googlesource.com/chromium/src/+/main/docs/chromium_browser_vs_google_chrome.md).

Consequently, a public-source Bionic rebuild would be a Chromium build, rather
than a reproduction of Google's Chrome distribution. This is a source-access
blocker before compilation. **No complete browser compilation was run, and no
Bionic compiler failure is claimed.**

The existing native port is substantial, but it demonstrates that Bionic itself
is feasible. The
[Termux Chromium recipe](https://github.com/termux/termux-packages/blob/538685c906074926fd19650e38c6dad91379eb0f/x11-packages/chromium/build.sh)
at this repository's pinned Termux commit targets version 156.0.8078.73, uses
the Android NDK sysroot and a cross-build toolchain, and applies **76 files** from
its `chromium-host-tools/cr-patches` directory, plus jumbo/build-tool patches.
It explicitly does not support on-device builds. `is_official_build=true` in
that recipe selects a build configuration; it does not supply Google's private
branding or distribution components.

A fresh full Chromium build also exceeds this PC's current free disk capacity:
37 GiB were available, while the upstream
[Linux build instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/build_instructions.md)
specify at least 100 GB free. The PC had about 0.6 GiB of available RAM while
other agents were working. These are capacity limits for this session, not
evidence that a Chromium/Bionic build is impossible elsewhere.

Source preflight evidence (`temp/docs/evidence/browsers/chrome-source/preflight.txt`)
and pinned revisions (`temp/docs/evidence/browsers/chrome-source/source-audit.json`).

## Chrome-only PRoot fallback

After the source-access check, the trial extracted the cached, unmodified Google
Chrome arm64 package to `~/.cache/livecd-chrome-proot/root`. It did not install a
second desktop or modify APT/dpkg state. The archive is:

```text
google-chrome-stable_156.0.8078.79-1_arm64.deb
SHA-256 dc66f2d96853153e350c4a0944da4503cae39c2fcbcdb4e0057c64f6c49202ff
```

Chrome runs in the existing Debian guest as `desktop`, with only its application
directory bound at `/opt/livecd-chrome`. It uses the existing glibc Mesa
27.0.0-devel-20261025 KGSL/Turnip/Zink stack. GNOME Shell remains a native Bionic
process, on a fresh Xvfb display and private session bus/profile for each run.
The previously tested Cogl clipping candidate is selected only for that private
shell, so the earlier fullscreen compositor bug does not confound this test.

The unmodified binary's `--version` command succeeds in PRoot. A software-rendering
control also opened a real page and completed a fullscreen entry/exit cycle.
**GPU-enabled trials failed before completing even the canvas acceptance case.**

| Trial | Observed result |
| --- | --- |
| ANGLE/OpenGL over Zink | GPU process repeatedly exits, then Chrome terminates |
| Disable zygote / GPU sandbox | Same GPU startup failure |
| ANGLE/Vulkan using Turnip directly | Explicit descriptor ownership violations in GPU and network subprocesses |
| Disable PRoot's SysV IPC shim and Xvfb MIT-SHM | Same descriptor ownership failure |
| Single-process browser and in-process GPU | Browser exits before DevTools is available |
| Software-rendering control | Canvas fullscreen cycle passes; this does not demonstrate acceleration |

With `--disable-crashpad-for-testing`, the GPU-enabled log exposes:

```text
Crashing due to FD ownership violation:
...
GPU process has crashed 6 time(s)
GPU process isn't usable. Goodbye.
```

This matches a
[PRoot maintainer's Chromium compatibility report](https://github.com/termux/proot/issues/404).
The relevant Chromium
[descriptor tracking code](https://chromium.googlesource.com/chromium/src/+/a21ce95c24ce3964416f09ae1862f53f319eb4d0/base/files/scoped_file_linux.cc)
and its unconditional activation in
[`content_main.cc`](https://chromium.googlesource.com/chromium/src/+/a21ce95c24ce3964416f09ae1862f53f319eb4d0/content/app/content_main.cc)
were inspected. No binary patch or descriptor-enforcement bypass was applied.
The particular descriptor/operation that causes the violation was not identified.

Xvfb also lacks DRI3. The trials tested Mesa's `LIBGL_KOPPER_DRI2=1` and
`LIBGL_KOPPER_DISABLE=true` copy-based presentation path. A glibc `glxinfo` probe
reported accelerated Turnip with the DRI2 option, but enumeration is insufficient
to establish that Chrome can render. The harness therefore checks Chrome's
post-rendering GPU status, requiring both a Turnip renderer and enabled GPU
compositing. No GPU trial reached that acceptance condition.

As an additional check after PRoot failed, a temporary launcher supplied the
same glibc graphics libraries directly to the existing Termux-glibc Chrome,
without entering PRoot. That also failed, including descriptor ownership errors.
An in-process GPU variant exited during initialization. These controls mean the
observations do not isolate every failure to PRoot itself; swapping a loader or
adding graphics libraries was insufficient in this session.

Trial results and output directories (`temp/docs/evidence/browsers/chrome-proot/runs.json`),
Vulkan failure log (`temp/docs/evidence/browsers/chrome-proot/proot-gpu-vulkan/browser.log`),
and software control (`temp/docs/evidence/browsers/chrome-proot/proot-software-control/result.json`).

## Reproduce the diagnostic

The trial launcher (`tests/browsers/chrome-proot-trial`, since removed with the PRoot
profile) required the existing
Debian guest, its `desktop` user and the optional glibc GPU stack described above.
It is a diagnostic, not a working accelerated launcher, and is not installed in
the application menu. It does not upgrade or install guest packages.

From an ordinary native Termux shell, with the original cached Google package:

```sh
# Extract only into the trial directory. Omit if already prepared.
tests/browsers/chrome-proot-trial --prepare

LIVECD_CHROME_PROOT_SYSVIPC=disabled python tests/browsers/test-fullscreen.py chrome \
  --browser-command "$PWD/tests/browsers/chrome-proot-trial" \
  --disable-shm --cycles 3 --require-gpu \
  --browser-flag=--use-gl=angle --browser-flag=--use-angle=gl-egl \
  --browser-flag=--disable-crashpad-for-testing
```

The recorded trial additionally selected the previous investigation's private
Cogl candidate with `--shell-lib-dir` and `--shell-preload`; see the
[fullscreen investigation](fullscreen-investigation.md#repeat-safely) for that
setup. It is not installed into the active desktop. The default harness now
starts Xvfb itself with software GLX support while independently selecting the
shell's requested renderer, so Xvfb's own graphics configuration does not hide
the client-side test.

For the control, omit `--require-gpu` and the two GL flags, and pass
`--browser-flag=--disable-gpu`. No existing browser profile is used. Logs and
result JSON go into the printed scratch output directory. The harness now
detects a dead browser launcher during startup rather than waiting the entire
DevTools timeout, and records custom launcher arguments.

## Remaining work

The requested native-first source check and Chrome-only PRoot experiment were
performed, but a usable accelerated Google Chrome has not been delivered.
Public-source work can target the existing Bionic Chromium port. Further Google
Chrome fallback work needs the actual descriptor conflict and initialization
failures resolved, followed by real rendering, playback and fullscreen tests.
The earlier successful software-browser/Cogl results do not establish GPU Chrome
support. Existing browser and desktop launchers were left in place.

The final checked-in launcher passed the
software control (`temp/docs/evidence/browsers/chrome-proot/final-software-control/result.json`).
The updated harness still detected the original native
fullscreen shell crash (`temp/docs/evidence/browsers/chrome-proot/native-crash-control/result.json`).
The cleanup check (`temp/docs/evidence/browsers/chrome-proot/final-state.json`) found no
surviving test processes or test display sockets, and the installed Cogl library
retained its original checksum.
