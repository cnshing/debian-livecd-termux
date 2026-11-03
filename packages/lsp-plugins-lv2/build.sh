TERMUX_PKG_HOMEPAGE=https://lsp-plug.in/
TERMUX_PKG_DESCRIPTION="LSP audio effects in LV2 format, without standalone plugin UIs (Termux port)"
TERMUX_PKG_LICENSE="LGPL-3.0-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING, COPYING.LESSER"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.2.35"
TERMUX_PKG_SRCURL="https://github.com/lsp-plugins/lsp-plugins/releases/download/${TERMUX_PKG_VERSION}/lsp-plugins-src-${TERMUX_PKG_VERSION}.tar.gz"
TERMUX_PKG_SHA256=2c95ec7bb219d561ea3db36051b6c732133bcd76426fb836b1dd850dc4b5bb6c
TERMUX_PKG_DEPENDS="libandroid-spawn, libc++, libcairo, libiconv, libsndfile"
TERMUX_PKG_BUILD_DEPENDS="ladspa-sdk, lv2"
TERMUX_PKG_BUILD_IN_SRC=true

# Linux builds assume iconv and posix_spawn are in libc. Termux uses libiconv and
# libandroid-spawn; pass them to utility executables and the LV2 shared object,
# preserving ELF hardening.
_lsp_make() {
	make "$@" FEATURES="lv2 crosscompile" \
		EXE_FLAGS="$LDFLAGS -Wl,-z,relro,-z,now -Wl,--gc-sections -liconv -landroid-spawn" \
		SO_FLAGS="$LDFLAGS -shared -fPIC -Wl,-z,relro,-z,now -Wl,--gc-sections -liconv -landroid-spawn"
}

termux_step_configure() {
	make config ARCHITECTURE="$TERMUX_ARCH" FEATURES="lv2 crosscompile" PREFIX="$TERMUX_PREFIX"
}

termux_step_make() {
	_lsp_make -j"$TERMUX_PKG_MAKE_PROCESSES"
}

termux_step_make_install() {
	_lsp_make install
}
