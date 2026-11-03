TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Android microphone and Bluetooth audio devices for native PulseAudio"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.1.0"
TERMUX_PKG_REVISION=2
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_DEPENDS="pulseaudio, python"
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make() {
	$CC $CPPFLAGS $CFLAGS "$TERMUX_PKG_BUILDER_DIR/sco-output.c" \
		$LDFLAGS -lOpenSLES -o "$TERMUX_PKG_BUILDDIR/sco-output"
	mkdir -p "$TERMUX_PKG_BUILDDIR/classes" "$TERMUX_PKG_BUILDDIR/dex"
	javac -source 8 -target 8 \
		-classpath "$ANDROID_HOME/platforms/android-35/android.jar" \
		-d "$TERMUX_PKG_BUILDDIR/classes" \
		"$TERMUX_PKG_BUILDER_DIR/java/org/livecd/mic/AudioRoute.java"
	"$TERMUX_D8" --release --min-api 24 \
		--lib "$ANDROID_HOME/platforms/android-35/android.jar" \
		--output "$TERMUX_PKG_BUILDDIR/dex" \
		"$TERMUX_PKG_BUILDDIR/classes/org/livecd/mic/"*.class
}

termux_step_make_install() {
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/mic.py" "$TERMUX_PREFIX/bin/livecd-mic"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/bluetooth.py" "$TERMUX_PREFIX/bin/livecd-mic-bluetooth"
	install -Dm644 "$TERMUX_PKG_BUILDDIR/dex/classes.dex" "$TERMUX_PREFIX/share/livecd-mic/audio-route.dex"
	install -Dm755 "$TERMUX_PKG_BUILDDIR/sco-output" "$TERMUX_PREFIX/libexec/livecd-mic/sco-output"
}
