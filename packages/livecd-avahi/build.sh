TERMUX_PKG_HOMEPAGE=https://www.avahi.org/
TERMUX_PKG_DESCRIPTION="mDNS/DNS-SD client and daemon for the native desktop's private bus"
TERMUX_PKG_LICENSE="LGPL-2.1"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION=0.8
TERMUX_PKG_REVISION=1
TERMUX_PKG_SRCURL=https://github.com/avahi/avahi/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz
TERMUX_PKG_SHA256=c15e750ef7c6df595fb5f2ce10cac0fee2353649600e6919ad08ae8871e4945f
TERMUX_PKG_DEPENDS="dbus, glib, libandroid-glob, libdaemon, libexpat, python"
TERMUX_PKG_BUILD_DEPENDS="glib-cross"
TERMUX_PKG_CONFLICTS="avahi"
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
--enable-dbus
--enable-glib
--disable-gobject
--disable-introspection
--disable-libevent
--disable-gdbm
--disable-gtk
--disable-gtk3
--disable-mono
--disable-python
--disable-python-dbus
--disable-qt3
--disable-qt4
--disable-qt5
--disable-autoipd
--disable-compat-libdns_sd
--disable-core-docs
--disable-manpages
--disable-tests
--with-distro=none
ac_cv_func_chroot=no
"

termux_step_pre_configure() {
	autoreconf -fi
	LDFLAGS+=" -landroid-glob"
}

termux_step_post_make_install() {
	install -Dm755 "$TERMUX_PKG_BUILDER_DIR/discovery.py" "$TERMUX_PREFIX/bin/livecd-network-discovery"
	# Only browse remote services; no SSH or other host services are advertised.
	rm -f "$TERMUX_PREFIX/etc/avahi/services/ssh.service" "$TERMUX_PREFIX/etc/avahi/services/sftp-ssh.service"
}
