TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/gnome-shell/
TERMUX_PKG_DESCRIPTION="GNOME Shell 48 for native Termux on X11"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="48.8"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/gnome-shell/${TERMUX_PKG_VERSION%%.*}/gnome-shell-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=cb9b7d86cf362530e648e68caaf109a32af4e832874a26791ca8789773efd233
TERMUX_PKG_DEPENDS="at-spi2-core, atk, gcr4, geoclue, gdk-pixbuf, glib, gnome-desktop4, gnome-menus, gnome-session, gobject-introspection, graphene, gtk4, ibus, libgweather, libx11, libxext, libxfixes, libxml2, livecd-gjs, livecd-mutter, livecd-upower, pango, pulseaudio"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross"
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_RM_AFTER_INSTALL="opt/gnome-48/share/glib-2.0/schemas/gschemas.compiled"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
--prefix=$TERMUX_PREFIX/opt/gnome-48
-Dpolkit=false
-Dnetworkmanager=false
-Dportal_helper=false
-Dcamera_monitor=false
-Dsystemd=false
-Dextensions_tool=false
-Dextensions_app=false
-Dtests=false
-Dman=false
-Dcalendar_server=false
-Dgjs_path=$TERMUX_PREFIX/opt/gnome-48/bin/gjs
--wrap-mode=nodownload
"

termux_step_pre_configure() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	livecd_gnome_setup
}

termux_step_post_make_install() {
	livecd_gnome_record gnome-shell
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	livecd_gnome_debscripts
}
