TERMUX_PKG_HOMEPAGE=https://mutter.gnome.org/
TERMUX_PKG_DESCRIPTION="GNOME 48 X11 compositor with Android and fullscreen fixes"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="48.8"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/mutter/${TERMUX_PKG_VERSION%%.*}/mutter-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=a483f91f75c16368d388179ecb855fcdb35db9c628f35b315b717153f99681a9
TERMUX_PKG_DEPENDS="atk, fribidi, gdk-pixbuf, glib, gnome-desktop4, gobject-introspection, graphene, gsettings-desktop-schemas, gtk4, harfbuzz, libandroid-shmem, libcairo, libcanberra, libcolord, libdisplay-info, libdrm, libei, libepoxy, libglvnd, libice, libpixman, libsm, libx11, libxau, libxcb, libxcomposite, libxcursor, libxdamage, libxext, libxfixes, libxi, libxinerama, libxkbcommon, libxkbfile, libxrandr, libxtst, littlecms, pango, pipewire, startup-notification, xkeyboard-config"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, glib-cross"
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_RM_AFTER_INSTALL="opt/gnome-48/share/glib-2.0/schemas/gschemas.compiled"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
--prefix=$TERMUX_PREFIX/opt/gnome-48
-Dlogind=false
-Dudev=false
-Dnative_backend=false
-Dwayland=false
-Dxwayland=false
-Dlibwacom=false
-Dintrospection=true
-Dtests=disabled
-Dinstalled_tests=false
-Dbash_completion=false
-Dprofiler=false
-Dopengl_libname=libGL.so
-Dgles2_libname=libGLESv2.so
--wrap-mode=nodownload
"

termux_step_pre_configure() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	livecd_gnome_setup
	LDFLAGS+=" -landroid-shmem"
}

termux_step_post_make_install() {
	livecd_gnome_record mutter
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	livecd_gnome_debscripts
}
