#!/bin/bash
# CI-only standalone Android CTS executables, following Khronos' Android recipe.
set -euo pipefail
cts=$(realpath "$1")
target=$2
out=$(realpath -m "$3")
case "$target" in deqp-vk|deqp-gles31) ;; *) exit 2 ;; esac
ndk=${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_HOME:?no NDK}}
mkdir -p "$out/data"
# Android's libandroid depends on the platform EGL. Load Termux EGL and GLES
# by their distinct absolute names when CTS creates the test context.
python3 - "$cts" <<'PYPLATFORM'
from pathlib import Path
import sys
root=Path(sys.argv[1])
p=root/'framework/platform/android/tcuAndroidPlatform.cpp'
s=p.read_text().replace('m_library("libEGL.so")', 'm_library("/data/data/com.termux/files/usr/lib/libEGL.so.1")')
p.write_text(s)
p=root/'framework/egl/egluGLContextFactory.cpp'
s=p.read_text().replace('#define DEQP_GLES2_LIBRARY_PATH "libGLESv2.so"', '#define DEQP_GLES2_LIBRARY_PATH "/data/data/com.termux/files/usr/lib/libGLESv2.so.2"')
p.write_text(s)
PYPLATFORM
git -C "$cts" diff > "$out/PLATFORM.patch"
python3 "$cts/external/fetch_sources.py"
cmake -S "$cts" -B "$cts/build-$target" -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
  -DANDROID_NDK_PATH="$ndk" -DCMAKE_ANDROID_NDK="$ndk" \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-33 -DANDROID_STL=c++_static \
  -DDE_ANDROID_API=33 -DDEQP_TARGET_TOOLCHAIN=ndk-modern \
  -DDEQP_TARGET=android -DDEQP_ANDROID_EXE=ON \
  -DGLES_ALLOW_DIRECT_LINK=OFF -DDEQP_DISABLE_VK_VIDEO_TESTS=ON
cmake --build "$cts/build-$target" --target "$target" --parallel 4
if [ "$target" = deqp-vk ]; then
  cp "$cts/build-$target/external/vulkancts/modules/vulkan/deqp-vk" "$out/"
  cp -a "$cts/external/vulkancts/data/vulkan" "$out/data/"
else
  cp "$cts/build-$target/modules/gles31/deqp-gles31" "$out/"
  mkdir -p "$out/data/gles31"
  cp -a "$cts/data/gles31/data" "$cts/data/gles31/shaders" "$out/data/gles31/"
fi
"$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip" "$out/$target"
{
  printf 'cts=%s\ntarget=%s\nandroid_api=33\n' "$(git -C "$cts" rev-parse HEAD)" "$target"
  cat "$ndk/source.properties"
  cmake --version | head -1
  git -C "$cts" status --short --untracked-files=no
} > "$out/BUILD.txt"
cp "$cts/external/fetch_sources.py" "$out/FETCH-SOURCES.py"
readelf -d "$out/$target" > "$out/DYNAMIC.txt"
(cd "$out" && sha256sum "$target" > SHA256SUMS)
