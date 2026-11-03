TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Native EasyEffects to Termux PulseAudio bridge and AutoEq preset importer"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.1.0"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_DEPENDS="dbus, easyeffects (= 7.2.5), pipewire, pulseaudio, python"
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make_install() {
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/audio.py" "$TERMUX_PREFIX/bin/livecd-audio"
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/autoeq.py" "$TERMUX_PREFIX/bin/livecd-autoeq"
	install -d "$TERMUX_PREFIX/share/applications"
	# A bare command: on our desktop, PATH finds the wrapper that leaves GNOME's private libraries behind.
	cat > "$TERMUX_PREFIX/share/applications/livecd-easyeffects.desktop" <<-DESKTOP
		[Desktop Entry]
		Name=EasyEffects
		Comment=Native audio effects and AutoEq presets
		Exec=livecd-audio ui
		Icon=com.github.wwmm.easyeffects
		Type=Application
		Terminal=false
		Categories=AudioVideo;Audio;Mixer;
	DESKTOP
}
