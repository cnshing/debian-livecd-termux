#!/bin/bash
# Usage: build.sh <zenith checkout> <Vulkan-Headers checkout> <out dir>
set -euo pipefail
src=$(realpath "$1")/tests
vk=$(realpath "$2")/include
kb=$(realpath "$1")/patches/kbase-common/files/include
here=$(dirname "$(realpath "$0")")
mkdir -p "$3"; out=$(realpath "$3")
ndk=${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_HOME:?no NDK on this runner}}
cc="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang"

# Offscreen triangles: dump the full readback; see add-dump.py.
python3 "$here/add-dump.py" "$src/offscreen/triangle.c" "$out/triangle-dump.c"
python3 "$here/add-dump.py" --top-left-oracle "$src/offscreen/triangle_vb.c" "$out/triangle-vb-dump.c"
python3 "$here/add-dump.py" --top-left-oracle "$src/offscreen/triangle_const.c" "$out/triangle-const-dump.c"

build() { # name source... -- extra flags
  local name=$1; shift
  echo "== $name"
  "$cc" -std=gnu11 -O2 -Wall -I"$vk" "$@" -ldl -lm -o "$out/$name"
}
build enumerate "$src/vulkan-smoke/enumerate.c"
build compute -I"$src/compute" "$src/compute/compute.c"
build triangle -I"$src/offscreen" "$out/triangle-dump.c"
build triangle-vb -I"$src/offscreen" "$out/triangle-vb-dump.c"
build triangle-const -I"$src/offscreen" "$out/triangle-const-dump.c"
build sync -I"$src/compute" "$src/sync/sync_test.c"
build handshake -I"$kb" "$src/kbase-probe/handshake.c"
rm "$out"/triangle*-dump.c
{
  echo "zenith=$(git -C "$1" rev-parse HEAD)"
  echo "vulkan-headers=$(git -C "$2" describe --tags --always)"
  echo "ndk=$(sed -n 's/^Pkg.Revision *= *//p' "$ndk/source.properties")"
} > "$out/PROVENANCE"
(cd "$out" && sha256sum enumerate compute triangle triangle-vb triangle-const sync handshake > SHA256SUMS)
cat "$out/PROVENANCE" "$out/SHA256SUMS"
