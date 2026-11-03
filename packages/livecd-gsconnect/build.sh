TERMUX_PKG_HOMEPAGE=https://github.com/GSConnect/gnome-shell-extension-gsconnect
TERMUX_PKG_DESCRIPTION="GSConnect daemon and settings for native Termux"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="LICENSES/GPL-2.0-or-later.txt"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="62+deb13u1"
TERMUX_PKG_REVISION=1
TERMUX_PKG_SRCURL="https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-gsconnect/gnome-shell-extension-gsconnect_62.orig.tar.gz"
TERMUX_PKG_SHA256=a467e200906f64e25cdbf2a0a9a8e85083208462725fcdd2e9914c68b1d4423c
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_DEPENDS="cjs, dbus, dconf, glib-networking, gsettings-desktop-schemas, gtk3, openssl-tool, python"
TERMUX_PKG_BUILD_DEPENDS="glib-cross"
TERMUX_PKG_RECOMMENDS="xfce4-notifyd"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dinstalled_tests=false
-Dnautilus=false
-Dwebextension=false
-Dsession_bus_services_dir=$TERMUX_PREFIX/share/dbus-1/services
-Dgnome_shell_libdir=$TERMUX_PREFIX/lib
"

termux_step_pre_configure() {
	termux_setup_glib_cross_pkg_config_wrapper
}

termux_step_post_make_install() {
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/gsconnect.py" "$TERMUX_PREFIX/bin/livecd-gsconnect"
}
