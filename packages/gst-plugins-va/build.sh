TERMUX_PKG_HOMEPAGE=https://gstreamer.freedesktop.org/
TERMUX_PKG_DESCRIPTION="GStreamer VA-API plugin (va): hardware H.264/HEVC encoding through the desktop's render node"
TERMUX_PKG_LICENSE="LGPL-2.1"
TERMUX_PKG_MAINTAINER="@cnshing"
# Built from the same release as Termux's gst-plugins-bad, which leaves the va
# plugin out. Only the files that package lacks are installed: libgstva-1.0
# and the plugin itself, which links that package's libgstcodecs-1.0.
TERMUX_PKG_VERSION="1.28.9"
TERMUX_PKG_SRCURL=https://gstreamer.freedesktop.org/src/gst-plugins-bad/gst-plugins-bad-${TERMUX_PKG_VERSION}.tar.xz
TERMUX_PKG_SHA256=4a4e0b7bf84f868378c48f143a7ac3a98923b488a5b74f1a35ba46bc3c43f6b1
TERMUX_PKG_DEPENDS="glib, gst-plugins-bad (= ${TERMUX_PKG_VERSION}), gst-plugins-base, gstreamer, libdrm, libva"
# Renamed from livecd-gst-va.
TERMUX_PKG_CONFLICTS="livecd-gst-va"
TERMUX_PKG_REPLACES="livecd-gst-va"
TERMUX_PKG_BUILD_DEPENDS="glib-cross"
TERMUX_PKG_AUTO_UPDATE=false
# va-android.patch: Meson calls this host "android", and the va library and
# plugin are otherwise built only for "linux" and "windows".
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dauto_features=disabled
-Dva=enabled
-Dexamples=disabled
-Dtests=disabled
-Dintrospection=disabled
-Dnls=disabled
-Dorc=disabled
-Dgpl=disabled
"

termux_step_pre_configure() {
	termux_setup_glib_cross_pkg_config_wrapper
}

termux_step_make_install() {
	local library
	# Meson keeps each library's objects in a ".p" directory beside it.
	for library in gst-libs/gst/va/libgstva-1.0.so*; do
		[ -d "$library" ] || cp -P "$library" "$TERMUX_PREFIX/lib/"
	done
	install -Dm600 sys/va/libgstva.so "$TERMUX_PREFIX/lib/gstreamer-1.0/libgstva.so"
}
