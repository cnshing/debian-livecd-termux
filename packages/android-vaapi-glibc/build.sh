TERMUX_PKG_HOMEPAGE=https://github.com/lfdevs/mesa-for-android-container
TERMUX_PKG_DESCRIPTION="Android hardware video for glibc programs on Adreno and Mali, with Turnip for Adreno"
TERMUX_PKG_LICENSE="custom"
TERMUX_PKG_LICENSE_FILE="COPYRIGHTS"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="27.0.0~devel20261025"
TERMUX_PKG_REVISION=1
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="bionilux, termux-va"
# These are glibc libraries, which Termux's Bionic ELF handling would damage.
TERMUX_PKG_NO_STRIP=true
TERMUX_PKG_NO_ELF_CLEANER=true
TERMUX_PKG_UNDEF_SYMBOLS_FILES="all"
_MESA_URL="https://github.com/lfdevs/mesa-for-android-container/releases/download/mesa-27.0.0-devel-20261025/mesa-for-android-container_27.0.0-devel-20261025_debian_trixie_arm64.tar.gz"
_MESA_SHA256=b711d1d9ab5537ee9085da8896dfe2115e791b33aa317fe37538f276c967d687

termux_step_post_get_source() {
	# lfdevs' glibc Mesa with the Termux:VA bridge, and the Debian trixie libraries it needs.
	termux_download "$_MESA_URL" "$TERMUX_PKG_CACHEDIR/mesa-glibc.tar.gz" "$_MESA_SHA256"
	mkdir -p mesa libraries sysroot
	tar -xzf "$TERMUX_PKG_CACHEDIR/mesa-glibc.tar.gz" -C mesa
	local package url sha snapshot archive
	: > COPYRIGHTS
	while read -r package url sha snapshot; do
		archive="$TERMUX_PKG_CACHEDIR/$(basename "$url")"
		termux_download "$url" "$archive" "$sha" || termux_download "$snapshot" "$archive" "$sha"
		dpkg-deb -x "$archive" "deb-$package"
		cp -P "deb-$package"/usr/lib/aarch64-linux-gnu/*.so* libraries/ 2>/dev/null || true
		printf '\n===== %s =====\n' "$package" >> COPYRIGHTS
		cat "deb-$package"/usr/share/doc/*/copyright >> COPYRIGHTS
	done < <(python3 -c 'import json, sys; [print(i["package"], i["url"], i["sha256"], i.get("snapshot", i["url"])) for i in json.load(open(sys.argv[1]))]' \
		"$TERMUX_PKG_BUILDER_DIR/libraries.lock.json")
	# A complete glibc sysroot for Mesa: never installed as runtime libraries.
	while read -r package url sha snapshot; do
		archive="$TERMUX_PKG_CACHEDIR/$(basename "$url")"
		termux_download "$url" "$archive" "$sha" || termux_download "$snapshot" "$archive" "$sha"
		dpkg-deb -x "$archive" sysroot
	done < <(python3 -c 'import json, sys; [print(i["package"], i["url"], i["sha256"], i["snapshot"]) for i in json.load(open(sys.argv[1]))]' \
		"$TERMUX_PKG_BUILDER_DIR/sysroot.lock.json")
	# Debian merges /lib into /usr/lib with a link from base-files, which is not a library package.
	# glibc's libc.so linker script names /lib/aarch64-linux-gnu/libc.so.6.
	test -e sysroot/lib || ln -s usr/lib sysroot/lib
	# Reuse the Bionic recipe's exact source, patches and ION surface changes.
	local bridge="$TERMUX_PKG_BUILDER_DIR/../android-vaapi" source_url source_sha
	read -r source_url source_sha < <(bash -c 'source "$1"; printf "%s %s\n" "$TERMUX_PKG_SRCURL" "$TERMUX_PKG_SHA256"' \
		- "$bridge/build.sh")
	termux_download "$source_url" "$TERMUX_PKG_CACHEDIR/mesa-va-$source_sha.tar.gz" "$source_sha"
	mkdir -p mesa-mali
	tar -xf "$TERMUX_PKG_CACHEDIR/mesa-va-$source_sha.tar.gz" -C mesa-mali --strip-components=1
	local change
	# Every bridge patch (01xx) of the Bionic recipe; its 00xx patches are Termux's for Bionic.
	for change in "$bridge"/01[0-9][0-9]-*.patch; do
		patch --batch -d mesa-mali -p1 < "$change"
	done
	cp "$bridge/tva_ion.h" "$bridge/tva_ion_winsys.h" mesa-mali/src/gallium/frontends/va/
	python3 "$bridge/configure-bridge.py" mesa-mali/src/gallium/frontends/va/tva_bridge.c
	printf '\n===== mesa-for-android-container =====\n' >> COPYRIGHTS
	cat mesa-mali/docs/license.rst >> COPYRIGHTS
	cat mesa/usr/share/doc/*/copyright >> COPYRIGHTS 2>/dev/null || echo 'MIT, see https://docs.mesa3d.org/license.html' >> COPYRIGHTS
}

termux_step_make() {
	termux_setup_meson
	TERMUX_MESON="$TERMUX_MESON" bash "$TERMUX_PKG_BUILDER_DIR/build-mali.sh" mesa-mali sysroot mali-build mali-stage
	# glibc shared objects, built with Clang's own linker and no C library: they only call into
	# the process's glibc.
	local name
	for name in ion-dma-heap va-completion; do
		$CC --target=aarch64-linux-gnu --sysroot="$PWD/sysroot" -fuse-ld=lld -nostdlib -shared -fPIC \
			-O2 -Wall -Wextra -Werror "$TERMUX_PKG_BUILDER_DIR/$name.c" -o "libandroid-vaapi-$name.so"
	done
}

termux_step_make_install() {
	local private="$TERMUX_PREFIX/lib/android-vaapi-glibc" name folder
	# Mesa keeps its archive layout: the launcher finds glvnd's EGL vendor file beside its usr/lib.
	local mesa="mesa/usr/lib/aarch64-linux-gnu"
	install -d "$private/lib"
	cp -a mesa "$private/mesa"
	cp -P libraries/* "$private/lib/"
	install -m755 libandroid-vaapi-ion-dma-heap.so libandroid-vaapi-va-completion.so "$private/lib/"
	# Mali uses the patched softpipe bridge. Keep lfdevs' Turnip stack beside it.
	install -d "$private/mali/dri"
	cp -P mali-stage/usr/lib/aarch64-linux-gnu/libgallium*.so* "$private/mali/"
	cp -P mali-stage/usr/lib/aarch64-linux-gnu/dri/termuxva_drv_video.so "$private/mali/dri/"
	# A Bionic launcher must never find glibc's own C library here, and libpci exits on Android.
	for folder in "$private/$mesa" "$private/lib" "$private/mali"; do
		for name in libc.so libc.so.6 libdl.so libm.so libpci.so.3; do
			if test -e "$folder/$name" || test -L "$folder/$name"; then
				termux_error_exit "Forbidden library in the glibc stack: $folder/$name"
			fi
		done
	done
	test -f "$private/$mesa/dri/termuxva_drv_video.so"
	test -f "$private/mali/dri/termuxva_drv_video.so"
	python3 - "$private" "$mesa" <<-'PY'
		import json, sys
		from pathlib import Path
		private, mesa = Path(sys.argv[1]), sys.argv[2]
		icd = json.loads((private / 'mesa/usr/share/vulkan/icd.d/freedreno_icd.aarch64.json').read_text())
		icd['ICD']['library_path'] = str(private / mesa / 'libvulkan_freedreno.so')
		(private / 'freedreno_icd.json').write_text(json.dumps(icd, indent=2) + '\n')
		(private / 'manifest.json').write_text(json.dumps({
		    'format': 1, 'abi': 'glibc', 'libraries': [mesa, 'lib'], 'driver_directory': mesa + '/dri',
		    'mesa_library_directory': mesa, 'vulkan_icd': 'freedreno_icd.json',
		    'preloads': [mesa + '/libtva_drm_shim_wayland.so', 'lib/libandroid-vaapi-ion-dma-heap.so'],
		    'completion_preload': 'lib/libandroid-vaapi-va-completion.so', 'ion_fallback': 'preload',
		    'mali': {'libraries': ['mali'], 'driver_directory': 'mali/dri'}}, indent=2) + '\n')
	PY
}
