TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/libgit2-glib
TERMUX_PKG_DESCRIPTION="GLib wrapper around libgit2"
TERMUX_PKG_LICENSE="LGPL-2.1"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.2.1"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/libgit2-glib/${TERMUX_PKG_VERSION%.*}/libgit2-glib-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=97423a779002b3be8751c75f9d79049dfccca3616a26159fc162486772ba785f
TERMUX_PKG_DEPENDS="glib, libgit2"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross, valac"
TERMUX_PKG_DISABLE_GIR=false
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dintrospection=true
-Dvapi=true
-Dpython=false
-Dgtk_doc=false
"

termux_step_pre_configure() {
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper
	export TERMUX_MESON_ENABLE_SOVERSION=1
}
