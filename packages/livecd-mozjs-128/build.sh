TERMUX_PKG_HOMEPAGE=https://spidermonkey.dev/
TERMUX_PKG_DESCRIPTION="SpiderMonkey 128 for the isolated GNOME 48 runtime"
TERMUX_PKG_LICENSE="MPL-2.0"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="128.14.0"
TERMUX_PKG_SRCURL="https://deb.debian.org/debian/pool/main/m/mozjs128/mozjs128_${TERMUX_PKG_VERSION}.orig.tar.xz"
TERMUX_PKG_SHA256=41cca35149710ce45fbabc5fefcf86a01fdf833fdb783941964fca3a55fb72dd
TERMUX_PKG_DEPENDS="libc++, libnspr, zlib"
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_NO_STATICSPLIT=true
TERMUX_PKG_RM_AFTER_INSTALL="opt/gnome-48/lib/libjs_static.ajs"

termux_step_pre_configure() {
	termux_setup_nodejs
	termux_setup_rust
	local host_target
	host_target=$(rustc -vV | sed -n 's/^host: //p')
	if ! test -x "$TERMUX_PKG_HOSTBUILD_DIR/bin/cbindgen"; then
		RUSTFLAGS= cargo install cbindgen --version 0.26.0 --locked \
			--target "$host_target" --root "$TERMUX_PKG_HOSTBUILD_DIR"
	fi
	export PATH="$TERMUX_PKG_HOSTBUILD_DIR/bin:$PATH"
	export HOST_CC=clang HOST_CXX=clang++
	export MOZ_TERMUX_TARGET="$($CC -dumpmachine)"
	export MOZBUILD_STATE_PATH="$TERMUX_PKG_CACHEDIR/mozbuild"
	export CARGO_BUILD_JOBS="$TERMUX_PKG_MAKE_PROCESSES"
	CXXFLAGS+=" -U__ANDROID__ -D_LIBCPP_HAS_NO_C11_ALIGNED_ALLOC"
	LDFLAGS+=" -llog"
}

termux_step_configure() {
	sh "$TERMUX_PKG_SRCDIR/js/src/configure" \
		--prefix="$TERMUX_PREFIX/opt/gnome-48" \
		--target="$TERMUX_HOST_PLATFORM" \
		--host="$(clang -dumpmachine)" \
		--enable-shared-js --enable-release \
		--disable-jemalloc --disable-tests --disable-debug \
		--disable-debug-symbols --disable-strip --disable-bootstrap \
		--with-system-zlib --with-intl-api
}

termux_step_post_make_install() {
	python3 "$TERMUX_PKG_BUILDER_DIR/record.py" mozjs-128 \
		"$TERMUX_PREFIX/opt/gnome-48" "$TERMUX_PKG_BUILDER_DIR" \
		"$TERMUX_PKG_VERSION" "$TERMUX_PKG_SRCURL" "$TERMUX_PKG_SHA256"
}
