TERMUX_PKG_HOMEPAGE=https://bitwarden.com/
TERMUX_PKG_DESCRIPTION="Bitwarden for Firefox"
TERMUX_PKG_LICENSE="GPL-3.0-only, custom"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2026.10.2"
TERMUX_PKG_SRCURL="https://addons.mozilla.org/firefox/downloads/file/5198653/bitwarden_password_manager-2026.10.2.xpi"
TERMUX_PKG_SHA256=abf9d7273dd55ac0583ecc6997f7f7ae3d29de11e2ad0a4838b80e2b941daa73
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="webext-firefox-common"
# License texts from bitwarden/clients at browser-v2026.10.2.
TERMUX_PKG_LICENSE_FILE="LICENSE.txt, LICENSE_GPL.txt, LICENSE_BITWARDEN.txt"

_WEBEXT_ID='{446900e4-71c2-419f-a6a7-df9c091e268b}'
_WEBEXT_BROWSER=firefox
source "$(dirname -- "${BASH_SOURCE[0]}")/webext.sh"
