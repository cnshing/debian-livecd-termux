TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Source-built GNOME 48 runtime and native session integration"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="48.8"
TERMUX_PKG_REVISION=2
TERMUX_PKG_SRCURL=(
	"https://download.gnome.org/sources/gnome-settings-daemon/48/gnome-settings-daemon-48.1.tar.xz"
	"https://github.com/GNOME/localsearch/archive/refs/tags/3.9.0.tar.gz"
)
TERMUX_PKG_SHA256=(
	3860a2ea214dcbcb6600ae7a1e3358a5389215087bc3e4a47cee3f87baee062e
	6d8d5ff2a2320632e2cd14ef5a9c6a57d67430ac71d36428a257404a81dcf943
)
TERMUX_PKG_DEPENDS="gnome-session, gnome-48-shell (= 48.8-1), fonts-cantarell"
# Renamed from livecd-gnome-runtime.
TERMUX_PKG_CONFLICTS="gnome-48-gi-paths, mutter-x11-frames, livecd-gnome-runtime, livecd-gi-paths"
TERMUX_PKG_REPLACES="livecd-gnome-runtime"
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false

# Only readable schemas are needed from Settings Daemon and LocalSearch.
termux_step_configure() { :; }
termux_step_make() { :; }

termux_step_make_install() {
	python3 "$TERMUX_PKG_BUILDER_DIR/schemas.py" "$TERMUX_PKG_SRCDIR" \
		"$TERMUX_PREFIX/opt/gnome-48"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/livecd-native.session" \
		"$TERMUX_PREFIX/opt/gnome-48/share/gnome-session/sessions/livecd-native.session"
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/gnome-mimeapps.list" \
		"$TERMUX_PREFIX/opt/gnome-48/share/applications/gnome-mimeapps.list"
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	gnome_48_debscripts
}
