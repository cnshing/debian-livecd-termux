TERMUX_PKG_HOMEPAGE=https://gjs.guide/
TERMUX_PKG_DESCRIPTION="GJS for the isolated GNOME 48 runtime"
TERMUX_PKG_LICENSE="MIT, LGPL-2.0-or-later"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.84.2"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/gjs/${TERMUX_PKG_VERSION%.*}/gjs-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=35142edf345705636300291ec3a7d583f14969ff3fae0ff30f4a95b1e6740166
TERMUX_PKG_DEPENDS="glib, gobject-introspection, libc++, libcairo, libffi, libx11, livecd-mozjs-128, readline"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross"
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
--prefix=$TERMUX_PREFIX/opt/gnome-48
-Db_pch=false
-Dinstalled_tests=false
-Dskip_tests=true
-Dprofiler=disabled
-Ddtrace=false
-Dsystemtap=false
--wrap-mode=nodownload
"

termux_step_pre_configure() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	livecd_gnome_setup
}

termux_step_post_make_install() {
	livecd_gnome_record gjs
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	livecd_gnome_debscripts
}
