TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Adreno Android address-space compatibility for WebGPU buffer mapping"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_LICENSE_FILE="LICENSE"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.1.0"
TERMUX_PKG_REVISION=1
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_BUILD_IN_SRC=true
# This library uses only the common AArch64 C ABI and resolves syscall/access/getenv
# from its host process. No Bionic dependency may be recorded: Chrome loads it in glibc.
TERMUX_PKG_NO_ELF_CLEANER=true
TERMUX_PKG_UNDEF_SYMBOLS_FILES="all"

termux_step_post_get_source() {
    cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}
termux_step_make_install() {
    install -d "$TERMUX_PREFIX/lib/android-webgpu"
    $CC -O2 -Wall -Wextra -Werror -fPIC -fno-stack-protector -nostdlib -shared \
        "$TERMUX_PKG_BUILDER_DIR/webgpu-map.c" -o "$TERMUX_PREFIX/lib/android-webgpu/libwebgpu-map.so"
    if "$READELF" -d "$TERMUX_PREFIX/lib/android-webgpu/libwebgpu-map.so" | grep '(NEEDED)' >/dev/null; then
        termux_error_exit "The WebGPU preload must not depend on an ABI-specific libc"
    fi
}
