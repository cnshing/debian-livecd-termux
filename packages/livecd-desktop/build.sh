TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Native GNOME desktop controller and profile setup"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.2.0"
TERMUX_PKG_REVISION=25
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
# Kept as a conffile, so a deliberate local change or removal survives upgrades.
TERMUX_PKG_CONFFILES="etc/apt/apt.conf.d/50livecd-session-guard"
TERMUX_PKG_DEPENDS="dbus, gnome-48-runtime, android-procfs (>= 1.0.0-1), pulseaudio, python, pygobject, termux-x11-nightly, xdotool, xorg-xdpyinfo, xorg-xprop, xorg-xrandr, xorg-xsetroot, xsettingsd"

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make_install() {
	local file
	for file in "$TERMUX_PKG_BUILDER_DIR/native/"*.py; do
		install -Dm644 "$file" "$TERMUX_PREFIX/libexec/livecd-native/$(basename "$file")"
	done
	for file in livecd livecd-native livecd-accelerate; do
		sed "s|@TERMUX_PREFIX@|$TERMUX_PREFIX|g" "$TERMUX_PKG_BUILDER_DIR/$file" \
			> "$TERMUX_PREFIX/bin/$file"
		chmod 755 "$TERMUX_PREFIX/bin/$file"
	done
	# Lets `pkg install` add packages to a running desktop but not replace ones it has loaded.
	sed "s|@TERMUX_PREFIX@|$TERMUX_PREFIX|g" "$TERMUX_PKG_BUILDER_DIR/apt-session-guard" \
		> "$TERMUX_PREFIX/libexec/livecd-native/apt-session-guard"
	chmod 755 "$TERMUX_PREFIX/libexec/livecd-native/apt-session-guard"
	install -d "$TERMUX_PREFIX/etc/apt/apt.conf.d"
	printf 'DPkg::Pre-Install-Pkgs { "%s"; };\n' "$TERMUX_PREFIX/libexec/livecd-native/apt-session-guard" \
		> "$TERMUX_PREFIX/etc/apt/apt.conf.d/50livecd-session-guard"
}

termux_step_create_debscripts() {
	# runtime.py links each controller module into the profile, but only install.sh runs it.
	# Link modules an upgrade adds, and drop links to modules it removed, so wrappers such as
	# google-chrome keep importing. Profiles not set up yet are left to install.sh.
	cat > postinst <<-POSTINST
		#!$TERMUX_PREFIX/bin/sh
		lib="\$HOME/.local/lib/livecd-native"
		test -n "\$HOME" && test -d "\$lib" || exit 0
		for module in "$TERMUX_PREFIX"/libexec/livecd-native/*.py; do
			link="\$lib/\${module##*/}"
			test -e "\$link" || test -L "\$link" || ln -s "\$module" "\$link" || true
		done
		for link in "\$lib"/*.py; do
			test -L "\$link" && ! test -e "\$link" || continue
			case "\$(readlink "\$link")" in
				"$TERMUX_PREFIX"/libexec/livecd-native/*) rm -f "\$link" ;;
			esac
		done
		exit 0
	POSTINST
}
