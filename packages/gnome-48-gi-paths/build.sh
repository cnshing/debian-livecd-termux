TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Adapter for the three legacy GI entry points the GNOME-Termux Shell binary calls"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.1.0"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_DEPENDS="glib"
# Renamed from livecd-gi-paths.
TERMUX_PKG_CONFLICTS="livecd-gi-paths"
TERMUX_PKG_REPLACES="livecd-gi-paths"
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make() {
	# shellcheck disable=SC2046
	$CC $CFLAGS -shared -fPIC -O2 -Wl,-soname,libgnome-48-gi-paths.so "$TERMUX_PKG_BUILDER_DIR/gi-paths.c" \
		-o libgnome-48-gi-paths.so $(pkg-config --cflags --libs glib-2.0) $LDFLAGS
}

termux_step_make_install() {
	install -Dm755 libgnome-48-gi-paths.so "$TERMUX_PREFIX/lib/libgnome-48-gi-paths.so"
}
