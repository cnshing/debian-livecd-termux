TERMUX_PKG_HOMEPAGE=https://gitlab.gnome.org/GNOME/mutter
TERMUX_PKG_DESCRIPTION="Mutter's GTK window frame client, missing from the GNOME-Termux binary bundle"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_LICENSE_FILE="COPYING"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="48.1"
TERMUX_PKG_SRCURL="https://download.gnome.org/sources/mutter/${TERMUX_PKG_VERSION%%.*}/mutter-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=e9970b3d81c76aed1e91f3436a82e7b14c5e32cf55949b1c9a18d0f157bacafc
TERMUX_PKG_DEPENDS="glib, gsettings-desktop-schemas, gtk4, libx11, libxfixes, libxi"
TERMUX_PKG_BUILD_IN_SRC=true

# Only this one program is needed, so Mutter's own meson build is not used. The bundle's
# libmutter runs it from $PREFIX/libexec; a missing client crashes the compositor.
termux_step_configure() {
	: > config.h
}

termux_step_make() {
	# shellcheck disable=SC2046
	$CC $CFLAGS $CPPFLAGS -I. src/frames/*.c -o mutter-x11-frames \
		$(pkg-config --cflags --libs gtk4-x11 gmodule-no-export-2.0 gsettings-desktop-schemas x11 xfixes xi) $LDFLAGS
}

termux_step_make_install() {
	install -Dm755 mutter-x11-frames "$TERMUX_PREFIX/libexec/mutter-x11-frames"
}
