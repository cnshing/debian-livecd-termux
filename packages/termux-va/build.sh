TERMUX_PKG_HOMEPAGE=https://github.com/lfdevs/termux-va
TERMUX_PKG_DESCRIPTION="Termux:VA daemon: serves VA-API decoding and encoding through Android's MediaCodec"
TERMUX_PKG_LICENSE="GPL-3.0"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2026.10.30"
TERMUX_PKG_SRCURL=https://codeload.github.com/lfdevs/termux-va/tar.gz/ae14813d77dbf107273b410a32f4ade34ba56313
TERMUX_PKG_SHA256=c25c87523d31aa7941c20aa015fc64d0429ed5fd977b0f6af58dfad7ea34bc1d
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false

termux_step_configure() {
	:
}

termux_step_make() {
	# Android 10's NDK media API, as the phone builds of this daemon used.
	$CC --target=aarch64-linux-android29 $CFLAGS $CPPFLAGS -std=c11 -I common daemon/termux-va.c \
		-o termux-va $LDFLAGS -lmediandk -llog -landroid
}

termux_step_make_install() {
	install -Dm755 termux-va "$TERMUX_PREFIX/bin/termux-va"
}
