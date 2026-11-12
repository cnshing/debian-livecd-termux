#!/bin/bash
# New X11/Wayland headers and matching libraries, privately extracted for CI.
# Ubuntu 24.04's xcb 1.15 lacks the release tree's DRI3 1.4 syncobj API.
set -euo pipefail
out=$(realpath -m "$1")
mkdir -p "$out"
docker run --rm -e OUTPUT_UID="$(id -u)" -e OUTPUT_GID="$(id -g)" -v "$out:/w" -w /w debian:sid sh -ec '
  apt-get update -qq
  apt-get download libxcb1 libxcb-dri3-0 libxcb-present0 libxcb-xfixes0 libxcb-sync1 libxcb-randr0 libxcb-shm0 libxcb-render0 libxcb-shape0 libxshmfence1 libwayland-client0 libwayland-cursor0 libwayland-egl1 libwayland-server0 libwayland-bin \
    libxcb1-dev libxcb-dri3-dev libxcb-present-dev libxcb-xfixes0-dev libxcb-sync-dev libxcb-randr0-dev libxcb-shm0-dev libxcb-render0-dev libxcb-shape0-dev libxshmfence-dev libwayland-dev wayland-protocols libx11-dev libx11-xcb-dev x11proto-dev libxau-dev libxdmcp-dev libxml2-16
  for deb in *.deb; do dpkg-deb -x "$deb" root; done
  sha256sum *.deb > PACKAGES.sha256
  chmod -R a+rX root
  chown -R "$OUTPUT_UID:$OUTPUT_GID" root
'
# pkg-config prefixes must refer to this private extraction, never /usr.
find "$out/root/usr" -name '*.pc' -exec sed -i "s|^prefix=/usr$|prefix=$out/root/usr|" {} +
cat "$out/PACKAGES.sha256"
