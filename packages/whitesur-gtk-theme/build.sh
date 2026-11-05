TERMUX_PKG_HOMEPAGE=https://github.com/vinceliuice/WhiteSur-gtk-theme
TERMUX_PKG_DESCRIPTION="MacOS Big Sur like GTK and GNOME Shell theme, with its installer for further variants"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2026.09.11"
TERMUX_PKG_SRCURL=https://codeload.github.com/vinceliuice/WhiteSur-gtk-theme/tar.gz/d5782652d412137e26fb8ff55b55a5572e4c6995
TERMUX_PKG_SHA256=9d8be3dca76f7be36dfb6513aa2c301be1ff265a9c1c4c1006b5ed0f89df29f1
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
# What install.sh needs to build accent, Monterey or Nord variants on the phone.
TERMUX_PKG_RECOMMENDS="glib, librsvg, sassc"
TERMUX_PKG_SUGGESTS="gtk2-engines-murrine"

termux_step_make_install() {
	# Upstream's prebuilt release variants: Light and Dark, standard and solid, default and Nord.
	local archive
	install -d "$TERMUX_PREFIX/share/themes"
	for archive in release/*.tar.xz; do
		tar -xJf "$archive" -C "$TERMUX_PREFIX/share/themes"
	done
	# The installer and its sources, patched for Termux. Copy them before running install.sh,
	# which writes temporary files beside itself.
	install -d "$TERMUX_PREFIX/share/whitesur-gtk-theme"
	tar --exclude=./release --exclude=./.github --exclude=./.gitignore -c . |
		tar -x -C "$TERMUX_PREFIX/share/whitesur-gtk-theme"
}
