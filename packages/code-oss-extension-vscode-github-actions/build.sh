TERMUX_PKG_HOMEPAGE=https://github.com/github/vscode-github-actions
TERMUX_PKG_DESCRIPTION="GitHub Actions for Code OSS: workflow runs, logs and workflow file editing"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_LICENSE_FILE="extension/LICENSE.txt"
TERMUX_PKG_MAINTAINER="@cnshing"
# The publisher's own build on Open VSX, as the editor's Extensions view would install it.
# The version the Code OSS port was verified with; see docs/code-oss/README.md.
TERMUX_PKG_VERSION="0.32.3"
TERMUX_PKG_SRCURL=https://open-vsx.org/api/GitHub/vscode-github-actions/${TERMUX_PKG_VERSION}/file/GitHub.vscode-github-actions-${TERMUX_PKG_VERSION}.vsix
TERMUX_PKG_SHA256=058462162cb29d4d22341d912c15dcfa2194774b1e92fc30fcba1a6ca3c91abd
TERMUX_PKG_DEPENDS="code-oss"
# Only unpacked here: the editor is needed at run time, not to build.
TERMUX_PKG_ANTI_BUILD_DEPENDS="code-oss"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false

termux_step_post_get_source() {
	local archive="$TERMUX_PKG_CACHEDIR/$(basename "$TERMUX_PKG_SRCURL")"
	termux_download "$TERMUX_PKG_SRCURL" "$archive" "$TERMUX_PKG_SHA256"
	unzip -q "$archive" 'extension/*'
}

# A built-in extension of the editor: every profile has it, and pkg updates it. One installed
# from the Extensions view still takes precedence.
termux_step_make_install() {
	local destination="$TERMUX_PREFIX/lib/code-oss/resources/app/extensions/GitHub.vscode-github-actions"
	rm -rf "$destination"
	mkdir -p "$destination"
	cp -R extension/. "$destination/"
}
