TERMUX_PKG_HOMEPAGE=https://github.com/Leleat/Tiling-Assistant
TERMUX_PKG_DESCRIPTION="Tiling Assistant: Windows-like window tiling for GNOME Shell (Debian gnome-shell-extension-tiling-assistant)"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/gnome-shell-extension-tiling-assistant/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="51"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-tiling-assistant/gnome-shell-extension-tiling-assistant_51-2_all.deb
TERMUX_PKG_SHA256=b36bea8041e78b55d15b0cc3c2512efcad76bc46fe07f1aa8160a2007eed53ea
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
	cp -R usr/share/gnome-shell/extensions/tiling-assistant@leleat-on-github "$extensions/"
	# One file at a time: some archives, such as ArcMenu's, carry the same schema twice.
	find usr/share -name '*.gschema.xml' -exec install -m644 -t "$schemas" {} \;
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	gnome_48_debscripts
}
