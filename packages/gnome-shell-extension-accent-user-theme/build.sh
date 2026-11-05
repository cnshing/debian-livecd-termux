TERMUX_PKG_HOMEPAGE=https://github.com/florintanasa/accent-user-theme
TERMUX_PKG_DESCRIPTION="Accent User Theme: switches the GNOME Shell theme with GNOME's accent color and style"
TERMUX_PKG_LICENSE="GPL-2.0"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="3"
# The extensions.gnome.org release that upstream's live CD bundles, unchanged but for the patches here.
TERMUX_PKG_SRCURL=https://extensions.gnome.org/extension-data/accent-user-themebrgvos.v3.shell-extension.zip
TERMUX_PKG_SHA256=738911893fe13caba245991241947544f62de7a2393619d233d74dca949ecd29
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
# It reads User Themes' global org.gnome.shell.extensions.user-theme schema.
TERMUX_PKG_DEPENDS="gnome-48-shell, gnome-shell-extension-user-theme"
TERMUX_PKG_RECOMMENDS="whitesur-gtk-theme"

termux_step_post_get_source() {
	local archive="$TERMUX_PKG_CACHEDIR/$(basename "$TERMUX_PKG_SRCURL")"
	termux_download "$TERMUX_PKG_SRCURL" "$archive" "$TERMUX_PKG_SHA256"
	python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(".")' "$archive"
}

termux_step_make_install() {
	local extension="$TERMUX_PREFIX/share/gnome-shell/extensions/accent-user-theme@brgvos"
	install -d "$extension/schemas"
	install -m644 extension.js prefs.js metadata.json "$extension/"
	install -m644 schemas/* "$extension/schemas/"
}
