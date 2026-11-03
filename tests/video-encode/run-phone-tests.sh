#!/data/data/com.termux/files/usr/bin/bash
# Runs the hardware-encoding suite on the phone against one Bionic stack, set
# up the way the desktop session sets it up for every program: the stack's
# render-node preload, its driver directory for libva, and a daemon. Nothing
# else names a device, a driver or a TERMUX_VA_* setting, except the private
# daemon socket that keeps the shared daemon out of the tests.
#
# Usage: run-phone-tests.sh --stack DIR --daemon PATH --out NEW_DIR
#            [--clients PREFIX]... [--pipewire-src DIR] [--only SUITE]...
#   --stack     a build-native.py output (lib/va-client, lib/dri, the preload)
#   --daemon    the patched termux-va to test
#   --clients   a prefix holding VA-API builds of FFmpeg and GStreamer's va
#               plugin (bin/, lib/, lib/gstreamer-1.0/); repeatable
#   --pipewire-src  a PipeWire 1.4.9 source tree, for the camera test
#   --only      run only this suite: daemon, render-node, gstreamer, ffmpeg or
#               camera; repeatable
set -u
here=$(cd "$(dirname "$0")" && pwd)
stack= daemon= out= clients=() pipewire= only=
while [ $# -gt 0 ]; do
    case $1 in
        --stack) stack=$(cd "$2" && pwd -P); shift 2 ;;
        --daemon) daemon=$2; shift 2 ;;
        --out) out=$2; shift 2 ;;
        --clients) clients+=("$2"); shift 2 ;;
        --pipewire-src) pipewire=$2; shift 2 ;;
        --only) only="$only $2"; shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 2 ;;
    esac
done
[ -n "$stack" ] && [ -n "$daemon" ] && [ -n "$out" ] || { sed -n 2,18p "$0"; exit 2; }
mkdir "$out" || exit 1
out=$(cd "$out" && pwd)

# Programs may only see what an installed system gives them.
for name in $(env | grep -o '^\(LIBVA\|TERMUX_VA\|DMD\)_[A-Z0-9_]*'); do unset "$name"; done
libraries=$stack/lib/va-client path=$PATH plugins=
for prefix in "${clients[@]}"; do
    libraries=$prefix/lib:$libraries
    path=$prefix/bin:$path
    plugins=$prefix/lib/gstreamer-1.0${plugins:+:$plugins}
done
socket=$out/run/termux-va.sock
mkdir "$out/run"
"$daemon" --sock "$socket" -t >"$out/daemon.log" 2>&1 </dev/null &
daemon_pid=$!
trap 'kill $daemon_pid 2>/dev/null; wait $daemon_pid 2>/dev/null' EXIT
for _ in $(seq 100); do [ -S "$socket" ] && break; sleep 0.1; done

session() {
    env LD_LIBRARY_PATH="$libraries" PATH="$path" GST_PLUGIN_PATH="$plugins" GST_REGISTRY="$out/gst-registry.bin" \
        LIBVA_DRIVERS_PATH="$stack/lib/dri" TERMUX_VA_SOCKET="$socket" \
        LD_PRELOAD="$stack/lib/liblivecd-render-node.so${LD_PRELOAD:+ $LD_PRELOAD}" "$@"
}

status=0
suite() {  # suite NAME COMMAND...
    local name=$1
    shift
    case " ${only:-$name} " in *" $name "*) ;; *) return ;; esac
    echo; echo "##### $name"
    "$@" 2>"$out/$name.stderr" | tee "$out/$name.txt"
    local r=${PIPESTATUS[0]}
    echo "##### $name: exit $r"
    [ "$r" -eq 0 ] || status=1
}

env -u LD_PRELOAD clang -O2 -Wall "$here/va-probe.c" -o "$out/va-probe" -I"$stack/include" \
    -I"$PREFIX/include/libdrm" -L"$stack/lib/va-client" -lva -lva-drm -ldrm || exit 1
suite daemon python "$here/test-daemon.py" --daemon "$daemon" --out "$out/daemon"
suite render-node env LD_LIBRARY_PATH="$libraries" PATH="$path" GST_PLUGIN_PATH="$plugins" \
    GST_REGISTRY="$out/gst-registry.bin" LIBVA_DRIVERS_PATH="$stack/lib/dri" TERMUX_VA_SOCKET="$socket" \
    bash "$here/test-render-node.sh" "$stack/lib/liblivecd-render-node.so" "$out/va-probe" "$out/render-node"
suite gstreamer session python "$here/test-gstreamer.py" --out "$out/gstreamer"
suite ffmpeg session python "$here/test-ffmpeg.py" --out "$out/ffmpeg"
if [ -n "$pipewire" ]; then
    suite camera session bash "$here/test-camera-encode.sh" "$pipewire" "$out/camera"
fi
echo; echo "Results in $out"; grep -h '^UNEXPECTED\|passed,\|RESULT' "$out"/*.txt; grep -h '^FAIL' "$out"/{daemon,gstreamer,ffmpeg,camera}.txt 2>/dev/null
exit $status
