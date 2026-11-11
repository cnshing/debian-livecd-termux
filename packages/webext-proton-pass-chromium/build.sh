TERMUX_PKG_HOMEPAGE=https://proton.me/pass
TERMUX_PKG_DESCRIPTION="Proton Pass for Chromium, Google Chrome and ungoogled Chromium"
TERMUX_PKG_LICENSE="GPL-3.0-only"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.43.0"
TERMUX_PKG_SRCURL="https://clients2.googleusercontent.com/crx/blobs/ARGaeZKLatFJdgtRDHFkbY9-yR7Y91jYsiHq7zTISbLzlGwhuihLsqqPVDAcQGdng-YmFgZh-zuZDXihN-wEihkzEjXnq-fH3lzln17T34z_95KHOWmByjmDqgkidIARhIbtAMZSmuVln6c5COOP2KoGaO0-6P9hNSWXiw/GHMBELDPHAFEPMBEGFDLKPAPADHBAKDE_1_43_0_0.crx"
TERMUX_PKG_SHA256=9f52c73fb98f9a53ab62d273b659e28e42a488ffaeae18436776080c6e485b9a
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false

_WEBEXT_ID='ghmbeldphafepmbegfdlkpapadhbakde'
_WEBEXT_BROWSER=chromium
source "$(dirname -- "${BASH_SOURCE[0]}")/webext.sh"
