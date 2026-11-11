TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Firefox preferences for packaged web extensions"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.0.0"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_DEPENDS="firefox"

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make_install() {
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/livecd-extensions.js" \
		"$TERMUX_PREFIX/lib/firefox/browser/defaults/preferences/livecd-extensions.js"
}
