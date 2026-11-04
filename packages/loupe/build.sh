TERMUX_PKG_HOMEPAGE=https://apps.gnome.org/Loupe/
TERMUX_PKG_DESCRIPTION="GNOME image viewer using Glycin's built-in Android decoder"
TERMUX_PKG_LICENSE="GPL-3.0-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING.md"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="51.1"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/loupe/${TERMUX_PKG_VERSION%.*}/loupe-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=a38907d01bb6e027aeb772d10bc6cc2f92fde54d2090f6352dca8e84606e7730
TERMUX_PKG_DEPENDS="dconf, gettext, glib, gtk4 (>= 4.16), hicolor-icon-theme, libadwaita (>= 1.8), libcairo, libgweather, libiconv"
TERMUX_PKG_BUILD_DEPENDS="desktop-file-utils, glib-cross"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="-Dprofile=release -Dx11=enabled"

termux_step_pre_configure() {
	termux_setup_rust
	termux_setup_glib_cross_pkg_config_wrapper
	export PKG_CONFIG_ALLOW_CROSS=1
	export CARGO_BUILD_TARGET=$CARGO_TARGET_NAME
	export CARGO_PROFILE_RELEASE_LTO=thin
	export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
	export CARGO_PROFILE_RELEASE_DEBUG=0
	export CARGO_TARGET_DIR=$TERMUX_PKG_CACHEDIR/cargo-target
	export APP_ID=org.gnome.Loupe VERSION=$TERMUX_PKG_VERSION LOCALEDIR=$TERMUX_PREFIX/share/locale
	local target=${CARGO_TARGET_NAME//-/_}
	export CARGO_TARGET_${target^^}_RUSTFLAGS+=" -C link-arg=-liconv"
}
