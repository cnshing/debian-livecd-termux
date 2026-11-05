TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Event-driven Android storage mounts for GIO and the native Files sidebar"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION=1.0.0
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_DEPENDS="gvfs (>= 1.62.0), pygobject, python"
# Renamed from livecd-storage.
TERMUX_PKG_CONFLICTS="livecd-storage"
TERMUX_PKG_REPLACES="livecd-storage"

termux_step_post_get_source() {
	cp "$TERMUX_PKG_BUILDER_DIR/LICENSE" LICENSE
}

termux_step_make_install() {
	local file
	for file in monitor.py storage.py migrate.py protocol.xml; do
		install -Dm644 "$TERMUX_PKG_BUILDER_DIR/$file" "$TERMUX_PREFIX/libexec/android-gvfs/$file"
	done
	install -Dm644 "$TERMUX_PKG_BUILDER_DIR/android-gvfs.monitor" \
		"$TERMUX_PREFIX/share/gvfs/remote-volume-monitors/android-gvfs.monitor"
	install -d "$TERMUX_PREFIX/share/dbus-1/services"
	sed "s|@TERMUX_PREFIX@|$TERMUX_PREFIX|g" "$TERMUX_PKG_BUILDER_DIR/org.gtk.vfs.AndroidVolumeMonitor.service.in" \
		> "$TERMUX_PREFIX/share/dbus-1/services/org.gtk.vfs.AndroidVolumeMonitor.service"
}
