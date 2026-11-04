TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/gnome-control-center
TERMUX_PKG_DESCRIPTION="GNOME 48 Settings for the native X11 desktop"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="48.7"
TERMUX_PKG_SRCURL=(
	"https://download.gnome.org/sources/gnome-control-center/48/gnome-control-center-${TERMUX_PKG_VERSION}.tar.xz"
	"https://download.gnome.org/sources/tecla/48/tecla-48.0.2.tar.xz"
)
TERMUX_PKG_SHA256=(
	f647fa5a1cb176ffcfa65e0e3283981da442c262a0a47560ba64ce0097dd6b98
	783d3464d2a2cf7eb1507649dbd9ff09ce24852c2a6c9a0d365db84063d3d401
)
TERMUX_PKG_DEPENDS="fontconfig, gdk-pixbuf, glib, gnome-desktop4, gsound, gsettings-desktop-schemas, gtk4, ibus, json-glib, libadwaita, libcairo, libcolord, libepoxy, libgtop, libx11, libxi, libxml2, pango, pulseaudio, pygobject, python, termux-x11-nightly, upower (>= 1.90.6)"
TERMUX_PKG_RECOMMENDS="livecd-gnome-runtime (>= 48.8-1)"
TERMUX_PKG_SUGGESTS="openssh"
TERMUX_PKG_BUILD_DEPENDS="glib-cross"
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dsnap=false
-Dwayland=false
-Dlocation-services=disabled
-Dtests=false
-Ddocumentation=false
--wrap-mode=nodownload
"

termux_step_post_get_source() {
	mv tecla-48.0.2 subprojects/tecla
}

termux_step_pre_configure() {
	termux_setup_glib_cross_pkg_config_wrapper
	# The bundled GNOME volume-control library shares its name with Graphviz.
	LDFLAGS="-L$TERMUX_PKG_BUILDDIR/subprojects/gvc $LDFLAGS"
}

termux_step_post_make_install() {
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/resolution.py" \
		"$TERMUX_PREFIX/libexec/gnome-control-center/resolution.py"
}
