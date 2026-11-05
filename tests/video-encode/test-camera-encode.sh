#!/data/data/com.termux/files/usr/bin/bash
# Live phone camera into the hardware encoder, through the paths ordinary Linux
# programs use: the camera as /dev/video0 (android-v4l2's
# camera-node and libandroid-v4l2.so preload) and the encoder as /dev/dri/renderD128 (the
# livecd-render-node preload), with both preloads loaded together as the
# desktop session would. A private PipeWire, WirePlumber and D-Bus carry the
# camera; the desktop's own services are not touched.
#
# The caller supplies the VA-API environment the way an installed system would
# (libva and its driver on the library and driver paths, and the daemon's
# socket); see run-phone-tests.sh. Needs CAMERA granted to com.termux.api, and
# opens the front camera.
# Usage: test-camera-encode.sh OUT_DIR
set -u
here=$(cd "$(dirname "$0")" && pwd)
lib=$PREFIX/lib/android-v4l2
node=$PREFIX/libexec/android-v4l2/camera-node

if [ "${1:-}" = --session ]; then
    T=$2 O=$3
    export XDG_RUNTIME_DIR=$T/run PIPEWIRE_RUNTIME_DIR=$T/run ANDROID_V4L2_DIR=$T/run/android-v4l2
    mkdir -m 700 "$T/run"
    pids=
    trap 'for p in $pids; do kill "$p" 2>/dev/null; done; wait 2>/dev/null' EXIT
    pipewire >"$T/pipewire.log" 2>&1 </dev/null & pids="$pids $!"
    for _ in $(seq 50); do [ -S "$T/run/pipewire-0" ] && break; sleep 0.1; done
    wireplumber --profile=policy >"$T/wireplumber.log" 2>&1 </dev/null & pids="$pids $!"
    sleep 1
    front=$(android-v4l2 list | python -c '
import json, sys
print(next(c["camera"] for c in json.load(sys.stdin)["chosen"] if c["facing"] == "front"))')
    env -u LD_LIBRARY_PATH "$node" --camera="$front" --device=0 --name="Front camera" \
        >"$O/camera-node.log" 2>&1 </dev/null & pids="$pids $!"
    for _ in $(seq 50); do grep -q 'node ready' "$O/camera-node.log" && break; sleep 0.1; done
    LD_PRELOAD="$lib/libandroid-v4l2.so${LD_PRELOAD:+ $LD_PRELOAD}" python "$here/test-camera.py" --out "$O"
    exit
fi

out=${1:?Usage: test-camera-encode.sh OUT_DIR}
test -x "$node" || { echo "Install android-v4l2 first." >&2; exit 2; }
mkdir "$out" || exit 1
T=$(mktemp -d "$PREFIX/tmp/camencode.XXXXXX")
chmod 700 "$T"
trap 'rm -rf "$T"' EXIT
dbus-run-session -- bash "$0" --session "$T" "$out" 2>&1 | grep --line-buffered -v '^dbus-daemon\|^tva-va: '
exit "${PIPESTATUS[0]}"
