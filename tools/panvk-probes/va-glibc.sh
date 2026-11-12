#!/bin/bash
# Usage: va-glibc.sh <main checkout> <out dir>. Runs in debian:trixie on an arm64 runner.
# Research build: lfdevs' Mesa VA frontend (the Termux:VA bridge) for glibc with softpipe
# only, plus this repository's android-vaapi changes: ION fallback, dma-buf software
# surfaces, encoding and end-of-picture completion.
set -euo pipefail
recipe=$(realpath "$1")/packages/android-vaapi
mkdir -p "$2"; out=$(realpath "$2")
commit=eb3e7fd4f009cab04b1482aad4843c0bde28a786
sha=123af0b3b2f7c83273a51f28367a64054201d524cbfa52f99ba76696e619927a
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential meson ninja-build pkg-config \
  python3-mako python3-yaml python3-packaging bison flex curl ca-certificates patch \
  libdrm-dev libva-dev zlib1g-dev libzstd-dev libexpat1-dev libx11-dev libx11-xcb-dev libxext-dev \
  libxfixes-dev libxcb1-dev libxcb-dri3-dev libxcb-present-dev libxcb-randr0-dev libxcb-sync-dev \
  libxcb-xfixes0-dev libxcb-shm0-dev libxcb-dri2-0-dev libxcb-glx0-dev libxshmfence-dev libxrandr-dev \
  libwayland-dev wayland-protocols >/dev/null
work=$(mktemp -d); cd "$work"
curl -sSfL -o mesa.tar.gz "https://codeload.github.com/lfdevs/mesa-for-android-container/tar.gz/$commit"
echo "$sha  mesa.tar.gz" | sha256sum -c -
tar xzf mesa.tar.gz; cd mesa-for-android-container-$commit
for p in 0100-termux-va-encode.patch 0101-complete-implicit-sync-decodes.patch; do
  patch -p1 < "$recipe/$p"
done
cp "$recipe/tva_ion.h" "$recipe/tva_ion_winsys.h" src/gallium/frontends/va/
awk "/python3 - src\/gallium\/frontends\/va\/tva_bridge.c <<-'PY'/{f=1;next} /^\tPY\$/{f=0} f" "$recipe/build.sh" \
  | sed 's/^\t*//' > edit.py
test -s edit.py
python3 edit.py src/gallium/frontends/va/tva_bridge.c
meson setup build --prefix=/usr --buildtype=release -Dauto_features=disabled \
  -Dplatforms=x11,wayland -Dgallium-drivers=softpipe -Dvulkan-drivers= \
  -Dgallium-va=enabled -Dtermux-va-bridge=enabled \
  -Dvideo-codecs=h264dec,h265dec,vp9dec,av1dec,h264enc,h265enc \
  -Dllvm=disabled -Ddraw-use-llvm=false -Dglx=disabled -Degl=enabled -Dgles1=disabled \
  -Dgles2=enabled -Dopengl=true -Dgbm=enabled -Dglvnd=disabled -Dxmlconfig=disabled \
  -Dbuild-tests=false -Dtools= -Dspirv-tools=disabled
ninja -C build
DESTDIR="$work/stage" ninja -C build install >/dev/null
lib=$work/stage/usr/lib/aarch64-linux-gnu
mkdir -p "$out/dri"
cp -L "$lib"/libgallium-*.so "$out/"
cp -L "$lib/dri/termuxva_drv_video.so" "$out/dri/"
ls -la "$lib/dri" "$out" "$out/dri"
for f in "$out"/libgallium-*.so "$out/dri/termuxva_drv_video.so"; do
  echo "== $f"; readelf -d "$f" | grep -E "NEEDED|RUNPATH|SONAME"
done
strings -a "$out"/libgallium-*.so "$out/dri/termuxva_drv_video.so" | grep -c "software backend on dma-buf surfaces"
{ echo "mesa=$commit"; echo "glibc-required=$(objdump -T "$out"/*.so "$out"/dri/*.so | grep -o 'GLIBC_2\.[0-9]*' | sort -V | tail -1)"
  dpkg-query -W -f='${Package} ${Version}\n' libva-dev libdrm-dev gcc; } > "$out/PROVENANCE"
(cd "$out" && sha256sum *.so dri/*.so > SHA256SUMS); cat "$out/PROVENANCE" "$out/SHA256SUMS"
