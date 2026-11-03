# GNOME 48 package inputs

The source versions and retained patches come from the independently tested
native GNOME 48 source port. That work area has since been removed from the repository.

The matching components are packaged separately as `livecd-mozjs-128`,
`livecd-gjs`, `livecd-mutter` and `livecd-gnome-shell`. Their `build.sh` metadata
pins the source URL and SHA-256. They install under `$TERMUX_PREFIX/opt/gnome-48`
and use Termux's toolchain, Rust/Meson setup, patch expansion, license handling
and package generation. No GNOME-Termux executable or generated typelib is an
input. `record.py` writes source receipts used by diagnostics and GPU selection.

The readable `gir/*.xml` introspection dumps are retained from Termux's GNOME 48
recipes at `77ae9db667103a2ea7575c8f23a497754796951a`, as staged by the source
port. Termux's `termux_setup_gir` uses them when cross-building;
native builds use the target's introspection tooling. Source patches retain
their upstream licenses and explanatory headers.

`livecd-gnome-runtime` supplies the session and readable schemas required from
GNOME Settings Daemon and LocalSearch. `livecd-gnome-data` packages the pinned
portable Debian font/extension assets and their attributions, with Noto fonts
split into `livecd-gnome-extra-fonts`. It excludes ELF payloads and maintainer
scripts. This preserves the tested profile data without importing a binary
GNOME runtime. It is not a rebuild of each font or extension's original sources.

The new package build and installation path needs complete Termux builds and
fresh device acceptance. The original source port's device results are not a
claim that these cross-compiling recipes have passed that acceptance.
