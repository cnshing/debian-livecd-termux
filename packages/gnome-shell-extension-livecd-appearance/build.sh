TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Makes the live CD's WhiteSur theme and Colloid icons follow GNOME's accent color and style"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.0.0"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_DEPENDS="colloid-icon-theme, gnome-48-shell, whitesur-gtk-theme"

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make_install() {
	local extension="$TERMUX_PREFIX/share/gnome-shell/extensions/livecd-appearance@local"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/livecd-appearance@local/metadata.json" "$extension/metadata.json"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/livecd-appearance@local/extension.js" "$extension/extension.js"
}
