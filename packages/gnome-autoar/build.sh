TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/gnome-autoar
TERMUX_PKG_DESCRIPTION="Automatic archive creation and extraction library for GNOME"
TERMUX_PKG_LICENSE="LGPL-2.1-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.4.5"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/gnome-autoar/${TERMUX_PKG_VERSION%.*}/gnome-autoar-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=838c5306fc38bfaa2f23abe24262f4bf15771e3303fb5dcb74f5b9c7a615dabe
TERMUX_PKG_DEPENDS="glib, gtk3, libarchive"
TERMUX_PKG_BUILD_DEPENDS="glib-cross"
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dintrospection=disabled
-Dgtk_doc=false
-Dtests=false
"

termux_step_pre_configure() {
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper
}
