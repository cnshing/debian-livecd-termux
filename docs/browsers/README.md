# Firefox, Chromium, Google Chrome and ungoogled Chromium on native Termux

This is an **opt-in port** of the live CD's browsers and their extensions. Everything
runs in native Termux on Android, with no PRoot and no root. It adds menu entries to the
[native GNOME desktop](../native/README.md) and also works from a plain Termux shell on any
X display.

| Browser | Comes from | Runs on | uBlock | Password managers |
| --- | --- | --- | --- | --- |
| Firefox | Official Termux package | Bionic | uBlock Origin | Bitwarden, Proton Pass |
| Chromium | Debian's signed arm64 build, pinned; Termux's package stays as a fallback | Termux's glibc | uBlock Origin Lite | Bitwarden, Proton Pass |
| Google Chrome | Google's own arm64 `.deb` | Termux's glibc | uBlock Origin Lite | Bitwarden, Proton Pass |
| ungoogled Chromium | The project's arm64 portable release, pinned | Termux's glibc | uBlock Origin Lite | Bitwarden, Proton Pass |

**Read [Security](#security) before signing in to a password manager here.** None of these
browsers has a working sandbox on Android.

Chrome and both Chromium builds use the GPU without PRoot once the desktop's fullscreen fix is applied.
Termux's own Chromium package is built without VA-API, so it can never decode video in hardware. The
installer therefore adds Debian's Chromium and ungoogled-chromium's release, both built with VA-API,
pinned by hash in [`chromium-prebuilt.lock.json`](../../overlays/Browser+Chromium/browsers/chromium-prebuilt.lock.json).
Hardware video decoding is opt-in (see [GPU rendering and hardware video](native-gpu-and-video.md)); with it on,
`chrome://gpu` reports Video Decode as hardware accelerated, and VP9 and HEVC decode through VA-API.
H.264 and AV1 stay in software. Without the fullscreen fix they render in software, as described below.

## Install and update

Run from this checkout inside native Termux, with the official X11 repository enabled:

```sh
python src/apply-overlays.py "Browser+Chromium"                       # all four
bash overlays/Browser+Chromium/browsers/install.sh chromium chrome    # or a selection
```

To copy what it needs from a PC with the established [phone rig](../phone-test-rig.md):

```sh
tar -czf - src overlays/Browser overlays/Browser+Chromium |
    ssh termux 'mkdir -p ~/debian-livecd-termux; tar -xzf - -C ~/debian-livecd-termux'
```

Then run the commands from `~/debian-livecd-termux`. Google Chrome needs about 640 MB
including Termux's glibc, and Termux's Chromium about 700 MB. The pinned builds add about
460 MB for Chromium and 790 MB for ungoogled Chromium, plus a download cache in `~/.cache/livecd-browsers`.

The pinned Chromium builds run on the GPU and video libraries that the `chrome` step sets up,
so install `chrome` with them. Without it, `chromium` keeps Termux's build and
`ungoogled-chromium` refuses to install. The installer puts each build in its own immutable
directory under `$PREFIX/opt/livecd-browsers`, then switches the `chromium` or
`ungoogled-chromium` link to it, so a running copy keeps its files. It also makes the native
desktop's Chromium menu entry and `chromium-browser` start the VA-API build, and adds an
Ungoogled Chromium entry. Termux's build stays at `$PREFIX/bin/chromium-browser`.

**Rerun the installer to update Chrome.** Google's updater does not run here and APT does not
manage Chrome, so nothing else updates it, and a browser left unpatched is a real risk. The
installer refuses to run while Chrome is open. It takes the latest stable release from Google's
signed index, and keeps the old copy if the new one fails to start. The pinned Chromium builds
change only when the lock file does: rerun the installer after updating this checkout. Firefox
and Termux's Chromium update through `pkg upgrade`. Rerun the installer after upgrading Termux's Chromium, since the package
restores the broken menu entry described below. Each browser should update its extensions itself,
as on the live CD. That was seen for uBlock Origin in Firefox, and not tested for the others.

The installer checks with APT first. If the packages would upgrade an existing shared library,
it refuses to run while the desktop is up, the same rule the desktop's own setup follows. It
proceeds on a running desktop when it would only add packages.

## Run

Use the menu entries on the desktop, or from a terminal with `DISPLAY` set:

```sh
firefox
chromium-browser     # the VA-API build on the native desktop
google-chrome
ungoogled-chromium
```

On the native desktop each browser keeps its profile under `~/.config/livecd-native`, and
`livecd stop` closes it. Starting a browser for the first time opens the extensions' welcome
tabs, as on the live CD.

## How the extensions are installed

This is the live CD's process, using the same scripts:
[`install-chrome-extensions.sh`](../../overlays/Browser/lb/hooks/normal/scripts/install-chrome-extensions.sh)
and [`install-firefox-extensions.sh`](../../overlays/Browser/lb/hooks/normal/scripts/install-firefox-extensions.sh).
They gained one optional argument and now respect `$TMPDIR`, which doesn't change the image
build. The extension IDs are the ones in [`os/config.yaml`](https://github.com/cnshing/debian-livecd/blob/cd769287d6511b90d54ad7682416b201e4c44e2f/os/config.yaml).

| Browser | Live CD directory | Directory here |
| --- | --- | --- |
| Firefox | `/usr/share/mozilla/extensions/{ec8030f7-…}` | `$PREFIX/share/mozilla/extensions/{ec8030f7-…}` |
| Chromium | `/usr/share/chromium/extensions` | `$PREFIX/opt/livecd-browsers/chromium-extensions`; Termux's build: `$PREFIX/lib/chromium/extensions` |
| Google Chrome | `/opt/google/chrome/extensions` | `$PREFIX/opt/google/chrome/extensions` |
| ungoogled Chromium | Debian package | `$PREFIX/opt/livecd-browsers/ungoogled-chromium-extensions` |

Chromium reads these from an `extensions` directory beside its binary. Each pinned build's
directory links there, so the extensions survive an update to a new build.

These apply to every profile. Firefox also needs two settings, written to
`$PREFIX/lib/firefox/browser/defaults/preferences/livecd-extensions.js`. `extensions.autoDisableScopes` takes
Debian's value, because upstream's default leaves these add-ons disabled behind a prompt.
`extensions.startupScanScopes` makes Firefox check this directory at each start, because
upstream only does so for a new profile or a Firefox upgrade. To remove an extension, delete
its `<id>.crx` and `<id>.json`, or `<id>.xpi`, then remove it in the browser.

Both Chromium builds use uBlock Origin Lite because Google's update server no longer offers
full uBlock Origin at this version: it answers `204`, nothing to install. The live CD's
ungoogled-chromium gets the full extension from a Debian package instead.

The native desktop's setup also places a pinned uBlock Origin in its private Firefox profile.
Firefox loads that copy for that profile, in place of the system one.

## How Google Chrome runs here

Android's programs use Bionic, Android's C library. Google builds Chrome for glibc, so **no
Bionic Google Chrome exists**, and copying it into Termux would normally fail. Termux's official
[glibc repository](https://github.com/termux-pacman/glibc-packages) supplies a glibc built for
Android. Chrome runs directly on that as a normal process, which is not emulation or PRoot.

The installer does the following:

1. Checks `Release` against the key in [`google-chrome.yaml`](../../overlays/Browser/repos/google-chrome.yaml),
   the one the live CD trusts, then follows SHA-256 hashes to the `.deb`.
2. Installs the libraries Chrome needs from [`chrome-libs.lock.json`](../../overlays/Browser+Chromium/browsers/chrome-libs.lock.json):
   104 Debian trixie arm64 packages, hash-pinned by [`lock-chrome-libs.py`](../../tools/lock-chrome-libs.py) from
   Debian's signed indexes. Termux's glibc repository has no NSS, ATK, CUPS, udev or GTK3. Only
   shared libraries are taken, into Chrome's own `lib` directory, and these are not APT packages.
3. Points `chrome` and its crash handler at Termux's loader with `patchelf`, and its libraries at
   each other with `DT_RUNPATH`.
4. Starts the result with `--version` before replacing anything.

**Keep Debian's libraries patched too.** The lock pins them, including NSS, and a rerun does not
refresh them. Run `lock-chrome-libs.py` on a Debian PC to update it, then rerun the installer.

[`google-chrome`](../../overlays/Browser+Chromium/browsers/google-chrome), the launcher, handles what differs from a Linux PC:

| Android differs by | So the launcher or installer |
| --- | --- |
| Termux's preload library and the desktop's library path are Bionic's | Clears both, and uses `DT_RUNPATH` so nothing leaks into programs Chrome starts |
| No `/dev/shm` | Passes `--disable-dev-shm-usage` |
| No `/tmp/.X11-unix` | Gives `DISPLAY` as a full socket path, which libxcb accepts |
| No `/etc/fonts`, and XKB data lives under `$PREFIX` | Sets `FONTCONFIG_FILE`, `XKB_CONFIG_ROOT` and `XLOCALEDIR` |
| No `/etc/resolv.conf`, and glibc can't ask Android's resolver | Links glibc's to Termux's `$PREFIX/etc/resolv.conf` and `hosts` |
| Bionilux or the desktop's fullscreen fix is missing | Passes `--disable-gpu`. Otherwise it [uses the GPU](native-gpu-and-video.md) |
| Chrome overwrites its `/proc/PID/environ` | Stays running as Chrome's parent, so that `livecd stop` can still find and stop it |

### Why not krypton-byte/chrome-termux

That project's tarball is not Google Chrome. Inspected statically and never run, it is a Bionic
**Chromium 109.0.5414.74** from January 2023, renamed `chrome`, more than three years behind on
security fixes, with an install link its own issue tracker reports as dead. Official Termux now
packages current Chromium. Its useful lessons are the Bionic build's shape and its `extensions/`
directory beside the binary, which is where Chromium looks here too.

Chromium's package also has a bug the installer repairs. Its menu entry still contains
placeholders such as `@@desktop_exec`, so GLib rejects the file and Chromium is absent from
the menu. The recipe substitutes names that upstream's template no longer uses.

## Security

**No browser here has a sandbox.** A web page that exploits a browser bug can reach everything
in the Termux app: SSH keys, this repository, and browser data. The Android app sandbox still
separates Termux from other apps.

| Browser | State on this phone | Why |
| --- | --- | --- |
| Firefox | Built without one (`MOZ_SANDBOX` is off) | Termux's build choice |
| Chromium, both builds | "You are NOT adequately sandboxed" | Termux's recipe documents it as unresolved; the glibc builds run like Chrome |
| ungoogled Chromium | "You are NOT adequately sandboxed" | As for Chrome |
| Google Chrome | "You are NOT adequately sandboxed" | No setuid helper and no user namespaces on Android |

**GPU rendering widens this.** It lets page content reach Mesa's shader compilers and the phone's GPU
kernel driver, in a browser with no sandbox. This is the same kind of risk that keeps
`--enable-unsafe-swiftshader` off by default. To keep the smaller exposure, set
`LIVECD_CHROME_GPU=0`, `LIVECD_CHROMIUM_GPU=0` and `LIVECD_UNGOOGLED_CHROMIUM_GPU=0`.

On a PC this same exploit would have to escape a sandbox first. So the practical advice is:

- Don't treat these as equal to the live CD's browsers for your most sensitive accounts.
- A password manager here means a page exploit could reach an unlocked vault. Use a short
  vault timeout, or leave the vault on a device whose browser is sandboxed.
- Keep all of them updated, which matters more here. uBlock also reduces exposure to hostile ads.

Chrome's "unsupported command-line flag: --no-sandbox" banner is accurate, and it is left visible.

Two smaller points:

- **DNS:** Chrome uses Termux's `resolv.conf`, which by default names Google's public servers
  (`8.8.8.8`, `8.8.4.4`), and not your network's or Android's Private DNS. Edit that file to
  change it, though it also affects other programs that read it. Firefox and Chromium use
  Bionic's resolver, which follows Android's network settings.
- **Google's terms:** Chrome is downloaded from Google on your phone. Don't redistribute that
  directory or the `.deb`.

## Limits

- **Software rendering in Chrome until the fix is applied.** WebGL is off in that mode.
  `google-chrome --enable-unsafe-swiftshader` turned it on in testing, but it runs a shader compiler on
  untrusted page content with no sandbox, hence the flag's name, so it is not the default.
- **Sign-in and sync are untested.** No account was signed in to any browser or extension.
- **Chrome reports Linux x86_64 in its user agent**, as Chrome on any Linux does.
- Widevine reports as available in Chrome, which only shows that the key system was granted.
  Playing DRM video was not tested.
- **Firefox's dock icon needs a local desktop entry.** The package's window class and its desktop entry
  disagree, so the native desktop's `Browser` overlay supplies a corrected one. See [Icons](../native/README.md#icons).

No separate verification report was kept for this port. The device test is
[`test-browsers.py`](../../tests/browsers/test-browsers.py).

## Test

[GPU rendering and hardware video](native-gpu-and-video.md) has the results for the native GPU path
and how to repeat them. The earlier [source check and PRoot attempt](chrome-native-source-and-proot.md)
records why a rebuild of Google's Chrome is not possible. Its PRoot launcher was never needed.

For fullscreen playback that exits GNOME Shell, see the
[isolated crash investigation](fullscreen-investigation.md). It found an out-of-bounds Cogl pixmap read
on Mutter 48.8, fixed by the source port's patch 0010.

The harness drives each browser on a fresh profile through its own debugging protocol. It
doesn't sign in to anything, and it plays a short tone if PulseAudio is available.

```sh
# On the native desktop: includes the file dialog and audio.
livecd-native exec -- python tests/browsers/test-browsers.py chrome

# On a private display, away from a desktop in use. A display without a window manager
# skips the file dialog, and one without PULSE_SERVER skips audio.
pkg install xorg-server-xvfb openbox
Xvfb :17 -screen 0 1280x800x24 -nolisten tcp &
DISPLAY=:17 openbox &
DISPLAY=:17 dbus-run-session -- python tests/browsers/test-browsers.py chrome
```

Results and screenshots go to `~/.local/state/livecd-browsers/test`. A browser's extensions come
from its system directory, so Firefox needs `install.sh` to have run first. To try Firefox
without changing what other profiles load, pass `--xpi-dir` with a directory of XPIs.

## Remove

```sh
rm -rf "$PREFIX/opt/google" "$PREFIX/bin/google-chrome" "$PREFIX/bin/google-chrome-stable" \
    "$PREFIX/share/applications/google-chrome.desktop" "$PREFIX"/share/icons/hicolor/*/apps/google-chrome.png \
    "$PREFIX/lib/chromium/extensions" "$PREFIX/share/mozilla/extensions/{ec8030f7-c20a-464f-9b0e-13a3a9e97384}" \
    "$PREFIX/lib/firefox/browser/defaults/preferences/livecd-extensions.js" "$HOME/.cache/livecd-browsers" \
    "$PREFIX/bin/bionilux" "$PREFIX/glibc/lib/libbionilux_preload.so" "$PREFIX/bin/termux-va" "$PREFIX/bin/tva-probe" \
    "$PREFIX/bin/termux-va-start" "$PREFIX/bin/termux-va-stop" "$PREFIX/etc/chromium/livecd-gpu.conf" \
    "$HOME/.local/lib/livecd/hardware-video.pem" "$PREFIX/opt/livecd-browsers" \
    "$PREFIX/bin/chromium-vaapi" "$PREFIX/bin/ungoogled-chromium" "$HOME/.local/lib/livecd-native/bin/chromium-browser" \
    "$HOME"/.local/share/{,livecd-native/}applications/{chromium,ungoogled-chromium}.desktop
apt-get remove chromium glibc glibc-repo
```

Profiles stay behind under `~/.config/livecd-native`, or `~/.config` and `~/.mozilla` outside the
desktop. Remove `$PREFIX/glibc/etc/resolv.conf`, `hosts` and `nsswitch.conf` if you keep glibc
for something else and don't want these settings.
