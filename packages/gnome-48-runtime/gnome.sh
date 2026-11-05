# Shared setup for the ABI-matched GNOME 48 recipes. Each recipe carries a link
# to this file; recipe staging copies its contents into the builder.
gnome_48_setup() {
	termux_setup_gir
	termux_setup_glib_cross_pkg_config_wrapper
	export TERMUX_MESON_ENABLE_SOVERSION=1
	export PKG_CONFIG_PATH="$TERMUX_PREFIX/opt/gnome-48/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
	export GI_GIR_PATH="$TERMUX_PREFIX/opt/gnome-48/share/gir-1.0:$TERMUX_PREFIX/opt/gnome-48/lib/mutter-16:$TERMUX_PREFIX/opt/gnome-48/share/gnome-shell"
	if test "$TERMUX_ON_DEVICE_BUILD" = true; then
		export LD_LIBRARY_PATH="$TERMUX_PREFIX/opt/gnome-48/lib:$TERMUX_PREFIX/opt/gnome-48/lib/mutter-16:$TERMUX_PREFIX/lib"
		export GI_TYPELIB_PATH="$TERMUX_PREFIX/opt/gnome-48/lib/girepository-1.0:$TERMUX_PREFIX/opt/gnome-48/lib/mutter-16:$TERMUX_PREFIX/opt/gnome-48/lib/gnome-shell:$TERMUX_PREFIX/lib/girepository-1.0"
	fi
}

gnome_48_record() {
	python3 "$TERMUX_PKG_BUILDER_DIR/record.py" "$1" \
		"$TERMUX_PREFIX/opt/gnome-48" "$TERMUX_PKG_BUILDER_DIR" \
		"$TERMUX_PKG_VERSION" "$TERMUX_PKG_SRCURL" "$TERMUX_PKG_SHA256"
}

gnome_48_debscripts() {
	cat > postinst <<-EOF
		#!$TERMUX_PREFIX/bin/sh
		set -e
		if test -d "$TERMUX_PREFIX/opt/gnome-48/share/glib-2.0/schemas"; then
			"$TERMUX_PREFIX/bin/glib-compile-schemas" "$TERMUX_PREFIX/opt/gnome-48/share/glib-2.0/schemas"
		fi
	EOF
}
