#!/data/data/com.termux/files/usr/bin/bash
# Mixtapes mints PO tokens for uploaded songs with rustypipe-botguard, an aarch64 glibc program.
# glibc and its OpenSSL come from Termux's separate glibc repository.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt=(apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
"${apt[@]}" install glibc-repo
apt-get update
"${apt[@]}" install --no-install-recommends glibc openssl-glibc
