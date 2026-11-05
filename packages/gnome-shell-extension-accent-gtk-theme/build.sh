TERMUX_PKG_HOMEPAGE=https://github.com/florintanasa/accent-gtk-theme
TERMUX_PKG_DESCRIPTION="Accent GTK Theme: switches the GTK theme with GNOME's accent color and style"
TERMUX_PKG_LICENSE="GPL-2.0"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="8"
# The extensions.gnome.org release that upstream's live CD bundles, unchanged but for the patches here.
TERMUX_PKG_SRCURL=https://extensions.gnome.org/extension-data/accent-gtk-themebrgvos.v8.shell-extension.zip
TERMUX_PKG_SHA256=448460b61035b23d6f309133af3fd20dc805725c5867af4fe3b1e6ec7880204d
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="gnome-48-shell"
TERMUX_PKG_RECOMMENDS="whitesur-gtk-theme"

termux_step_post_get_source() {
	local archive="$TERMUX_PKG_CACHEDIR/$(basename "$TERMUX_PKG_SRCURL")"
	termux_download "$TERMUX_PKG_SRCURL" "$archive" "$TERMUX_PKG_SHA256"
	python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(".")' "$archive"
}

termux_step_make_install() {
	local extension="$TERMUX_PREFIX/share/gnome-shell/extensions/accent-gtk-theme@brgvos"
	install -d "$extension/schemas"
	install -m644 extension.js prefs.js metadata.json "$extension/"
	install -m644 schemas/* "$extension/schemas/"
}
