TERMUX_PKG_HOMEPAGE=https://github.com/cnshing/debian-livecd-termux
TERMUX_PKG_DESCRIPTION="Qualified private Ghostty GTK GL DMA-BUF stack for Mali-G77 x1s"
TERMUX_PKG_LICENSE="custom"
TERMUX_PKG_LICENSE_FILE="COPYRIGHTS"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="1.0"
TERMUX_PKG_REVISION=2
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_NO_STRIP=true
TERMUX_PKG_NO_ELF_CLEANER=true
TERMUX_PKG_UNDEF_SYMBOLS_FILES="all"
TERMUX_PKG_DEPENDS="adwaita-icon-theme, fontconfig, fribidi, gdk-pixbuf, ghostty (>= 1.4.0), glib, graphene, gtk-update-icon-cache, gtk4 (>= 4.24.1), harfbuzz, iso-codes, libandroid-shmem, libc++, libcairo, libdrm, libepoxy, libglvnd, libjpeg-turbo, libllvm (<< 22), libpng, librsvg, libtiff, libwayland, libx11, libxcursor, libxdamage, libxext, libxfixes, libxi, libxinerama, libxkbcommon, libxrandr, libxshmfence, libxxf86vm, ncurses, pango, python, shared-mime-info, vulkan-loader, zlib, zstd"

termux_step_post_get_source() {
    local url sha file
    read -r url sha file < <(python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); print(p["release"],p["sha256"],p["file"])' "$TERMUX_PKG_BUILDER_DIR/release.lock.json")
    termux_download "$url/$file" stack.deb "$sha"
    dpkg-deb -x stack.deb unpacked
    cat unpacked/data/data/com.termux/files/usr/share/doc/ghostty-panvk-dmabuf/*LICENSE* \
        unpacked/data/data/com.termux/files/usr/share/doc/ghostty-panvk-dmabuf/GTK-COPYING > COPYRIGHTS
}

termux_step_make_install() {
    cp -a unpacked/data/data/com.termux/files/usr/. "$TERMUX_PREFIX/"
}
