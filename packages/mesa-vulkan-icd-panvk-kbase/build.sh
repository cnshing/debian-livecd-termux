TERMUX_PKG_HOMEPAGE=https://github.com/zenithblue-oss/panvk-kbase-android
TERMUX_PKG_DESCRIPTION="Mesa PanVK Vulkan driver for Mali GPUs through Android's own mali_kbase kernel driver, for Bionic and glibc programs"
TERMUX_PKG_LICENSE="custom"
TERMUX_PKG_LICENSE_FILE="COPYRIGHTS"
TERMUX_PKG_MAINTAINER="@cnshing"
# Zenith's release tag. driverInfo: Mesa 26.3.0-devel (git-795ca7ff3e, p0175), Mesa 5a07217f + patches.
TERMUX_PKG_VERSION="26.3.1"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
# The Bionic driver dlopens these X11 libraries for its surfaces.
TERMUX_PKG_DEPENDS="libx11, libxcb, libxshmfence"
# Upstream's release binaries are kept byte for byte, and the glibc files are not Bionic ELF.
TERMUX_PKG_NO_STRIP=true
TERMUX_PKG_NO_ELF_CLEANER=true
TERMUX_PKG_UNDEF_SYMBOLS_FILES="all"
_PANVK_SUPPORT_DIR=$(dirname "$(realpath "${BASH_SOURCE[0]}")")
_PANVK_INSTALL_NAME=panvk-kbase
_PANVK_ICD_API_VERSION=1.4.363
_RELEASE=https://github.com/zenithblue-oss/panvk-kbase-android/releases/download/panvk-kbase-v$TERMUX_PKG_VERSION
_BIONIC_SHA256=62c2b3f98ca987d5ab50b6f01e2d2c1c5b3ee995fe93666aa5da9415f65c3348
_GLIBC_SHA256=063bcf0cacd6605458f01530e7fc4f4de43cda7d7a995d9518e1a6e38f5d0db6
_SOURCE=https://raw.githubusercontent.com/zenithblue-oss/panvk-kbase-android/cf70e02b918e1864cbcd746a7fefa57b96c673ce

termux_step_post_get_source() {
	termux_download "$_RELEASE/libvulkan_panfrost-android-aarch64.so" bionic.so "$_BIONIC_SHA256"
	termux_download "$_RELEASE/libvulkan_panfrost-glibc-aarch64.so" glibc.so "$_GLIBC_SHA256"
	termux_download "$_SOURCE/LICENSES/MIT.txt" MIT.txt c1b07dde7a5abd4538a09090876e5309991a284e657311100815eed234cfed4a
	termux_download "$_SOURCE/NOTICE.md" NOTICE.md 9537624c66bab3ba87d68eb70f71f2749d2dcc1941903caf49c115d45e8cfd05
	{
		echo '===== panvk-kbase-android (Mesa PanVK with a mali_kbase backend) ====='
		cat NOTICE.md MIT.txt
	} > COPYRIGHTS
	if test -n "${_PANVK_EXTRA_LICENSE:-}"; then
		cat "$_PANVK_EXTRA_LICENSE" >> COPYRIGHTS
	fi
	# The glibc driver needs newer X11 and Wayland client libraries than Google Chrome bundles:
	# DRI3/Present 1.4 calls (libxcb 1.17) and wl_fixes (Wayland 1.24).
	local package url sha snapshot archive
	mkdir -p glibc-lib
	while read -r package url sha snapshot; do
		archive="$TERMUX_PKG_CACHEDIR/$(basename "$url")"
		termux_download "$url" "$archive" "$sha" || termux_download "$snapshot" "$archive" "$sha"
		dpkg-deb -x "$archive" "deb-$package"
		cp -P "deb-$package"/usr/lib/aarch64-linux-gnu/*.so.* glibc-lib/
		printf '\n===== %s =====\n' "$package" >> COPYRIGHTS
		cat "deb-$package"/usr/share/doc/*/copyright >> COPYRIGHTS
	done < <(python3 -c 'import json, sys; [print(i["package"], i["url"], i["sha256"], i.get("snapshot", i["url"])) for i in json.load(open(sys.argv[1]))]' \
		"$_PANVK_SUPPORT_DIR/libraries.lock.json")
}

termux_step_make() {
	# A glibc shared object built without a C library; see the file's comment.
	$CC --target=aarch64-linux-gnu -fuse-ld=lld -nostdlib -ffreestanding -shared -fPIC -O2 \
		-Wall -Wextra -Werror -Wl,-soname,libSPIRV-Tools.so \
		"$_PANVK_SUPPORT_DIR/spirv-tools-stub.c" -o libSPIRV-Tools.so
}

termux_step_make_install() {
	local root="$TERMUX_PREFIX/lib/$_PANVK_INSTALL_NAME" abi name
	install -Dm644 bionic.so "$root/bionic/libvulkan_panfrost.so"
	install -Dm644 glibc.so "$root/glibc/libvulkan_panfrost.so"
	install -d "$root/bionic/x11" "$root/glibc/lib"
	# The Bionic driver dlopens versioned sonames; Termux installs these libraries unversioned.
	# Only a launcher that wants PanVK puts this directory on LD_LIBRARY_PATH.
	for name in libxcb.so.1 libX11-xcb.so.1 libxcb-dri3.so.0 libxcb-present.so.0 libxcb-randr.so.0 \
			libxcb-shm.so.0 libxcb-sync.so.1 libxcb-xfixes.so.0 libxshmfence.so.1; do
		ln -sf "../../../${name%%.so*}.so" "$root/bionic/x11/$name"
	done
	cp -P glibc-lib/* "$root/glibc/lib/"
	install -m644 libSPIRV-Tools.so "$root/glibc/lib/"
	for name in libc.so libc.so.6 libdl.so libm.so libstdc++.so.6; do
		test ! -e "$root/glibc/lib/$name" || termux_error_exit "Forbidden library in the glibc stack: $name"
	done
	if test -n "${_PANVK_SOURCE_LOCK:-}"; then
		install -Dm644 "$_PANVK_SOURCE_LOCK" "$TERMUX_PREFIX/share/doc/$TERMUX_PKG_NAME/SOURCE.json"
	fi
	for abi in bionic glibc; do
		printf '{"file_format_version": "1.0.1", "ICD": {"library_path": "%s", "api_version": "%s"}}\n' \
			"$root/$abi/libvulkan_panfrost.so" "$_PANVK_ICD_API_VERSION" > "$root/$abi/panfrost_icd.json"
	done
}
