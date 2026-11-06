TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Request-driven Android CPU, process and sensor snapshots for native applications"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_LICENSE_FILE="LICENSE"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.0.0"
# Renamed from livecd-resources.
TERMUX_PKG_CONFLICTS="livecd-resources"
TERMUX_PKG_REPLACES="livecd-resources"
TERMUX_PKG_REVISION=4
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_post_get_source() {
	cp -r "$TERMUX_PKG_BUILDER_DIR/src" "$TERMUX_PKG_SRCDIR/"
	cp "$TERMUX_PKG_BUILDER_DIR/"{Cargo.toml,Cargo.lock,LICENSE} "$TERMUX_PKG_SRCDIR/"
}

termux_step_pre_configure() { termux_setup_rust; }
termux_step_configure() { :; }

termux_step_make() {
	local target_args=()
	if test -n "${CARGO_TARGET_NAME:-}"; then target_args=(--target "$CARGO_TARGET_NAME"); fi
	cargo build --release --locked "${target_args[@]}"
	$CC $CFLAGS "$TERMUX_PKG_BUILDER_DIR/stat-reader.c" $LDFLAGS -o "$TERMUX_PKG_BUILDDIR/stat-reader"
	$CC $CFLAGS "$TERMUX_PKG_BUILDER_DIR/exec-system.c" $LDFLAGS -o "$TERMUX_PKG_BUILDDIR/exec-system"
}

termux_step_make_install() {
	local target_dir=target
	if test -n "${CARGO_TARGET_NAME:-}"; then target_dir+=/$CARGO_TARGET_NAME; fi
	install -Dm755 "$target_dir/release/libandroid_procfs.so" "$TERMUX_PREFIX/lib/libandroid_procfs.so"
	install -Dm755 "$target_dir/release/android-procfs-broker" "$TERMUX_PREFIX/libexec/android-procfs/broker"
	# Real TLS, needing Android 10. With the default emulated TLS, preloading this library aborts
	# every Node.js program: "Pointer tag ... was truncated". See docs/resources/README.md#compatibility-boundary.
	$CC $CFLAGS -fno-emulated-tls -shared -fPIC "$TERMUX_PKG_BUILDER_DIR/proc-compat.c" -I"$TERMUX_PKG_BUILDER_DIR" -L"$TERMUX_PREFIX/lib" -landroid_procfs -ldl -pthread $LDFLAGS -o "$TERMUX_PREFIX/lib/libandroid-procfs.so"
	# Check the emitted artifact, rather than treating a compiler flag as proof. grep reads every line:
	# with -q it can exit before readelf finishes, and pipefail then fails a library that has the segment.
	if ! "$READELF" -lW "$TERMUX_PREFIX/lib/libandroid-procfs.so" | grep ' TLS ' >/dev/null; then
		termux_error_exit "The resource preload must use ELF TLS (Android 10+)"
	fi
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/android-procfs-run" "$TERMUX_PREFIX/bin/android-procfs-run"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/top" "$TERMUX_PREFIX/libexec/android-procfs/bin/top"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/android-procfs.h" "$TERMUX_PREFIX/include/android-procfs.h"
	install -Dm755 "$TERMUX_PKG_BUILDDIR/stat-reader" "$TERMUX_PREFIX/libexec/android-procfs/stat-reader"
	install -Dm755 "$TERMUX_PKG_BUILDDIR/exec-system" "$TERMUX_PREFIX/libexec/android-procfs/exec-system"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/android-procfs-setup" "$TERMUX_PREFIX/bin/android-procfs-setup"
	mkdir -p "$TERMUX_PREFIX/lib/pkgconfig"
	cat > "$TERMUX_PREFIX/lib/pkgconfig/android-procfs.pc" <<EOF
prefix=$TERMUX_PREFIX
libdir=\${prefix}/lib
includedir=\${prefix}/include
Name: android-procfs
Description: Request-driven Android resource snapshots
Version: $TERMUX_PKG_VERSION
Libs: -L\${libdir} -landroid_procfs
Cflags: -I\${includedir}
EOF
}
