TERMUX_PKG_HOMEPAGE=https://github.com/googlefonts/noto-emoji
TERMUX_PKG_DESCRIPTION="Noto Color Emoji font (Debian fonts-noto-color-emoji)"
TERMUX_PKG_LICENSE="OFL-1.1, Apache-2.0"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/fonts-noto-color-emoji/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2.051"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/f/fonts-noto-color-emoji/fonts-noto-color-emoji_2.051-0+deb13u1_all.deb
TERMUX_PKG_SHA256=03141cd51c0e9ff8ad858fcf2d8234f8a00ae4d7a0872df43a71519359c54e8c
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
