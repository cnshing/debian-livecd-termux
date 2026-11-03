TERMUX_PKG_HOMEPAGE=https://github.com/intel/libva
TERMUX_PKG_DESCRIPTION="VA-API client library for native applications and the private Termux:VA driver"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2.22.0"
TERMUX_PKG_SRCURL="https://codeload.github.com/intel/libva/tar.gz/refs/tags/$TERMUX_PKG_VERSION"
TERMUX_PKG_SHA256=467c418c2640a178c6baad5be2e00d569842123763b80507721ab87eb7af8735
TERMUX_PKG_DEPENDS="libdrm, libx11, libxcb, libxext, libxfixes"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dwith_x11=yes
-Dwith_wayland=no
-Dwith_glx=no
-Denable_docs=false
"
