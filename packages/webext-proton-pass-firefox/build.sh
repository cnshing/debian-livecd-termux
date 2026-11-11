TERMUX_PKG_HOMEPAGE=https://proton.me/pass
TERMUX_PKG_DESCRIPTION="Proton Pass for Firefox"
TERMUX_PKG_LICENSE="GPL-3.0-only"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.43.1"
TERMUX_PKG_SRCURL="https://addons.mozilla.org/firefox/downloads/file/5203430/proton_pass-1.43.1.xpi"
TERMUX_PKG_SHA256=a973bb13e22816b73bc8be9c6a4df9d2b478b4e3d57d11f50033ff4e15f9b7b4
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="webext-firefox-common"

_WEBEXT_ID='78272b6fa58f4a1abaac99321d503a20@proton.me'
_WEBEXT_BROWSER=firefox
source "$(dirname -- "${BASH_SOURCE[0]}")/webext.sh"
