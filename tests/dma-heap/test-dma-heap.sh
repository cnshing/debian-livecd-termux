#!/bin/sh
# Host test for packages/android-vaapi/dma-heap.c against a fake ION device.
set -eu
here=$(cd "$(dirname "$0")" && pwd); src="$here/../../packages/android-vaapi/dma-heap.c"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
cc=${CC:-cc}
$cc -O2 -Wall -Wextra -Werror -shared -fPIC -o "$work/libandroid-dma-heap.so" "$src" -ldl
$cc -O2 -Wall -shared -fPIC -o "$work/libfake-ion.so" "$here/fake-ion.c" -ldl
$cc -O2 -Wall -o "$work/client" "$here/heap-client.c"
: > "$work/ion"; export FAKE_ION="$work/ion" FAKE_ION_LOG="$work/log" HEAP_DIR="$work/dma_heap"
export LIVECD_DMA_HEAP_ION_DEVICE="$work/ion" LIVECD_DMA_HEAP_DIR="$work/dma_heap"
pre="$work/libandroid-dma-heap.so:$work/libfake-ion.so"
fail=0
check() { # name expected-output expected-log env...
    name=$1 want=$2 wantlog=$3; shift 3
    : > "$work/log"
    got=$(env LD_PRELOAD="$pre" "$@" "$work/client" ${HEAP:-system} 1048576 || true)
    log=$(head -1 "$work/log")
    if [ "$got" = "$want" ] && [ "$log" = "$wantlog" ]; then echo "PASS $name"
    else echo "FAIL $name: got '$got' log '$log', want '$want' '$wantlog'"; fail=1; fi
}
check "system is cached ION system heap" ok "mask=0x20 flags=1"
HEAP=system-uncached check "system-uncached is uncached" ok "mask=0x20 flags=0"
check "vendor-named system heap found by type" ok "mask=0x20 flags=1" FAKE_ION_NAME=exynos_sys
HEAP=bogus check "unknown heap name not emulated" "stat No such file or directory" ""
check "no system heap means ENOENT" "open No such file or directory" "" FAKE_ION_NO_SYSTEM=1
check "no ION device means ENOENT" "stat No such file or directory" "" LIVECD_DMA_HEAP_ION_DEVICE="$work/missing"
check "disabled by LIVECD_DMA_HEAP_ION=0" "stat No such file or directory" "" LIVECD_DMA_HEAP_ION=0
mkdir "$work/dma_heap"
check "real heap directory wins" "stat No such file or directory" ""
rmdir "$work/dma_heap"
got=$(LD_PRELOAD="$pre" cat "$here/heap-client.c" | head -1)
case $got in "// Uses only"*) echo "PASS other files pass through";; *) echo "FAIL passthrough"; fail=1;; esac
exit $fail
