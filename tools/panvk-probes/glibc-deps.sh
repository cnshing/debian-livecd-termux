#!/bin/bash
# Usage: glibc-deps.sh <out dir>. Runs on an arm64 Ubuntu runner.
set -euo pipefail
mkdir -p "$1"; out=$(realpath "$1"); work=$(mktemp -d)
pkgs=(libxcb-dri3-0 libxcb-present0 libxcb-xfixes0 libxcb-sync1 libxcb-randr0 libxshmfence1 spirv-tools)
cd "$work"
sudo apt-get update -qq
apt-get download "${pkgs[@]}"
mkdir -p root "$out/lib"
for deb in *.deb; do dpkg-deb -x "$deb" root; done
cp -P root/usr/lib/aarch64-linux-gnu/lib{xcb-dri3,xcb-present,xcb-xfixes,xcb-sync,xcb-randr,xshmfence}.so.* "$out/lib/"
# Ubuntu ships SPIRV-Tools only as static archives. Link the C API into a
# shared library under the ICD's unversioned NEEDED name; build the matching
# upstream tag if the archive is not position-independent.
spirv_link() {
  g++ -shared -o "$out/lib/libSPIRV-Tools.so" -Wl,-soname,libSPIRV-Tools.so \
    -Wl,--whole-archive "$1" -Wl,--no-whole-archive -Wl,--no-undefined
}
if ! spirv_link root/usr/lib/aarch64-linux-gnu/libSPIRV-Tools.a; then
  echo "static archive is not PIC; building SPIRV-Tools from source"
  git clone -q --depth 1 -b v2025.1.rc1 https://github.com/KhronosGroup/SPIRV-Tools.git spirv
  git clone -q --depth 1 -b vulkan-sdk-1.4.309.0 https://github.com/KhronosGroup/SPIRV-Headers.git spirv/external/spirv-headers
  cmake -S spirv -B spirv/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DSPIRV_SKIP_TESTS=ON -DSPIRV_SKIP_EXECUTABLES=ON -DSPIRV_WERROR=OFF >/dev/null
  cmake --build spirv/build --target SPIRV-Tools-static -j"$(nproc)" >/dev/null
  spirv_link spirv/build/source/libSPIRV-Tools.a
  echo "spirv-tools-source=v2025.1.rc1" >> "$out/PROVENANCE.spirv"
fi
nm -D --defined-only "$out/lib/libSPIRV-Tools.so" | grep -E ' spv(BinaryToText|ContextCreate|DiagnosticDestroy|DiagnosticPrint|TextDestroy)$'
{
  for deb in *.deb; do echo "$deb $(sha256sum < "$deb" | cut -d' ' -f1)"; done
  echo "glibc-required=$(objdump -T "$out"/lib/*.so* | grep -o 'GLIBC_2\.[0-9]*' | sort -V | tail -1)"
  cat "$out/PROVENANCE.spirv" 2>/dev/null || true
} > "$out/PROVENANCE"; rm -f "$out/PROVENANCE.spirv"
(cd "$out/lib" && sha256sum $(find . -type f | sort)) > "$out/SHA256SUMS"
cat "$out/PROVENANCE"; ls -l "$out/lib"
