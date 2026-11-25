#!/bin/bash
# Native CI runner only. Never invokes build-glibc.sh's rooted-device branch.
set -euo pipefail
kind=$1
zenith=$(realpath "$2")
out=$(realpath -m "$3")
here=$(dirname "$(realpath "$0")")
patch_dir=${PANVK_DRIVER_PATCH_DIR:-$here/driver-patches}
case "${PANVK_BUILD_VARIANT:-research}" in
  research) ;;
  baseline) patch_dir= ;;
  x11) patch_dir="$out/selected-patches"; mkdir -p "$patch_dir"
    cp "$here/driver-patches/0001-termux-x11-sonames.patch" "$patch_dir/" ;;
  point-size) patch_dir="$out/selected-patches"; mkdir -p "$patch_dir"
    cp "$here/driver-patches/0002-v9-per-vertex-point-size.patch" "$patch_dir/" ;;
  workgroups) patch_dir="$here/workgroup-patches" ;;
  memory-budget) patch_dir="$here/budget-patches" ;;
  ion-cache) patch_dir="$here/ion-patches" ;;
  import-coherence) patch_dir="$out/selected-patches"; mkdir -p "$patch_dir"
    cp "$here/ion-patches/"*.patch "$here/coherence-patches/"*.patch "$patch_dir/" ;;
  combined|combined-platform|combined-ahb|combined-ahb-trace) patch_dir="$out/selected-patches"; mkdir -p "$patch_dir"
    cp "$here/workgroup-patches/"*.patch "$here/budget-patches/"*.patch \
      "$here/ion-patches/"*.patch "$here/coherence-patches/"*.patch \
      "$here/driver-patches/0002-v9-per-vertex-point-size.patch" "$patch_dir/" ;;
  # Turnip (Adreno/KGSL) from the same tree: the shared X11 WSI parts only (render
  # wait 0003, AHB transport 0004) and Turnip's own opt-in switch.
  turnip-ahb) patch_dir="$out/selected-patches"; mkdir -p "$patch_dir"
    cp "$here/platform-patches/0003-"*.patch "$here/platform-patches/0004-"*.patch \
      "$here/turnip-patches/"*.patch "$patch_dir/" ;;
  *) echo 'Unknown PANVK_BUILD_VARIANT' >&2; exit 1 ;;
esac
if [[ "${PANVK_BUILD_VARIANT:-research}" = combined-platform || "${PANVK_BUILD_VARIANT:-research}" = combined-ahb || "${PANVK_BUILD_VARIANT:-research}" = combined-ahb-trace ]]; then
  cp "$here/platform-patches/"*.patch "$patch_dir/"
fi
if [ "${PANVK_BUILD_VARIANT:-research}" = combined-ahb-trace ]; then
  cp "$here/ahb-trace-patches/"*.patch "$patch_dir/"
fi
if [ "${PANVK_BUILD_VARIANT:-research}" = combined-ahb ]; then
  cp "$here/ahb-patches/"*.patch "$patch_dir/"
fi
lib=libvulkan_panfrost.so
android_build="$zenith/scripts/build-android.sh"
if [ "${PANVK_BUILD_VARIANT:-research}" = turnip-ahb ]; then
  test "$kind" = android
  # Zenith's Android+X11 build with Turnip in place of PanVK. msm keeps libdrm (static)
  # and with it the DRI3 path that the same build uses when AHB is not requested.
  lib=libvulkan_freedreno.so
  android_build="$zenith/scripts/build-android-turnip.sh"
  sed -e 's/-Dvulkan-drivers=panfrost -Dpanfrost-kmds=kbase/-Dvulkan-drivers=freedreno -Dfreedreno-kmds=msm,kgsl/' \
      -e 's/libvulkan_panfrost\.so/libvulkan_freedreno.so/g' \
      "$zenith/scripts/build-android.sh" > "$android_build"
  grep -q 'freedreno-kmds=msm,kgsl' "$android_build"
  ! grep -q panfrost "$android_build"
fi
mkdir -p "$out"
mesa="$zenith/work/mesa"
test -f "$mesa/.panvk-patchlevel"
bash "$here/driver-deps.sh" "$zenith/work/ci-deps"
deps="$zenith/work/ci-deps/root/usr"
triplet=$(gcc -dumpmachine)
export PKG_CONFIG_PATH="$deps/lib/$triplet/pkgconfig:$deps/share/pkgconfig"
export PANVK_JOBS=4
# The native code generators are built from the same reconstructed tree.
export CC=clang-18 CXX=clang++-18
export LLVM_CONFIG=llvm-config-18
export PATH="$deps/bin:/usr/lib/llvm-18/bin:$PATH"
bash "$zenith/scripts/bootstrap-host-tools.sh" --mesa "$mesa" --out "$zenith/build/host-tools-ci"
export HOST_TOOLS="$zenith/build/host-tools-ci/bin"
export PATH="$HOST_TOOLS:$PATH"
if [ "$kind" = android ]; then
  export X11_INCLUDE="$deps/include"
  bash "$zenith/scripts/prepare-x11-headers.sh" "$zenith/work/android-deps-x11"
  # Only the generated header-only .pc files may enter the NDK target.
  # Host pkg-config paths otherwise override pkg_config_libdir in the cross file.
  unset PKG_CONFIG_PATH
  MESA="$mesa" BDIR="$zenith/build/android-ci" DDIR="$out" \
    bash "$android_build" --profile g615-v11-csf --api 29 \
      --ndk "${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_HOME:?missing NDK}}"
