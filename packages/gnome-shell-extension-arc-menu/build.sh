TERMUX_PKG_HOMEPAGE=https://gitlab.com/arcmenu/ArcMenu
TERMUX_PKG_DESCRIPTION="ArcMenu, an application menu for GNOME Shell (Debian gnome-shell-extension-arc-menu)"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="usr/share/doc/gnome-shell-extension-arc-menu/copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="65"
TERMUX_PKG_SRCURL=https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-arc-menu/gnome-shell-extension-arc-menu_65-2_all.deb
TERMUX_PKG_SHA256=07777cc449327d9426ad9c1caf1dec523bb70be39727952319440159390252e6
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
	# Debian's package omits ArcMenu's menu icons, so take them from the matching upstream release.
	termux_download https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-arc-menu/gnome-shell-extension-arc-menu_65.orig.tar.gz "$TERMUX_PKG_CACHEDIR/arcmenu-65.orig.tar.gz" e38aba4038540cc9153f9d10d9742f8f403aeaeec7990dfdd6a2d0476c6a0a23
	tar -xzf "$TERMUX_PKG_CACHEDIR/arcmenu-65.orig.tar.gz" ArcMenu-v65/icons
}


termux_step_make_install() {
	local extensions="$TERMUX_PREFIX/share/gnome-shell/extensions"
	local schemas="$TERMUX_PREFIX/opt/gnome-48/share/glib-2.0/schemas"
	install -d "$extensions" "$schemas"
	cp -R usr/share/gnome-shell/extensions/arcmenu@arcmenu.com "$extensions/"
	# One file at a time: some archives, such as ArcMenu's, carry the same schema twice.
	find usr/share -name '*.gschema.xml' -exec install -m644 -t "$schemas" {} \;
	# Debian's package also omits upstream's stylesheet.
	install -m644 "$TERMUX_PKG_BUILDER_DIR/stylesheet.css" "$extensions/arcmenu@arcmenu.com/stylesheet.css"
	cp -R ArcMenu-v65/icons/. "$extensions/arcmenu@arcmenu.com/icons/"
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	gnome_48_debscripts
}
