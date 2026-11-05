TERMUX_PKG_HOMEPAGE=https://github.com/vinceliuice/Colloid-icon-theme
TERMUX_PKG_DESCRIPTION="Colloid icon theme, in every accent color and in light and dark variants"
TERMUX_PKG_LICENSE="GPL-3.0"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="2026.08.29"
TERMUX_PKG_SRCURL=https://codeload.github.com/vinceliuice/Colloid-icon-theme/tar.gz/ceac6608ecd0e40025cbc2ebbd32bf0e0f4ebc6a
TERMUX_PKG_SHA256=3f731f9f13b1c1403893561ff92adec7b3ab07c5495f55c78c111b07a10a296e
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="hicolor-icon-theme"

termux_step_make_install() {
	# install.sh refreshes each theme's icon cache with a program the build machine may lack.
	# The phone builds the caches after installation instead.
	local tools="$TERMUX_PKG_TMPDIR/tools"
	mkdir -p "$tools"
	printf '#!/bin/sh\nexit 0\n' > "$tools/gtk-update-icon-cache"
	chmod 755 "$tools/gtk-update-icon-cache"
	install -d "$TERMUX_PREFIX/share/icons"
	PATH="$tools:$PATH" bash install.sh --dest "$TERMUX_PREFIX/share/icons" --theme all
	python3 "$TERMUX_PKG_BUILDER_DIR/symbolic.py" "$TERMUX_PREFIX/share/icons"
}

termux_step_create_debscripts() {
	cat > postinst <<-POSTINST
		#!$TERMUX_PREFIX/bin/sh
		for theme in "$TERMUX_PREFIX"/share/icons/Colloid*; do
			"$TERMUX_PREFIX/bin/gtk-update-icon-cache" --quiet --force "\$theme" || true
		done
	POSTINST
	cat > postrm <<-POSTRM
		#!$TERMUX_PREFIX/bin/sh
		test "\$1" = remove || test "\$1" = purge || exit 0
		rm -f "$TERMUX_PREFIX"/share/icons/Colloid*/icon-theme.cache
	POSTRM
}
