TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/libpeas
TERMUX_PKG_DESCRIPTION="GObject plugin library, version 2, which elementary Code loads its plugins with"
TERMUX_PKG_LICENSE="LGPL-2.1"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2.2.1"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/libpeas/${TERMUX_PKG_VERSION%.*}/libpeas-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=589eca89b437006edf3755478df037c740a2a84cfa5d202dbad6095e828e2488
TERMUX_PKG_DEPENDS="glib"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross"
TERMUX_PKG_DISABLE_GIR=false
TERMUX_PKG_VERSIONED_GIR=false
# Only C plugins, as Code's own are. Termux's libpeas 1 leaves out the Python loader too.
# No Vala bindings: Code brings its own, and valac would pick these up first.
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dgjs=false
-Dlua51=false
-Dpython3=false
-Dintrospection=true
-Dvapi=false
-Dgtk_doc=false
"

termux_step_pre_configure() {
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper
	export TERMUX_MESON_ENABLE_SOVERSION=1
}
