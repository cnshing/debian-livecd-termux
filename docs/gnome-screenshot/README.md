# GNOME Screenshot

The default Desktop Environment+Shell overlay installs `gnome-screenshot`, matching
upstream debian-livecd's delayed screenshot utility. Launch **Screenshot** from the
application menu, choose the whole screen, a window or an area, then take the shot.
The overlay defaults to a three-second delay in the interactive dialog, PNG files
and no mouse pointer. The dialog remembers subsequent user choices through dconf.
The usual Pictures directory is the upstream save location.

For a delayed capture from a terminal in the desktop session:

```sh
gnome-screenshot --delay=3 --file="$HOME/Pictures/screenshot.png"
```

The command-line delay is explicit; the saved delay setting applies to interactive
mode. GNOME Shell's own screenshot UI remains available.

The recipe derives from Termux's pinned `x11-packages/gnome-screenshot` recipe;
`packages/gnome-screenshot/upstream.json` verifies its provenance. Builder staging
retains Termux's `0001-remove-extraneous-positional-argument.patch`, required by
modern Meson. The source archive is checksum verified, with X11 support enabled
for Termux:X11. GNOME Shell's screenshot service supplies compositor captures.

Build this package alone with:

```sh
bash tools/build-packages.sh gnome-screenshot
gh workflow run packages.yml --ref feat/gnome-screenshot -f packages=gnome-screenshot -f rebuild=true
```

On native Termux, `bash tools/build-packages.sh --install gnome-screenshot` builds
and installs through APT. The normal installer also installs it through the default
Shell overlay. Apply overlays with the managed desktop stopped.

With the native desktop running, verify the installed launcher and real delayed
screen/window captures with `python tests/native/test-screenshot.py`. The test
opens a temporary GTK window and removes its captures afterwards.

## Verification

Verified November 3, 2026:

- [Isolated GitHub Actions run 41776417785](https://github.com/cnshing/debian-livecd-termux/actions/runs/41776417785)
  passed planning, the `gnome-screenshot` build and repository assembly, with
  `packages=gnome-screenshot` and `rebuild=true`.
- Installed that run's `gnome-screenshot_41.0_aarch64.deb` through APT on the
  native arm64 Android phone.
- `tests/native/test-screenshot.py` passed with the Zink GNOME session:
  delayed full-screen PNG 1280×1024 in 4.76 seconds (requested delay: three
  seconds), active-window PNG 456×395 in 0.38 seconds. Both decoded and contained
  nonblank image data.
- `gtk-launch org.gnome.Screenshot` opened a visible Screenshot dialog.
- Session `gsettings` reads confirmed delay `3`, file type `'png'` and pointer
  inclusion `false`. All 12 host packaging checks passed.

The screenshots cover the Termux:X11 desktop, rather than Android's system UI.
