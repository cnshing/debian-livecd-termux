TERMUX_PKG_HOMEPAGE=https://notofonts.github.io
TERMUX_PKG_DESCRIPTION="Noto fonts for the major scripts (Debian fonts-noto-core)"
TERMUX_PKG_LICENSE="OFL-1.1"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/fonts-noto-core/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="20201225"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/f/fonts-noto/fonts-noto-core_20201225-2_all.deb
TERMUX_PKG_SHA256=97978d09b68445fcf85342b106cd2e812d7813e3d5626f9884a5f344c3a55973
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
