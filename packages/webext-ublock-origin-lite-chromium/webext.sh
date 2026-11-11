# Shared by the webext recipes; symlinks are materialized by recipes.py prepare.
termux_step_post_get_source() {
	local suffix=crx
	[ "$_WEBEXT_BROWSER" != firefox ] || suffix=xpi
	termux_download "$TERMUX_PKG_SRCURL" "$TERMUX_PKG_CACHEDIR/$TERMUX_PKG_NAME-$TERMUX_PKG_VERSION.$suffix" "$TERMUX_PKG_SHA256"
	cp "$TERMUX_PKG_CACHEDIR/$TERMUX_PKG_NAME-$TERMUX_PKG_VERSION.$suffix" "$TERMUX_PKG_SRCDIR/extension.$suffix"
	python3 "$TERMUX_PKG_BUILDER_DIR/archive.py" "$TERMUX_PKG_SRCDIR/extension.$suffix" \
		"$_WEBEXT_BROWSER" "$_WEBEXT_ID" "$TERMUX_PKG_VERSION"
	local license
	for license in "$TERMUX_PKG_BUILDER_DIR/"LICENSE*; do
		[ ! -f "$license" ] || cp "$license" "$TERMUX_PKG_SRCDIR/"
	done
}

termux_step_make_install() {
	if [ "$_WEBEXT_BROWSER" = firefox ]; then
		install -Dm644 "$TERMUX_PKG_SRCDIR/extension.xpi" \
			"$TERMUX_PREFIX/share/mozilla/extensions/{ec8030f7-c20a-464f-9b0e-13a3a9e97384}/$_WEBEXT_ID.xpi"
	else
		local archive="$TERMUX_PREFIX/share/webext/$_WEBEXT_ID.crx"
		install -Dm644 "$TERMUX_PKG_SRCDIR/extension.crx" "$archive"
		local directory
		for directory in lib/chromium/extensions opt/google/chrome/extensions \
			opt/livecd-browsers/chromium-extensions opt/livecd-browsers/ungoogled-chromium-extensions; do
			install -d "$TERMUX_PREFIX/$directory"
			# Each browser keeps its own registration; the signed payload is stored once.
			ln -sf "$archive" "$TERMUX_PREFIX/$directory/$_WEBEXT_ID.crx"
			printf '{"external_crx":"%s","external_version":"%s"}\n' "$archive" "$TERMUX_PKG_VERSION" \
				> "$TERMUX_PREFIX/$directory/$_WEBEXT_ID.json"
		done
	fi
}
