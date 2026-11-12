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
find root -name 'libSPIRV-Tools*' | sort
spirv=$(find root -name 'libSPIRV-Tools-shared.so*' -type f | head -1)
[ -n "$spirv" ] || { echo "no shared SPIRV-Tools library in spirv-tools" >&2; exit 1; }
cp "$spirv" "$out/lib/"
# The ICD's NEEDED entry is the unversioned build-tree name.
ln -s "$(basename "$spirv")" "$out/lib/libSPIRV-Tools.so"
{
  for deb in *.deb; do echo "$deb $(sha256sum < "$deb" | cut -d' ' -f1)"; done
  echo "glibc-required=$(objdump -T "$out"/lib/*.so* | grep -o 'GLIBC_2\.[0-9]*' | sort -V | tail -1)"
} > "$out/PROVENANCE"
(cd "$out/lib" && sha256sum $(find . -type f | sort)) > "$out/SHA256SUMS"
cat "$out/PROVENANCE"; ls -l "$out/lib"
