TERMUX_PKG_HOMEPAGE=https://unifoundry.com/unifont/
TERMUX_PKG_DESCRIPTION="GNU Unifont, a bitmap font covering the Unicode Basic Multilingual Plane (Debian fonts-unifont)"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/fonts-unifont/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="15.1.01"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/u/unifont/fonts-unifont_15.1.01-1_all.deb
TERMUX_PKG_SHA256=867d447c9b4b139a13c07d27b4f48df4d22e1ef21d29ff5e468a796fd9f2c635
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="fontconfig"
# Formerly bundled in livecd-gnome-data.
TERMUX_PKG_CONFLICTS="livecd-gnome-data, livecd-gnome-extra-fonts"
TERMUX_PKG_REPLACES="livecd-gnome-data, livecd-gnome-extra-fonts"

# Debian's architecture-independent package, which holds only fonts, JavaScript and data.
termux_step_post_get_source() {
	local archive="$TERMUX_PKG_CACHEDIR/$(basename "$TERMUX_PKG_SRCURL")"
	termux_download "$TERMUX_PKG_SRCURL" "$archive" "$TERMUX_PKG_SHA256"
	dpkg-deb -x "$archive" .
}

termux_step_make_install() {
	# Termux's own font directory, which every program's fontconfig reads.
	install -d "$TERMUX_PREFIX/share/fonts"
	cp -R usr/share/fonts/. "$TERMUX_PREFIX/share/fonts/"
}
