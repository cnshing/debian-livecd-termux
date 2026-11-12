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

# Keep the unmodified reconstructed driver above as the equivalence control.
# Build our small series incrementally with the same code generators and deps.
mkdir -p "$out/patched"
for patch in "$here"/driver-patches/*.patch; do
  git -C "$mesa" apply --check "$patch"
  git -C "$mesa" apply "$patch"
  git -C "$mesa" add -u
  git -C "$mesa" commit -q -m "livecd: $(basename "$patch")"
done
if [ "$kind" = android ]; then
  MESA="$mesa" BDIR="$zenith/build/android-ci" DDIR="$out/patched" \
    bash "$zenith/scripts/build-android.sh" --profile g615-v11-csf --api 29 \
      --ndk "${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_HOME:?missing NDK}}"
else
  ninja -j4 -C "$zenith/build/glibc-ci"
  cp "$zenith/build/glibc-ci/src/panfrost/vulkan/libvulkan_panfrost.so" "$out/patched/"
  llvm-strip-18 "$out/patched/libvulkan_panfrost.so"
  # The research artifact carries no CI build path in RUNPATH. Its runtime
  # dependencies are supplied privately beside it or via BIONILUX_LIBRARY_PATH.
  patchelf --set-rpath '$ORIGIN' "$out/patched/libvulkan_panfrost.so"
fi
{
  echo "mesa-commit=$(git -C "$mesa" rev-parse HEAD)"
  echo "mesa-tree=$(git -C "$mesa" rev-parse HEAD^{tree})"
  sha256sum "$here"/driver-patches/*.patch
  if [ "$kind" = glibc ]; then echo 'postprocess=patchelf --set-rpath $ORIGIN'; fi
} > "$out/patched/PATCHES.txt"
readelf -d "$out/patched/libvulkan_panfrost.so" > "$out/patched/DYNAMIC.txt"
(cd "$out/patched" && sha256sum libvulkan_panfrost.so > SHA256SUMS)
cat "$out/patched/PATCHES.txt" "$out/patched/DYNAMIC.txt" "$out/patched/SHA256SUMS"
