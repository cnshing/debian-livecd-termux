TERMUX_PKG_HOMEPAGE=https://github.com/elementary/granite
TERMUX_PKG_DESCRIPTION="Extension of GTK 3 for elementary apps such as Code"
TERMUX_PKG_LICENSE="LGPL-3.0"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
# The last GTK 3 release. Granite 7 is GTK 4, and Code still asks for this one by name.
TERMUX_PKG_VERSION="6.2.0"
TERMUX_PKG_SRCURL="https://github.com/elementary/granite/archive/refs/tags/${TERMUX_PKG_VERSION}.tar.gz"
TERMUX_PKG_SHA256=067d31445da9808a802fca523630c3e4b84d2d7c78ae547ced017cb7f3b9c6b5
TERMUX_PKG_DEPENDS="glib, gtk3, libgee"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross, valac"
TERMUX_PKG_DISABLE_GIR=false
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Ddocumentation=false
-Dintrospection=true
"

termux_step_pre_configure() {
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper
	export TERMUX_MESON_ENABLE_SOVERSION=1
}
