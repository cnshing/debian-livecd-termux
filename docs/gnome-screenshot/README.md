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
