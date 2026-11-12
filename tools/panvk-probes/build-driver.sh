#!/bin/bash
# Native CI runner only. Never invokes build-glibc.sh's rooted-device branch.
set -euo pipefail
kind=$1
zenith=$(realpath "$2")
out=$(realpath -m "$3")
here=$(dirname "$(realpath "$0")")
mkdir -p "$out"
mesa="$zenith/work/mesa"
test -f "$mesa/.panvk-patchlevel"
bash "$here/driver-deps.sh" "$zenith/work/ci-deps"
deps="$zenith/work/ci-deps/root/usr"
export PKG_CONFIG_PATH="$deps/lib/aarch64-linux-gnu/pkgconfig:$deps/share/pkgconfig"
export PANVK_JOBS=4
# The native code generators are built from the same reconstructed tree.
export CC=clang-18 CXX=clang++-18
export LLVM_CONFIG=llvm-config-18
export PATH="/usr/lib/llvm-18/bin:$PATH"
bash "$zenith/scripts/bootstrap-host-tools.sh" --mesa "$mesa" --out "$zenith/build/host-tools-ci"
export HOST_TOOLS="$zenith/build/host-tools-ci/bin"
export PATH="$HOST_TOOLS:$PATH"
if [ "$kind" = android ]; then
  export X11_INCLUDE="$deps/include"
  MESA="$mesa" BDIR="$zenith/build/android-ci" DDIR="$out" \
    bash "$zenith/scripts/build-android.sh" --profile g615-v11-csf --api 29 \
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
  cp "$zenith/build/glibc-ci/src/panfrost/vulkan/libvulkan_panfrost.so" "$out/"
  llvm-strip-18 "$out/libvulkan_panfrost.so"
fi
readelf -d "$out/libvulkan_panfrost.so" > "$out/DYNAMIC.txt"
readelf --version-info "$out/libvulkan_panfrost.so" > "$out/VERSIONS.txt"
cp "$zenith/work/ci-deps/PACKAGES.sha256" "$out/DEPENDENCIES.sha256"
{
  echo "kind=$kind"
  echo "zenith=$(git -C "$zenith" rev-parse HEAD)"
  echo "mesa-tree=$(git -C "$mesa" rev-parse HEAD^{tree})"
  meson --version
  clang-18 --version | head -1
  if [ "$kind" = android ]; then
    cat "${ANDROID_NDK_LATEST_HOME:-$ANDROID_NDK_HOME}/source.properties"
  fi
  dpkg-query -W llvm-18-dev libclang-18-dev libclc-18-dev libllvmspirvlib-18-dev spirv-tools
} > "$out/BUILD.txt"
(cd "$out" && sha256sum libvulkan_panfrost.so > SHA256SUMS)
cat "$out/BUILD.txt" "$out/DYNAMIC.txt" "$out/SHA256SUMS"
