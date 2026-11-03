TERMUX_PKG_HOMEPAGE=https://github.com/ViceVerse-cz/Serein
TERMUX_PKG_DESCRIPTION="Native Discord client with voice for the Termux X11 desktop"
TERMUX_PKG_LICENSE="MIT, Apache-2.0"
TERMUX_PKG_LICENSE_FILE="LICENSE-MIT, LICENSE-APACHE"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.0.0~nightly.20261028.68"
_TAG=v1.0.0-nightly.20261028.68
TERMUX_PKG_SRCURL="https://github.com/ViceVerse-cz/Serein/archive/refs/tags/$_TAG.tar.gz"
TERMUX_PKG_SHA256=98914d0b782bccf547dea11185626658a8686e819babd22b9f7cb880ff3f834a
TERMUX_PKG_DEPENDS="alsa-lib, fontconfig, freetype, glib, gst-libav, gst-plugins-bad, gst-plugins-base, gst-plugins-good, gstreamer, gtk4, hicolor-icon-theme, libc++, libx11, libxcb, libxcursor, libxi, libxkbcommon, libxrandr, mesa, openssl, pulseaudio, webkitgtk-6.0, xdg-utils"
TERMUX_PKG_BUILD_DEPENDS="vulkan-headers"
TERMUX_PKG_RECOMMENDS="gnome-keyring"
TERMUX_PKG_BUILD_IN_SRC=true
# The first port targets the project's arm64 phone; other architectures need validation.
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_AUTO_UPDATE=false

termux_step_configure() {
	if test "$TERMUX_ON_DEVICE_BUILD" = false; then
		# Match upstream's rust-toolchain.toml instead of installing two toolchains.
		export TERMUX_RUST_VERSION=1.98.1
	fi
	termux_setup_rust
	termux_setup_cmake
	export PKG_CONFIG_ALLOW_CROSS=1
	# Keep this build practical on a phone and avoid upstream's memory-heavy fat LTO.
	export CARGO_PROFILE_RELEASE_LTO=thin
	export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
	export CARGO_PROFILE_RELEASE_DEBUG=0
	# Keep compiled crates in the package cache, which CI saves, so unchanged ones are not rebuilt.
	# prepare.py edits vendored crates, and Cargo does not notice changes to those, so any change to
	# this recipe starts the cache over.
	export CARGO_TARGET_DIR=$TERMUX_PKG_CACHEDIR/cargo-target
	local recipe
	recipe=$(cd "$TERMUX_PKG_BUILDER_DIR" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
	if test "$(cat "$CARGO_TARGET_DIR/recipe.sha256" 2>/dev/null)" != "$recipe"; then
		rm -rf "$CARGO_TARGET_DIR"
		mkdir -p "$CARGO_TARGET_DIR"
		echo "$recipe" > "$CARGO_TARGET_DIR/recipe.sha256"
	fi
	if test "$TERMUX_ON_DEVICE_BUILD" = true; then
		# LLD 21 on the Android 11 rig intermittently aborts in its parallel
		# allocator. Limit linker threads for native host tools as well as Serein.
		mkdir -p "$TERMUX_PKG_TMPDIR/native-linker"
		sed "s|@TERMUX_PREFIX@|$TERMUX_PREFIX|g" "$TERMUX_PKG_BUILDER_DIR/native-cc.sh.in" \
			> "$TERMUX_PKG_TMPDIR/native-linker/cc"
		chmod 755 "$TERMUX_PKG_TMPDIR/native-linker/cc"
		export PATH="$TERMUX_PKG_TMPDIR/native-linker:$PATH"
		local target=${CARGO_TARGET_NAME//-/_}
		export "CARGO_TARGET_${target^^}_LINKER=$TERMUX_PKG_TMPDIR/native-linker/cc"
	fi
	$CC $CPPFLAGS $CFLAGS -fPIC -c "$TERMUX_PKG_BUILDER_DIR/renameat2-compat.c" \
		-o "$TERMUX_PKG_TMPDIR/renameat2-compat.o"
	# Continued builds retain prepared sources, but need their tool paths and env.
	if test "$TERMUX_CONTINUE_BUILD" = true; then return; fi
	# Vendor the locked registry AND git dependencies before changing desktop cfgs.
	# Source replacements retain upstream versions and package checksums.
	cargo vendor --locked termux-vendor > "$TERMUX_PKG_TMPDIR/serein-vendor.toml"
	cat "$TERMUX_PKG_TMPDIR/serein-vendor.toml" >> .cargo/config.toml
	python3 "$TERMUX_PKG_BUILDER_DIR/prepare.py" "$TERMUX_PKG_SRCDIR" "$TERMUX_PREFIX"
}

termux_step_make() {
	cargo rustc --locked --offline --release --package serein --bin serein --no-default-features --features demo \
		--target "$CARGO_TARGET_NAME" --jobs "$TERMUX_PKG_MAKE_PROCESSES" \
		-- -C "link-arg=$TERMUX_PKG_TMPDIR/renameat2-compat.o"
}

termux_step_make_install() {
	install -Dm755 "$CARGO_TARGET_DIR/$CARGO_TARGET_NAME/release/serein" "$TERMUX_PREFIX/bin/serein"
	install -Dm644 packaging/linux/serein.desktop "$TERMUX_PREFIX/share/applications/serein.desktop"
	install -Dm644 assets/brand/serein.svg "$TERMUX_PREFIX/share/icons/hicolor/scalable/apps/serein.svg"
	install -Dm644 THIRD_PARTY_NOTICES.md "$TERMUX_PREFIX/share/doc/serein/THIRD_PARTY_NOTICES.md"
	cp -a assets/licenses "$TERMUX_PREFIX/share/doc/serein/"
}
