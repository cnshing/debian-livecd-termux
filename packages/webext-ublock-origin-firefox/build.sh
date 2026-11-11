TERMUX_PKG_HOMEPAGE=https://github.com/gorhill/uBlock
TERMUX_PKG_DESCRIPTION="uBlock Origin for Firefox"
TERMUX_PKG_LICENSE="GPL-3.0-only"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.76.0"
TERMUX_PKG_SRCURL="https://addons.mozilla.org/firefox/downloads/file/5225273/ublock_origin-1.76.0.xpi"
TERMUX_PKG_SHA256=6f20ff6749193599548770539103069c20948dfcd3e61c3089a67da7bfc3be39
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="webext-firefox-common"

_WEBEXT_ID='uBlock0@raymondhill.net'
_WEBEXT_BROWSER=firefox
source "$(dirname -- "${BASH_SOURCE[0]}")/webext.sh"
