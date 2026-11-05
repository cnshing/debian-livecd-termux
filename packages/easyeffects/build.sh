TERMUX_PKG_HOMEPAGE=https://github.com/wwmm/easyeffects
TERMUX_PKG_DESCRIPTION="Native GTK audio effects for PipeWire (Termux experimental port)"
TERMUX_PKG_LICENSE="GPL-3.0-or-later"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="7.2.5"
TERMUX_PKG_REVISION=1
TERMUX_PKG_SRCURL="https://codeload.github.com/wwmm/easyeffects/tar.gz/refs/tags/v${TERMUX_PKG_VERSION}"
TERMUX_PKG_SHA256=d86877b12648a24b3b21a56d16d5680ee2585d575878ecdcea1b9bd9bb428191
TERMUX_PKG_DEPENDS="fftw, fmt, gsl, gtk4, libadwaita, libbs2b, libc++, libebur128, libsamplerate, libsigc++-3.0, libsndfile, libsoundtouch, libtbb, libzita-convolver, lilv, lsp-plugins-lv2, pipewire, pulseaudio, python, speexdsp, dbus"
# easyeffects-bridge, formerly the livecd-audio package, connects it to Termux's PulseAudio.
TERMUX_PKG_CONFLICTS="livecd-audio"
TERMUX_PKG_REPLACES="livecd-audio"
TERMUX_PKG_BUILD_DEPENDS="desktop-file-utils, glib-cross, ladspa-sdk, lv2, nlohmann-json"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Denable-rnnoise=false
-Denable-libcpp-workarounds=true
"

termux_step_pre_configure() {
	termux_setup_glib_cross_pkg_config_wrapper
}

termux_step_post_make_install() {
	# EasyEffects needs PipeWire, and Termux's audio is PulseAudio: the bridge runs it on a private
	# PipeWire whose output is tunnelled to Termux's PulseAudio, and Android plays that.
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/easyeffects-bridge.py" "$TERMUX_PREFIX/bin/easyeffects-bridge"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/easyeffects-autoeq.py" "$TERMUX_PREFIX/bin/easyeffects-autoeq"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/LICENSE.bridge" "$TERMUX_PREFIX/share/doc/easyeffects/LICENSE.bridge"
	install -d "$TERMUX_PREFIX/share/applications"
	# A bare command: on our desktop, PATH finds the wrapper that leaves GNOME's private libraries behind.
	cat > "$TERMUX_PREFIX/share/applications/easyeffects-bridge.desktop" <<-DESKTOP
		[Desktop Entry]
		Name=EasyEffects
		Comment=Native audio effects and AutoEq presets
		Exec=easyeffects-bridge ui
		Icon=com.github.wwmm.easyeffects
		Type=Application
		Terminal=false
		Categories=AudioVideo;Audio;Mixer;
	DESKTOP
}
