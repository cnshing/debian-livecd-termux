TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Fullscreen preference compatibility for Termux:X11 on Samsung Android 11 DeX"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION=0.1.0
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_DEPENDS="python"
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make() {
	# No Termux library dependency: ART loads this inside the Android app.
	$CC $CPPFLAGS $CFLAGS -fPIC -fno-stack-protector -nostdlib -shared \
		-Wl,--no-undefined -Wl,-soname,libdexfullscreen.so \
		"$TERMUX_PKG_BUILDER_DIR/agent.c" -o "$TERMUX_PKG_BUILDDIR/libdexfullscreen.so"
	mkdir -p "$TERMUX_PKG_BUILDDIR/classes" "$TERMUX_PKG_BUILDDIR/dex"
	javac -source 8 -target 8 -classpath "$ANDROID_HOME/platforms/android-35/android.jar" \
		-d "$TERMUX_PKG_BUILDDIR/classes" \
		"$TERMUX_PKG_BUILDER_DIR/java/org/livecd/dexfullscreen/Helper.java"
	"$TERMUX_D8" --release --min-api 30 --lib "$ANDROID_HOME/platforms/android-35/android.jar" \
		--output "$TERMUX_PKG_BUILDDIR/dex" "$TERMUX_PKG_BUILDDIR/classes/org/livecd/dexfullscreen/"*.class
}

termux_step_make_install() {
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/README.md" "$TERMUX_PREFIX/share/doc/android-legacy-dex-fullscreen/README.md"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/controller.py" "$TERMUX_PREFIX/bin/android-legacy-dex-fullscreen"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/device.sh" "$TERMUX_PREFIX/libexec/android-legacy-dex-fullscreen/device.sh"
	install -Dm644 "$TERMUX_PKG_BUILDDIR/libdexfullscreen.so" "$TERMUX_PREFIX/libexec/android-legacy-dex-fullscreen/libdexfullscreen.so"
	install -Dm644 "$TERMUX_PKG_BUILDDIR/dex/classes.dex" "$TERMUX_PREFIX/libexec/android-legacy-dex-fullscreen/helper.dex"
}

termux_step_create_debscripts() {
	cat > prerm <<-PRERM
		#!$TERMUX_PREFIX/bin/sh
		# Stop the old supervisor before an upgrade/removal replaces its controller.
		if test -f "\$HOME/.local/state/android-legacy-dex-fullscreen/session.json"; then
			"$TERMUX_PREFIX/bin/android-legacy-dex-fullscreen" stop || true
		fi
		exit 0
	PRERM
}
