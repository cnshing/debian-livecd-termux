TERMUX_PKG_HOMEPAGE=https://github.com/theonuverse/bionilux
TERMUX_PKG_DESCRIPTION="Runs glibc programs, such as Google Chrome, directly on Termux without PRoot"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.5.0"
TERMUX_PKG_SRCURL=https://codeload.github.com/theonuverse/bionilux/tar.gz/4152b476db31ffa8e2bb50b060292a59e15d0031
TERMUX_PKG_SHA256=aed1a206f8c74d0c375dfc91cde5ed4e6c43659fbbda944a5eb4538114598480
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
# glibc comes from Termux's glibc-repo, which the build cannot resolve as a dependency.
TERMUX_PKG_RECOMMENDS="glibc"
# The preloads are glibc libraries, which Termux's Bionic ELF handling would damage.
TERMUX_PKG_NO_ELF_CLEANER=true
TERMUX_PKG_UNDEF_SYMBOLS_FILES="all"

termux_step_configure() {
	termux_setup_rust
	# glibc's headers and C library, only to compile and link the two glibc preloads.
	mkdir -p sysroot
	local package url sha archive
	while read -r package url sha; do
		archive="$TERMUX_PKG_CACHEDIR/$(basename "$url")"
		termux_download "$url" "$archive" "$sha"
		dpkg-deb -x "$archive" sysroot
	done < <(python3 -c 'import json, sys; [print(i["package"], i["url"], i["sha256"]) for i in json.load(open(sys.argv[1]))]' \
		"$TERMUX_PKG_BUILDER_DIR/glibc-sysroot.lock.json")
}

termux_step_make() {
	cargo build --jobs "$TERMUX_PKG_MAKE_PROCESSES" --target "$CARGO_TARGET_NAME" --release --locked
	local glibc="$TERMUX_PREFIX/glibc" libraries="$PWD/sysroot/usr/lib/aarch64-linux-gnu"
	# As upstream's scripts/build-preload.sh, against Debian's glibc instead of the installed one.
	$CC --target=aarch64-linux-gnu --sysroot="$PWD/sysroot" -fuse-ld=lld -shared -fPIC -O2 -nostdlib \
		-Wall -Wextra src/preload/hooks.c "$libraries/libc.so.6" "$libraries/libdl.so.2" \
		-Wl,--dynamic-linker="$glibc/lib/ld-linux-aarch64.so.1" -Wl,-rpath,"$glibc/lib" \
		-o libbionilux_preload.so
	$CC --target=aarch64-linux-gnu --sysroot="$PWD/sysroot" -fuse-ld=lld -shared -fPIC -O2 -nostdlib \
		-Wall -Wextra -Werror "$TERMUX_PKG_BUILDER_DIR/bionilux-fortify.c" -o libbionilux-fortify.so
}

termux_step_make_install() {
	install -Dm755 "target/$CARGO_TARGET_NAME/release/bionilux" "$TERMUX_PREFIX/bin/bionilux"
	# Bionilux looks for its preload in glibc's library directory.
	install -Dm755 -t "$TERMUX_PREFIX/glibc/lib" libbionilux_preload.so libbionilux-fortify.so
}
