#!/bin/bash
# Build the apt repository that install.sh unpacks, from a directory of compiled packages.
# Usage: make-apt-repo.sh DEBS-DIRECTORY OUTPUT-DIRECTORY [SUITE]
# SUITE defaults to livecd, this project's packages, kept in pool/main. Another suite, such as
# offline-repo.py's termux, is added beside it in pool/SUITE, and replaces only an earlier copy of itself.
# Needs apt-ftparchive, from apt-utils. The result is unsigned: install.sh trusts it by path.
set -euo pipefail
debs=$(realpath -- "$1")
suite=${3:-livecd}
pool=pool/main
test "$suite" = livecd || pool=pool/$suite
mkdir -p "$2"
cd -- "$2"
index=dists/$suite/main/binary-aarch64
rm -rf "dists/$suite" "$pool"
mkdir -p "$pool" "$index"
cp -- "$debs"/*.deb "$pool/"
apt-ftparchive packages "$pool" > "$index/Packages"
gzip -9 --keep --no-name "$index/Packages"
# Written elsewhere first, or the Release file would list itself.
release=$(mktemp)
trap 'rm -f -- "$release"' EXIT
apt-ftparchive -o APT::FTPArchive::Release::Suite="$suite" -o APT::FTPArchive::Release::Codename="$suite" \
    -o APT::FTPArchive::Release::Components=main -o APT::FTPArchive::Release::Architectures='aarch64 all' \
    release "dists/$suite" > "$release"
install -m 644 "$release" "dists/$suite/Release"