else
  test "$kind" = glibc
  test "$(uname -m)" = aarch64
  export LD_LIBRARY_PATH="$deps/lib/aarch64-linux-gnu"
  meson setup "$zenith/build/glibc-ci" "$mesa" \
    -Dbuildtype=release -Dplatforms=x11,wayland -Dgallium-drivers= \
    -Dvulkan-drivers=panfrost -Dpanfrost-kmds=kbase \
    -Dmesa-clc=system -Dprecomp-compiler=system -Dxlib-lease=disabled \
    -Degl=disabled -Dgles1=disabled -Dgles2=disabled -Dopengl=false \
    -Dglx=disabled -Dgbm=disabled -Dzstd=disabled -Dlibunwind=disabled
  ninja -j4 -C "$zenith/build/glibc-ci"
  cp "$zenith/build/glibc-ci/src/panfrost/vulkan/$lib" "$out/"
  llvm-strip-18 "$out/$lib"
  # Runtime libraries come from the package's glibc/lib directory, selected by
  # BIONILUX_LIBRARY_PATH. A CI-only RUNPATH must never ship in a package.
  patchelf --remove-rpath "$out/$lib"
fi
readelf -d "$out/$lib" > "$out/DYNAMIC.txt"
readelf --version-info "$out/$lib" > "$out/VERSIONS.txt"
cp "$zenith/work/ci-deps/PACKAGES.sha256" "$out/DEPENDENCIES.sha256"
{
  echo "kind=$kind"
  echo "variant=${PANVK_BUILD_VARIANT:-research}"
  echo "zenith=$(git -C "$zenith" rev-parse HEAD)"
  echo "mesa-tree=$(git -C "$mesa" rev-parse HEAD^{tree})"
  meson --version
  clang-18 --version | head -1
  if [ "$kind" = android ]; then
    cat "${ANDROID_NDK_LATEST_HOME:-$ANDROID_NDK_HOME}/source.properties"
  fi
  dpkg-query -W llvm-18-dev libclang-18-dev libclc-18-dev libllvmspirvlib-18-dev spirv-tools
} > "$out/BUILD.txt"
(cd "$out" && sha256sum $lib > SHA256SUMS)
cat "$out/BUILD.txt" "$out/DYNAMIC.txt" "$out/SHA256SUMS"

# A source-built baseline is the package qualification control. No driver
# patch (including the X11 soname patch) is applied to this variant.
if [ "${PANVK_BUILD_VARIANT:-research}" = baseline ]; then
  exit 0
fi

# Keep the unmodified reconstructed driver above as the equivalence control.
# Build our small series incrementally with the same code generators and deps.
mkdir -p "$out/patched"
for patch in "$patch_dir"/*.patch; do
  git -C "$mesa" apply --check "$patch"
  git -C "$mesa" apply "$patch"
  git -C "$mesa" add -u
  git -C "$mesa" commit -q -m "livecd: $(basename "$patch")" -m 'Generated-by: LLM'
done
if [ "$kind" = android ]; then
  MESA="$mesa" BDIR="$zenith/build/android-ci" DDIR="$out/patched" \
    bash "$android_build" --profile g615-v11-csf --api 29 \
      --ndk "${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_HOME:?missing NDK}}"
else
  ninja -j4 -C "$zenith/build/glibc-ci"
  cp "$zenith/build/glibc-ci/src/panfrost/vulkan/$lib" "$out/patched/"
  llvm-strip-18 "$out/patched/$lib"
  # The research artifact carries no CI build path in RUNPATH. Its runtime
  # dependencies are supplied privately beside it or via BIONILUX_LIBRARY_PATH.
  patchelf --set-rpath '$ORIGIN' "$out/patched/$lib"
fi
if [ "${PANVK_KEEP_SYMBOLS:-0}" = 1 ]; then
  case "$kind" in
    android) symbol_file=$(find "$zenith/build/android-ci" -name $lib -print -quit) ;;
    glibc) symbol_file="$zenith/build/glibc-ci/src/panfrost/vulkan/$lib" ;;
  esac
  install -Dm644 "$symbol_file" "$out/patched/symbols/$lib"
fi
{
  echo "mesa-commit=$(git -C "$mesa" rev-parse HEAD)"
  echo "mesa-tree=$(git -C "$mesa" rev-parse HEAD^{tree})"
  sha256sum "$patch_dir"/*.patch
  if [ "$kind" = glibc ]; then echo 'postprocess=patchelf --set-rpath $ORIGIN'; fi
} > "$out/patched/PATCHES.txt"
readelf -d "$out/patched/$lib" > "$out/patched/DYNAMIC.txt"
(cd "$out/patched" && sha256sum $lib > SHA256SUMS)
cat "$out/patched/PATCHES.txt" "$out/patched/DYNAMIC.txt" "$out/patched/SHA256SUMS"
