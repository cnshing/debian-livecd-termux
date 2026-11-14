#!/bin/bash
# CI only: Android executable and SPIR-V. Never build on the device or host.
set -euo pipefail
headers=$(realpath "$1")/include
mkdir -p "$2"; out=$(realpath "$2")
here=$(dirname "$(realpath "$0")")
ndk=${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_HOME:?no NDK}}
cc="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang"
"$cc" -std=gnu11 -O2 -Wall -Wextra -Werror -I"$headers" \
  -Wno-missing-field-initializers "$here/check.c" -ldl -o "$out/check"
for shape in 128-1-1 256-1-1 257-1-1 511-1-1 512-1-1 513-1-1 769-1-1 1023-1-1 1024-1-1 32-30-1 8-8-16 17-19-3; do
  IFS=- read -r x y z <<< "$shape"
  glslangValidator -V --target-env vulkan1.1 -Od -DX="$x" -DY="$y" -DZ="$z" \
    "$here/check.comp" -o "$out/$shape.spv"
  spirv-val --target-env vulkan1.1 "$out/$shape.spv"
done
for case in nested:1024:1 nested-if:1024:2 nested-control:1024:3 nested-prime:769:1; do
  IFS=: read -r name x kind <<< "$case"
  glslangValidator -V --target-env vulkan1.1 -Od -DX="$x" -DY=1 -DZ=1 -DNESTED="$kind" \
    "$here/check.comp" -o "$out/$name.spv"
  spirv-val --target-env vulkan1.1 "$out/$name.spv"
done
cp "$here/run.py" "$out/"
(cd "$out" && sha256sum check *.spv > SHA256SUMS)
