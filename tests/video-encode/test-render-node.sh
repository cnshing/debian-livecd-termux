#!/data/data/com.termux/files/usr/bin/bash
# Checks the render-node preload on its own and against what it must not
# change. Runs with the caller's VA-API environment (see run-phone-tests.sh)
# and a private Xvfb display; the desktop's display is not used.
# Usage: test-render-node.sh PRELOAD VA_PROBE OUT_DIR
set -u
here=$(cd "$(dirname "$0")" && pwd)
preload=${1:?Usage: test-render-node.sh PRELOAD VA_PROBE OUT_DIR}
probe=${2:?}
out=${3:?}
mkdir "$out" || exit 1
others=${LD_PRELOAD:-}
fails=0
expect() {  # expect pass|fail COMMAND...
    local want=$1 r
    shift
    echo "\$ $*  (expect $want)"
    "$@" </dev/null
    r=$?
    if { [ "$want" = pass ] && [ $r -ne 0 ]; } || { [ "$want" = fail ] && [ $r -eq 0 ]; }; then
        echo "UNEXPECTED: wanted $want, exit $r"
        fails=$((fails + 1))
    fi
}
with_preload() { LD_PRELOAD="$preload${others:+ $others}" "$@"; }
without_preload() { LD_PRELOAD="$others" "$@"; }
same() {  # same LABEL COMMAND...: output must not change under the preload
    local label=$1
    shift
    without_preload "$@" >"$out/$label.without" 2>&1 </dev/null
    with_preload "$@" >"$out/$label.with" 2>&1 </dev/null
    if cmp -s "$out/$label.without" "$out/$label.with"; then
        echo "same output with and without the preload: $label"
    else
        echo "UNEXPECTED: output changed under the preload: $label"
        diff "$out/$label.without" "$out/$label.with" | head -20
        fails=$((fails + 1))
    fi
}

echo "=== the device as files"
expect fail without_preload python "$here/render-node-compat.py"
expect pass with_preload python "$here/render-node-compat.py"

echo; echo "=== finding the encoder the way GStreamer, OBS and Chromium do"
expect fail without_preload "$probe" scan
expect pass with_preload "$probe" scan
with_preload "$probe" scan >"$out/scan.json" 2>/dev/null
expect pass python -c "import json, sys; d = json.load(open('$out/scan.json')); sys.exit(not ({'h264-constrained-baseline', 'h264-high', 'hevc-main'} <= set(d['encoders']) and d['drm_bus'] == 'platform'))"

echo; echo "=== TERMUX_VA_DECODE=0 hides decoders and keeps encoders"
list_va() { GST_REGISTRY="$out/registry-$1.bin" gst-inspect-1.0 va 2>/dev/null | grep -o 'vah26[45]\(enc\|dec\)' | sort | tr '\n' ' '; }
with_decode=$(with_preload list_va decode)
without_decode=$(TERMUX_VA_DECODE=0 with_preload list_va encode)
echo "decoders allowed: $with_decode"
echo "TERMUX_VA_DECODE=0: $without_decode"
expect pass test "$with_decode" = "vah264dec vah264enc vah265dec vah265enc "
expect pass test "$without_decode" = "vah264enc vah265enc "

echo; echo "=== GL is unchanged: Mesa's renderer on a private Xvfb"
# Keep the private server alive between clients; its automatic reset can
# crash after the first GLX connection closes.
Xvfb :87 -noreset -nolisten tcp >"$out/xvfb.log" 2>&1 </dev/null &
xvfb=$!
for _ in $(seq 50); do [ -S "$PREFIX/tmp/.X11-unix/X87" ] && break; sleep 0.1; done
DISPLAY=:87 same glxinfo sh -c 'glxinfo -B | grep -E "OpenGL (renderer|version|vendor)"'
kill $xvfb
# Surfaceless EGL enumerates DRM render nodes, so it meets the new node.
same eglinfo-surfaceless sh -c 'eglinfo -B -p surfaceless 2>&1 | grep -E "OpenGL (core profile |ES )?(renderer|version)"'

echo; echo "=== ordinary programs under the preload"
expect pass with_preload bash -c 'ls -l /dev/dri && cat /sys/class/drm/renderD128/dev'
expect pass with_preload python -c 'import json, sqlite3, ssl, subprocess; print(subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip())'
if command -v clang >/dev/null; then
    expect pass with_preload sh -c 'clang --version | head -1'
else
    echo 'SKIP compiler smoke check: clang is not installed'
fi
bench='import os, time
t = time.perf_counter()
for _ in range(100000):
    os.stat("/data/data/com.termux/files/usr/bin/bash")
    os.close(os.open("/data/data/com.termux/files/usr/bin/bash", os.O_RDONLY))
print(f"stat+open+close: {(time.perf_counter() - t) * 10:.2f} us per round")'
printf 'without preload: '; without_preload python -c "$bench"
printf 'with preload:    '; with_preload python -c "$bench"

echo; echo "RESULT: $fails unexpected"
[ "$fails" -eq 0 ]
