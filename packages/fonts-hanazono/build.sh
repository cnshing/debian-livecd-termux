TERMUX_PKG_HOMEPAGE=https://glyphwiki.org/wiki/GlyphWiki:HanaMin
TERMUX_PKG_DESCRIPTION="Hanazono Mincho, a Japanese font with extensive kanji coverage (Debian fonts-hanazono)"
TERMUX_PKG_LICENSE="custom, OFL-1.1"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/fonts-hanazono/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="20170904"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/f/fonts-hanazono/fonts-hanazono_20170904-3_all.deb
TERMUX_PKG_SHA256=ead623c26f77cb15874dae03d6f581e890225eacfe3fbe9f0665ecd6f4effd11
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
