TERMUX_PKG_HOMEPAGE=https://github.com/elementary/code
TERMUX_PKG_DESCRIPTION="elementary's code editor, which the liveCD installs as its text editor"
TERMUX_PKG_LICENSE="GPL-3.0-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="8.4.0"
TERMUX_PKG_SRCURL="https://github.com/elementary/code/archive/refs/tags/${TERMUX_PKG_VERSION}.tar.gz"
TERMUX_PKG_SHA256=b0b523547e2fe785651c37e9a0cd9338eedbbc34f4fa52c085ad172bd7245d6e
# valac supplies libvala, which Code links for its symbol outline.
TERMUX_PKG_DEPENDS="editorconfig-core-c, fontconfig, glib, granite6, gtk3, gtksourceview4, gtkspell3, libgee, libgit2-glib, libhandy, libpeas2, libsoup3, libvte, pango, valac"
TERMUX_PKG_BUILD_DEPENDS="glib-cross"
# Termux has no pkexec for opening files as root.
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
-Dhave_pkexec=false
"

termux_step_pre_configure() {
	# For the build machine's valac, which compiles the Vala sources.
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper
}
