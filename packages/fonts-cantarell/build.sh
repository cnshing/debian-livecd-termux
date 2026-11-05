TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/cantarell-fonts
TERMUX_PKG_DESCRIPTION="Cantarell, GNOME's interface font (Debian fonts-cantarell)"
TERMUX_PKG_LICENSE="OFL-1.1"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/fonts-cantarell/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.303.1"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/f/fonts-cantarell/fonts-cantarell_0.303.1-4_all.deb
TERMUX_PKG_SHA256=21f8160696cd2b51ac104e735fd63d0e2245cd84cf75f17919f1425dce4ea258
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
