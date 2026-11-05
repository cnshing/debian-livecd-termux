TERMUX_PKG_HOMEPAGE=https://github.com/ubuntu/gnome-shell-extension-appindicator
TERMUX_PKG_DESCRIPTION="AppIndicator and KStatusNotifierItem support for GNOME Shell (Debian gnome-shell-extension-appindicator)"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/gnome-shell-extension-appindicator/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="59"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-appindicator/gnome-shell-extension-appindicator_59-4_all.deb
TERMUX_PKG_SHA256=e0095529f79be06ef35d67d446253695a7feed8336439f2bf768aec08b918395
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="gnome-48-shell"
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
	local extensions="$TERMUX_PREFIX/share/gnome-shell/extensions"
	local schemas="$TERMUX_PREFIX/opt/gnome-48/share/glib-2.0/schemas"
	install -d "$extensions" "$schemas"
	cp -R usr/share/gnome-shell/extensions/ubuntu-appindicators@ubuntu.com "$extensions/"
	# One file at a time: some archives, such as ArcMenu's, carry the same schema twice.
	find usr/share -name '*.gschema.xml' -exec install -m644 -t "$schemas" {} \;
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	gnome_48_debscripts
}
