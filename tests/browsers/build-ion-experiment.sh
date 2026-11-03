#!/data/data/com.termux/files/usr/bin/bash
# Termux Clang, with unpacked Debian cross headers. This builds a glibc TEST
# preload, not an Android library, and does not install it anywhere.
# SYSROOT is the directory containing usr/aarch64-linux-gnu and usr/include/va.
set -euo pipefail
sysroot_dir=${1:?Usage: bash build-ion-experiment.sh SYSROOT [OUTPUT.so]}
output_file=${2:-ion-dma-heap.so}
source_dir=$(dirname "$(readlink -f "$0")")
clang --target=aarch64-linux-gnu --sysroot="$sysroot_dir/usr/aarch64-linux-gnu" \
    -isystem "$sysroot_dir/usr/aarch64-linux-gnu/include" -isystem "$sysroot_dir/usr/include" \
    -fuse-ld=lld -nostdlib -O2 -g -Wall -Wextra -Werror -fPIC -shared \
    "$source_dir/ion-dma-heap.c" -o "$output_file"
