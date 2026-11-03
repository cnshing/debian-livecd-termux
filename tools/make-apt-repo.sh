#!/bin/bash
# Build the apt repository that install.sh unpacks, from a directory of compiled packages.
# Usage: make-apt-repo.sh DEBS-DIRECTORY OUTPUT-DIRECTORY
# Needs apt-ftparchive, from apt-utils. The result is unsigned: install.sh trusts it by path.
set -euo pipefail
debs=$(realpath -- "$1")
mkdir -p "$2"
cd -- "$2"
index=dists/livecd/main/binary-aarch64
rm -rf dists pool
mkdir -p pool/main "$index"
cp -- "$debs"/*.deb pool/main/
apt-ftparchive packages pool/main > "$index/Packages"
gzip -9 --keep --no-name "$index/Packages"
# Written elsewhere first, or the Release file would list itself.
release=$(mktemp)
trap 'rm -f -- "$release"' EXIT
apt-ftparchive -o APT::FTPArchive::Release::Suite=livecd -o APT::FTPArchive::Release::Codename=livecd \
    -o APT::FTPArchive::Release::Components=main -o APT::FTPArchive::Release::Architectures='aarch64 all' \
    release dists/livecd > "$release"
install -m 644 "$release" dists/livecd/Release
