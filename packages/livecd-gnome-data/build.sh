TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Portable GNOME extensions, fonts and cursors for the native profile"
TERMUX_PKG_LICENSE="GPL-2.0-or-later, GPL-3.0-or-later, LGPL-3.0-or-later, OFL-1.1"
TERMUX_PKG_LICENSE_FILE="licenses/gnome-shell-extension-arc-menu.copyright, licenses/gnome-shell-extension-dash-to-panel.copyright, licenses/gnome-shell-extension-desktop-icons-ng.copyright, licenses/gnome-shell-extension-appindicator.copyright, licenses/gnome-shell-extension-user-theme.copyright, licenses/gnome-shell-extension-no-annoyance.copyright, licenses/gnome-shell-extension-tiling-assistant.copyright, licenses/fonts-noto-core.copyright, licenses/fonts-noto-extra.copyright, licenses/fonts-noto-color-emoji.copyright, licenses/fonts-unifont.copyright, licenses/fonts-hanazono.copyright, licenses/fonts-cantarell.copyright, licenses/adwaita-icon-theme.copyright"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="48.8"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="fontconfig, glib, livecd-gnome-extra-fonts"
# These architecture-independent archives contain readable JS and data only.
# Executables, shared libraries and Debian maintainer scripts are never installed.
TERMUX_PKG_SRCURL=(
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-arc-menu/gnome-shell-extension-arc-menu_65-2_all.deb"
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-dash-to-panel/gnome-shell-extension-dash-to-panel_68-2_all.deb"
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-desktop-icons-ng/gnome-shell-extension-desktop-icons-ng_48.1.0-1_all.deb"
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-appindicator/gnome-shell-extension-appindicator_59-4_all.deb"
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extensions/gnome-shell-extension-user-theme_48.2-1_all.deb"
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-no-annoyance/gnome-shell-extension-no-annoyance_0+20241212-8ca0647-1_all.deb"
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-tiling-assistant/gnome-shell-extension-tiling-assistant_51-2_all.deb"
	"https://deb.debian.org/debian/pool/main/f/fonts-noto/fonts-noto-core_20201225-2_all.deb"
	"https://deb.debian.org/debian/pool/main/f/fonts-noto/fonts-noto-extra_20201225-2_all.deb"
	"https://deb.debian.org/debian/pool/main/f/fonts-noto-color-emoji/fonts-noto-color-emoji_2.051-0+deb13u1_all.deb"
	"https://deb.debian.org/debian/pool/main/u/unifont/fonts-unifont_15.1.01-1_all.deb"
	"https://deb.debian.org/debian/pool/main/f/fonts-hanazono/fonts-hanazono_20170904-3_all.deb"
	"https://deb.debian.org/debian/pool/main/f/fonts-cantarell/fonts-cantarell_0.303.1-4_all.deb"
	"https://deb.debian.org/debian/pool/main/a/adwaita-icon-theme/adwaita-icon-theme_48.1-1_all.deb"
	"https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-arc-menu/gnome-shell-extension-arc-menu_65.orig.tar.gz"
)
TERMUX_PKG_SHA256=(
	07777cc449327d9426ad9c1caf1dec523bb70be39727952319440159390252e6
	48b2424c0ea1aec0f2fb0e0f391c2d166ed2343da4df93a384f954aad4779d2f
	c833d3d164b6cbfddf740f0815156b738524b9200de17190ee579894ca8caa9f
	e0095529f79be06ef35d67d446253695a7feed8336439f2bf768aec08b918395
	77bed4feb016638cc8a0015e354050d41fcd7bc32fd9557827f7ead88d97d3ee
	ff91e53aa40e3f2f3e003c027e539fbf1f2206d8a5e8ccdb5de88baa707b7ce5
	b36bea8041e78b55d15b0cc3c2512efcad76bc46fe07f1aa8160a2007eed53ea
	97978d09b68445fcf85342b106cd2e812d7813e3d5626f9884a5f344c3a55973
	c5e928c74c06dbcb9a19437413d66b40aaa9521847726b74f0e928c9daea43ef
	03141cd51c0e9ff8ad858fcf2d8234f8a00ae4d7a0872df43a71519359c54e8c
	867d447c9b4b139a13c07d27b4f48df4d22e1ef21d29ff5e468a796fd9f2c635
	ead623c26f77cb15874dae03d6f581e890225eacfe3fbe9f0665ecd6f4effd11
	21f8160696cd2b51ac104e735fd63d0e2245cd84cf75f17919f1425dce4ea258
	f60b0577aee314d43d6908ca7f0b8f07dc48e2bb766e7e25035330817e0e827c
	e38aba4038540cc9153f9d10d9742f8f403aeaeec7990dfdd6a2d0476c6a0a23
)

termux_step_post_get_source() {
	local i archive
	for i in "${!TERMUX_PKG_SRCURL[@]}"; do
		archive="$TERMUX_PKG_CACHEDIR/$(basename "${TERMUX_PKG_SRCURL[$i]}")"
		termux_download "${TERMUX_PKG_SRCURL[$i]}" "$archive" "${TERMUX_PKG_SHA256[$i]}"
		case "$archive" in *.deb) dpkg-deb -x "$archive" .;; esac
	done
	python3 "$TERMUX_PKG_BUILDER_DIR/licenses.py" "$TERMUX_PKG_SRCDIR" "$TERMUX_PKG_BUILDER_DIR"
}

termux_step_make_install() {
	python3 "$TERMUX_PKG_BUILDER_DIR/install.py" "$TERMUX_PKG_SRCDIR" \
		"$TERMUX_PREFIX" "$TERMUX_PKG_CACHEDIR" "$TERMUX_PKG_BUILDER_DIR"
}

termux_step_create_debscripts() {
	source "$TERMUX_PKG_BUILDER_DIR/gnome.sh"
	gnome_48_debscripts
}
