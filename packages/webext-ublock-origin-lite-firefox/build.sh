TERMUX_PKG_HOMEPAGE=https://github.com/gorhill/uBlock
TERMUX_PKG_DESCRIPTION="uBlock Origin Lite for Firefox"
TERMUX_PKG_LICENSE="GPL-3.0-only"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2026.1110.1816"
TERMUX_PKG_SRCURL="https://addons.mozilla.org/firefox/downloads/file/5235054/ublock_origin_lite-2026.1110.1816.xpi"
TERMUX_PKG_SHA256=3838bf88742ab921f553795b5b96f21e6429e198c1db3865c414402e5fe55059
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="webext-firefox-common"

_WEBEXT_ID='uBOLiteRedux@raymondhill.net'
_WEBEXT_BROWSER=firefox
source "$(dirname -- "${BASH_SOURCE[0]}")/webext.sh"
