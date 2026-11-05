TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/gnome-shell-extensions
TERMUX_PKG_DESCRIPTION="User Themes: load GNOME Shell themes from the user directory (Debian gnome-shell-extension-user-theme)"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/gnome-shell-extension-user-theme/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="48.2"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/g/gnome-shell-extensions/gnome-shell-extension-user-theme_48.2-1_all.deb
TERMUX_PKG_SHA256=77bed4feb016638cc8a0015e354050d41fcd7bc32fd9557827f7ead88d97d3ee
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
	cp -R usr/share/gnome-shell/extensions/user-theme@gnome-shell-extensions.gcampax.github.com "$extensions/"
	# One file at a time: some archives, such as ArcMenu's, carry the same schema twice.
	find usr/share -name '*.gschema.xml' -exec install -m644 -t "$schemas" {} \;
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	gnome_48_debscripts
}
