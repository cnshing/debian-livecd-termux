TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/nautilus
TERMUX_PKG_DESCRIPTION="File browser for GNOME"
TERMUX_PKG_LICENSE="GPL-3.0-or-later"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="49.3"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/nautilus/${TERMUX_PKG_VERSION%%.*}/nautilus-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=aa6bf376f08992362805eae01890b1bf5ad148f356aa7ccfe1f664eda88d413e
TERMUX_PKG_DEPENDS="dbus, gdk-pixbuf, gexiv2, glib, gnome-autoar, gnome-desktop4, gstreamer, gtk4, libadwaita, libportal, libportal-gtk4, libstemmer, tinysparql, totem-pl-parser"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, gst-plugins-base, glib-cross"
TERMUX_PKG_PYTHON_COMMON_DEPS="setuptools, docutils"
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Ddocs=false
-Dcloudproviders=false
-Dpackagekit=false
-Dselinux=false
-Dtests=none
"

termux_step_pre_configure() {
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper
	export TERMUX_MESON_ENABLE_SOVERSION=1
	# Otherwise the linker can pick up a previously installed extension library.
	rm -rf "$TERMUX_PREFIX"/lib/libnautilus*
}
