TERMUX_PKG_HOMEPAGE=https://missioncenter.io
TERMUX_PKG_DESCRIPTION="Mission Center using the shared native Android resource backend"
TERMUX_PKG_LICENSE="GPL-3.0-or-later, MIT"
TERMUX_PKG_LICENSE_FILE="COPYING, LICENSE-MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.2.0"
TERMUX_PKG_REVISION=1
_MC=193e3729367035cf184da004c3246efe79d5c53e
_MAGPIE=a5272b3c1d853caa4044b737cf49257bfc4c86f2
_RUMMAGE=26b93b8c6f0de6912f0a17022f7ece76bad87612
TERMUX_PKG_SRCURL=(
	"https://gitlab.com/mission-center-devs/mission-center/-/archive/$_MC/mission-center-$_MC.tar.gz"
	"https://gitlab.com/mission-center-devs/gng/-/archive/$_MAGPIE/gng-$_MAGPIE.tar.gz"
	"https://gitlab.com/mission-center-devs/app-detection/-/archive/$_RUMMAGE/app-detection-$_RUMMAGE.tar.gz"
)
TERMUX_PKG_SHA256=(
	94df753264ea20658b2805a605ef7f312ffd772846c6f3ee40ae05b7f5ddfbac
	e487986e7b1f165d92280e44b02ad57113fe44e7969483951cd10027feab7e81
	074cbd4898a104de43835299f5c5c0edc6f901ad00ff89a469a66d4fab8353de
)
TERMUX_PKG_DEPENDS="dconf, gettext, glib, gtk4 (>= 4.22), hicolor-icon-theme, libadwaita (>= 1.9), libandroid-spawn, libc++, libiconv, livecd-resources, openssl"
TERMUX_PKG_BUILD_DEPENDS="blueprint-compiler, glib-cross"
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_post_get_source() {
	rmdir subprojects/magpie
	mv "gng-$_MAGPIE" subprojects/magpie
	rmdir subprojects/magpie/platform-linux/crates/app-rummage
	mv "app-detection-$_RUMMAGE" subprojects/magpie/platform-linux/crates/app-rummage
	cp "$TERMUX_PKG_BUILDER_DIR/proc_stat.rs" subprojects/magpie/platform-linux/src/proc_stat.rs
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE-MIT" LICENSE-MIT
}

termux_step_pre_configure() {
	termux_setup_rust
	# magpie's nng-c-sys crate builds with CMake, which the cmake crate configures for Android
	# without the toolchain and API level that Termux's own CMake step passes. Give CMake those
	# through a toolchain file, which the cmake crate does accept.
	termux_setup_cmake
	if test "$TERMUX_ON_DEVICE_BUILD" = false; then
		local toolchain=$TERMUX_PKG_TMPDIR/android.cmake
		cat > "$toolchain" <<-EOF
			set(CMAKE_SYSTEM_NAME Android)
			set(CMAKE_SYSTEM_VERSION $TERMUX_PKG_API_LEVEL)
			set(CMAKE_ANDROID_STANDALONE_TOOLCHAIN $TERMUX_STANDALONE_TOOLCHAIN)
		EOF
		export "CMAKE_TOOLCHAIN_FILE_${CARGO_TARGET_NAME//-/_}=$toolchain"
	fi
	termux_setup_meson
	termux_setup_bpc
	termux_setup_glib_cross_pkg_config_wrapper
	export PKG_CONFIG_ALLOW_CROSS=1
}

termux_step_configure() {
	python3 "$TERMUX_PKG_BUILDER_DIR/prepare.py" "$TERMUX_PKG_SRCDIR" "$TERMUX_PKG_BUILDDIR/resources-build" "$TERMUX_PREFIX"
}

# Compiled crates live in the package cache, which CI saves, so unchanged ones are not rebuilt.
termux_step_make() {
	local target_args=() cache=$TERMUX_PKG_CACHEDIR/cargo-target
	if test -n "${CARGO_TARGET_NAME:-}"; then target_args=(--target "$CARGO_TARGET_NAME"); fi
	cargo build --manifest-path subprojects/magpie/Cargo.toml --release --locked "${target_args[@]}" --jobs "$TERMUX_PKG_MAKE_PROCESSES" \
		--target-dir "$cache/magpie"
	BUILD_ROOT="$TERMUX_PKG_BUILDDIR/resources-build" cargo build --release --locked "${target_args[@]}" --jobs "$TERMUX_PKG_MAKE_PROCESSES" \
		--target-dir "$cache/missioncenter"
}

termux_step_make_install() {
	local cache=$TERMUX_PKG_CACHEDIR/cargo-target triple=
	if test -n "${CARGO_TARGET_NAME:-}"; then triple=/$CARGO_TARGET_NAME; fi
	install -Dm755 "$cache/missioncenter$triple/release/missioncenter" "$TERMUX_PREFIX/bin/missioncenter"
	install -Dm755 "$cache/magpie$triple/release/magpie" "$TERMUX_PREFIX/bin/missioncenter-magpie"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/missioncenter-shizuku-setup" "$TERMUX_PREFIX/bin/missioncenter-shizuku-setup"
	install -Dm644 "$TERMUX_PKG_BUILDDIR/resources-build/resources/missioncenter.gresource" "$TERMUX_PREFIX/share/missioncenter/missioncenter.gresource"
	install -Dm644 "$TERMUX_PKG_BUILDDIR/resources-build/hwdb/hw.db" "$TERMUX_PREFIX/share/missioncenter/hw.db"
	install -Dm644 data/io.missioncenter.MissionCenter.gschema.xml "$TERMUX_PREFIX/share/glib-2.0/schemas/io.missioncenter.MissionCenter.gschema.xml"
	install -Dm644 data/io.missioncenter.MissionCenter.desktop.in "$TERMUX_PREFIX/share/applications/io.missioncenter.MissionCenter.desktop"
	install -Dm644 data/io.missioncenter.MissionCenter.metainfo.xml.in "$TERMUX_PREFIX/share/metainfo/io.missioncenter.MissionCenter.metainfo.xml"
	local icon language
	for icon in scalable/apps/io.missioncenter.MissionCenter.svg symbolic/apps/io.missioncenter.MissionCenter-symbolic.svg; do
		install -Dm644 "data/icons/hicolor/$icon" "$TERMUX_PREFIX/share/icons/hicolor/$icon"
	done
	for language in po/*.po; do
		local mo="$TERMUX_PREFIX/share/locale/$(basename "$language" .po)/LC_MESSAGES/missioncenter.mo"
		mkdir -p "$(dirname "$mo")"
		msgfmt "$language" -o "$mo"
	done
}
