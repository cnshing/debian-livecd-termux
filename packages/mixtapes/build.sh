TERMUX_PKG_HOMEPAGE=https://github.com/m-obeid/Mixtapes
TERMUX_PKG_DESCRIPTION="Mixtapes YouTube Music player for native Termux"
TERMUX_PKG_LICENSE="GPL-3.0-only"
TERMUX_PKG_LICENSE_FILE="LICENSE"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.1.0+git20261019.618c24c"
_COMMIT=618c24c3abfb12266825a4373155f26e9abbff36
_VERIFIER=rustls-platform-verifier-0.7.0
TERMUX_PKG_SRCURL=(
	"https://github.com/m-obeid/Mixtapes/archive/$_COMMIT.tar.gz"
	"https://static.crates.io/crates/rustls-platform-verifier/$_VERIFIER.crate"
)
TERMUX_PKG_SHA256=(
	a09276af07e80fcdeb84398807c184ef29d34120e23e6cdc3be8c0af78c2d37f
	26d1e2536ce4f35f4846aa13bff16bd0ff40157cdb14cc056c7b14ba41233ba0
)
TERMUX_PKG_DEPENDS="ffmpeg, gst-libav, gst-plugins-bad, gst-plugins-base, gst-plugins-good, gstreamer, gtk4, libadwaita, libsqlite, nodejs-lts | nodejs, openssl, python-yt-dlp, webkitgtk-6.0, yt-dlp-ejs"
# Renamed from livecd-mixtapes.
TERMUX_PKG_CONFLICTS="livecd-mixtapes"
TERMUX_PKG_REPLACES="livecd-mixtapes"
TERMUX_PKG_BUILD_DEPENDS="glib-cross"
TERMUX_PKG_RECOMMENDS="glibc, openssl-glibc"
# Bundles rustypipe-botguard's aarch64 glibc binary, which must not be stripped or cleaned.
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_NO_ELF_CLEANER=true
TERMUX_PKG_NO_STRIP=true
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_post_get_source() {
	mv "$_VERIFIER" vendor/rustls-platform-verifier
}

termux_step_make() {
	termux_setup_rust
	# The aws-lc-sys crate builds with CMake.
	termux_setup_cmake
	# build.rs runs glib-compile-resources, which has to run on the build machine.
	export PATH="$TERMUX_PREFIX/opt/glib/cross/bin:$PATH"
	# Keep compiled crates in the package cache, which CI saves, so unchanged ones are not rebuilt.
	cargo build --jobs "$TERMUX_PKG_MAKE_PROCESSES" --target "$CARGO_TARGET_NAME" --release --locked \
		--target-dir "$TERMUX_PKG_CACHEDIR/cargo-target"
}

termux_step_make_install() {
	local stage
	stage=$(mktemp -d)
	install -Dm755 "$TERMUX_PKG_CACHEDIR/cargo-target/$CARGO_TARGET_NAME/release/mixtapes" "$TERMUX_PREFIX/bin/mixtapes"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/rustypipe-botguard" "$TERMUX_PREFIX/lib/mixtapes/bin/rustypipe-botguard"
	tar -xJf vendor/rustypipe-botguard/rustypipe-botguard-v0.1.2-aarch64-unknown-linux-gnu.tar.xz -C "$stage"
	install -Dm755 "$stage/rustypipe-botguard" "$TERMUX_PREFIX/lib/mixtapes/rustypipe-botguard.bin"
	rm -rf "$stage"
	install -Dm644 com.pocoguy.Muse.desktop "$TERMUX_PREFIX/share/applications/com.pocoguy.Muse.desktop"
	install -Dm644 com.pocoguy.Muse.metainfo.xml "$TERMUX_PREFIX/share/metainfo/com.pocoguy.Muse.metainfo.xml"
	local icon
	for icon in scalable/apps/com.pocoguy.Muse.svg symbolic/apps/com.pocoguy.Muse-symbolic.svg; do
		install -Dm644 "assets/icons/hicolor/$icon" "$TERMUX_PREFIX/share/icons/hicolor/$icon"
	done
}
