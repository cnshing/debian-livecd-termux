TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Android front and rear cameras for native V4L2 and PipeWire programs"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_LICENSE_FILE="COPYING, LICENSE, android-v4l2-LICENSE"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.1.0"
# pw-v4l2 is built from the same PipeWire release as Termux's pipewire package, against its ABI.
TERMUX_PKG_SRCURL="https://gitlab.freedesktop.org/pipewire/pipewire/-/archive/1.4.9/pipewire-1.4.9.tar.bz2"
TERMUX_PKG_SHA256=e606aa3f6d53ec4c56fe35034d35cadfe0bbea1a5275e4e006dd7d1abaec6b92
TERMUX_PKG_DEPENDS="pipewire, python"
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" "$TERMUX_PKG_SRCDIR/android-v4l2-LICENSE"
}

termux_step_configure() { :; }

termux_step_make() {
	local pw_flags
	pw_flags=$(pkg-config --cflags --libs libpipewire-0.3)
	: > config.h
	# Only the V4L2 compatibility library, as PipeWire's own build makes it.
	# shellcheck disable=SC2086
	$CC $CPPFLAGS $CFLAGS -shared -fPIC -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32 \
		-D_LARGEFILE64_SOURCE -U_TIME_BITS -fvisibility=hidden -I. \
		pipewire-v4l2/src/pipewire-v4l2.c pipewire-v4l2/src/v4l2-func.c $pw_flags -lm $LDFLAGS -o libpw-v4l2.so
	$CC $CPPFLAGS $CFLAGS -Wall -shared -fPIC -U_FORTIFY_SOURCE \
		"$TERMUX_PKG_BUILDER_DIR/v4l2.c" -ldl $LDFLAGS -o libandroid-v4l2.so
	# shellcheck disable=SC2086
	$CC $CPPFLAGS $CFLAGS -Wall "$TERMUX_PKG_BUILDER_DIR/camera-node.c" $pw_flags \
		-lcamera2ndk -lmediandk -ldl $LDFLAGS -o camera-node
	$CC $CPPFLAGS $CFLAGS -Wall "$TERMUX_PKG_BUILDER_DIR/camera-list.c" \
		-lcamera2ndk $LDFLAGS -o camera-list
}

termux_step_make_install() {
	local name
	for name in camera-node camera-list; do
		install -Dm755 "$name" "$TERMUX_PREFIX/libexec/android-v4l2/$name"
	done
	# The preload finds its patched back end beside itself.
	for name in libpw-v4l2.so libandroid-v4l2.so; do
		install -Dm755 "$name" "$TERMUX_PREFIX/lib/android-v4l2/$name"
	done
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/camera.py" "$TERMUX_PREFIX/bin/android-v4l2"
}
