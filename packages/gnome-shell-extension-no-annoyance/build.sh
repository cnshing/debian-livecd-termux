TERMUX_PKG_HOMEPAGE=https://github.com/jirkavrba/noannoyance
TERMUX_PKG_DESCRIPTION="NoAnnoyance: focus windows instead of showing 'is ready' notifications (Debian gnome-shell-extension-no-annoyance)"
TERMUX_PKG_LICENSE="GPL-2.0-only"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/gnome-shell-extension-no-annoyance/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0+20241212.8ca0647"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-no-annoyance/gnome-shell-extension-no-annoyance_0+20241212-8ca0647-1_all.deb
TERMUX_PKG_SHA256=ff91e53aa40e3f2f3e003c027e539fbf1f2206d8a5e8ccdb5de88baa707b7ce5
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
	cp -R usr/share/gnome-shell/extensions/noannoyance-fork@vrba.dev "$extensions/"
	# One file at a time: some archives, such as ArcMenu's, carry the same schema twice.
	find usr/share -name '*.gschema.xml' -exec install -m644 -t "$schemas" {} \;
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	gnome_48_debscripts
}
