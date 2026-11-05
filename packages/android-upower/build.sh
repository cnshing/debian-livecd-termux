TERMUX_PKG_HOMEPAGE=https://upower.freedesktop.org/
TERMUX_PKG_DESCRIPTION="UPower reporting Android's battery, without a poll when Shizuku is available"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.91.5"
TERMUX_PKG_SRCURL="https://gitlab.freedesktop.org/upower/upower/-/archive/v$TERMUX_PKG_VERSION/upower-v$TERMUX_PKG_VERSION.tar.gz"
TERMUX_PKG_SHA256=d900f175e39fbc0dfd8632f7c70606e10f79903ee4171d199aa777dfa3a396e2
TERMUX_PKG_DEPENDS="glib, gobject-introspection, termux-api"
# Renamed from livecd-upower.
TERMUX_PKG_CONFLICTS="upower, livecd-upower"
TERMUX_PKG_REPLACES="upower, livecd-upower"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross"
TERMUX_PKG_VERSIONED_GIR=false
# Named apart so that a newer upower on Termux's mirrors cannot silently replace it.
# The version lets it satisfy versioned dependencies; apt-preferences does the rest.
TERMUX_PKG_PROVIDES="upower (= $TERMUX_PKG_VERSION)"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dintrospection=enabled
-Dos_backend=dummy
-Dpolkit=disabled
-Dsystemdsystemunitdir=no
-Dgtk-doc=false
-Dman=false
"

termux_step_pre_configure() {
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper

	export TERMUX_MESON_ENABLE_SOVERSION=1
}

termux_step_post_make_install() {
	install -d "$TERMUX_PREFIX/share/dbus-1/services"
	sed "s|@TERMUX_PREFIX@|$TERMUX_PREFIX|g" "$TERMUX_PKG_BUILDER_DIR/org.freedesktop.UPower.service" \
		> "$TERMUX_PREFIX/share/dbus-1/services/org.freedesktop.UPower.service"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/apt-preferences" "$TERMUX_PREFIX/etc/apt/preferences.d/android-upower"
}
