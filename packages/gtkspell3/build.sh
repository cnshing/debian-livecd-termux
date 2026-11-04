TERMUX_PKG_HOMEPAGE=https://gtkspell.sourceforge.net/
TERMUX_PKG_DESCRIPTION="Spell checking for GTK 3 text views"
TERMUX_PKG_LICENSE="GPL-2.0-or-later"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="3.0.10"
TERMUX_PKG_SRCURL="https://downloads.sourceforge.net/gtkspell/gtkspell3-${TERMUX_PKG_VERSION}.tar.xz"
TERMUX_PKG_SHA256=b040f63836b347eb344f5542443dc254621805072f7141d49c067ecb5a375732
TERMUX_PKG_DEPENDS="enchant, glib, gtk3, iso-codes"
TERMUX_PKG_BUILD_DEPENDS="g-ir-scanner, valac"
TERMUX_PKG_DISABLE_GIR=false
TERMUX_PKG_VERSIONED_GIR=false
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
--enable-introspection=yes
--enable-vala=yes
--disable-gtk-doc
"

termux_step_pre_configure() {
	termux_setup_gir
}
