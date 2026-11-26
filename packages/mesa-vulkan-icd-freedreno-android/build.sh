TERMUX_PKG_HOMEPAGE=https://github.com/zenithblue-oss/panvk-kbase-android
TERMUX_PKG_DESCRIPTION="Mesa Turnip Vulkan driver for Adreno, built for Android and X11, that presents to Termux:X11 through Android hardware buffers"
TERMUX_PKG_LICENSE="custom"
TERMUX_PKG_LICENSE_FILE="COPYRIGHTS"
TERMUX_PKG_MAINTAINER="@cnshing"
# The Mesa tree of mesa-vulkan-icd-panvk-kbase (Zenith p0175), with its X11 present wait and
# Termux:X11 AHB swapchains (platform patches 0003-0004) and Turnip's switch for them (0101-0102).
# It sits beside the Termux Turnip, which every other program keeps; only the desktop session
# on Termux:X11 selects it (src/native/graphics.py).
TERMUX_PKG_VERSION="26.3.1"
TERMUX_PKG_REVISION=1
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
TERMUX_PKG_SKIP_SRC_EXTRACT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false
# The driver dlopens these X11 libraries for its surfaces.
TERMUX_PKG_DEPENDS="libx11, libxcb, libxshmfence"
# Preserve the pinned CI binary.
TERMUX_PKG_NO_STRIP=true
TERMUX_PKG_NO_ELF_CLEANER=true
TERMUX_PKG_UNDEF_SYMBOLS_FILES="all"
_TURNIP_SOURCE_LOCK=$(dirname "$(realpath "${BASH_SOURCE[0]}")")/source.lock.json
_TURNIP_ICD_API_VERSION=1.4.363
read -r _RELEASE _ANDROID_SHA256 < <(python3 -c '
import json,sys
p=json.load(open(sys.argv[1]))
print(p["release"], p["android_sha256"])
' "$_TURNIP_SOURCE_LOCK")
_SOURCE=https://raw.githubusercontent.com/zenithblue-oss/panvk-kbase-android/cf70e02b918e1864cbcd746a7fefa57b96c673ce

termux_step_post_get_source() {
	termux_download "$_RELEASE/libvulkan_freedreno-android-aarch64.so" android.so "$_ANDROID_SHA256"
	termux_download "$_SOURCE/LICENSES/MIT.txt" MIT.txt c1b07dde7a5abd4538a09090876e5309991a284e657311100815eed234cfed4a
	termux_download "$_SOURCE/NOTICE.md" NOTICE.md 9537624c66bab3ba87d68eb70f71f2749d2dcc1941903caf49c115d45e8cfd05
	{
		echo '===== panvk-kbase-android (Mesa, here built with Turnip) ====='
		cat NOTICE.md MIT.txt
	} > COPYRIGHTS
}

termux_step_make_install() {
	local root="$TERMUX_PREFIX/lib/freedreno-android" name
	install -Dm644 android.so "$root/libvulkan_freedreno.so"
	install -d "$root/x11"
	# The driver dlopens versioned sonames; Termux installs these libraries unversioned.
	# Only the desktop session that selects this driver puts the directory on LD_LIBRARY_PATH.
	for name in libxcb.so.1 libX11-xcb.so.1 libxcb-dri3.so.0 libxcb-present.so.0 libxcb-randr.so.0 \
			libxcb-shm.so.0 libxcb-sync.so.1 libxcb-xfixes.so.0 libxshmfence.so.1; do
		ln -sf "../../${name%%.so*}.so" "$root/x11/$name"
	done
	install -Dm644 "$_TURNIP_SOURCE_LOCK" "$TERMUX_PREFIX/share/doc/$TERMUX_PKG_NAME/SOURCE.json"
	# Not in share/vulkan/icd.d, so the Vulkan loader never offers it to other programs.
	printf '{"file_format_version": "1.0.1", "ICD": {"library_path": "%s", "api_version": "%s"}}\n' \
		"$root/libvulkan_freedreno.so" "$_TURNIP_ICD_API_VERSION" > "$root/freedreno_icd.json"
}
