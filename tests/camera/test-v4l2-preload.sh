#!/data/data/com.termux/files/usr/bin/bash
# Exercises the installed android-v4l2 binaries, camera-node,
# libandroid-v4l2.so and its patched pw-v4l2, against a private PipeWire,
# WirePlumber and D-Bus; the desktop's audio, display and its own camera
# service are not touched. Needs CAMERA granted to com.termux.api, and opens
# the front and rear cameras. Frames are judged only by rate, latency and luma
# levels; no picture is kept.
# Usage: test-v4l2-preload.sh
# For the cameras the desktop itself publishes, see test-desktop-camera.py.
set -u
here=$(cd "$(dirname "$0")" && pwd)
lib=$PREFIX/lib/android-v4l2
node=$PREFIX/libexec/android-v4l2/camera-node

if [ "${1:-}" = --session ]; then
    T=$2
    export XDG_RUNTIME_DIR=$T/run PIPEWIRE_RUNTIME_DIR=$T/run ANDROID_V4L2_DIR=$T/run/android-v4l2
    mkdir -m 700 "$T/run"
    pids=
    trap 'for p in $pids; do kill "$p" 2>/dev/null; done; wait 2>/dev/null' EXIT
    pipewire >"$T/pipewire.log" 2>&1 </dev/null & pids="$pids $!"
    for _ in $(seq 50); do [ -S "$T/run/pipewire-0" ] && break; sleep 0.1; done
    wireplumber --profile=policy >"$T/wireplumber.log" 2>&1 </dev/null & pids="$pids $!"
    sleep 1

    preload="${LD_PRELOAD:+$LD_PRELOAD:}$lib/libandroid-v4l2.so"
    with_preload() { LD_PRELOAD="$preload" "$@"; }
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
    wait_ready() { for _ in $(seq 50); do grep -q 'node ready' "$1" && return; sleep 0.1; done; }

    echo "=== no camera published, preload loaded: the device must not exist"
    expect fail with_preload python "$here/v4l2-compat.py" 0

    read -r front rear < <(android-v4l2 list | python -c '
import json, sys
chosen = {c["facing"]: c["camera"] for c in json.load(sys.stdin)["chosen"]}
print(chosen["front"], chosen["rear"])')
    # libandroid-stub in $PREFIX/lib must not stand in for Android's camera libraries.
    env -u LD_LIBRARY_PATH "$node" --camera="$front" --device=0 --name="Front camera" --stamp \
        >"$T/front.log" 2>&1 </dev/null & pids="$pids $!"
    front_pid=$!
    env -u LD_LIBRARY_PATH "$node" --camera="$rear" --device=1 --name="Rear camera" --stamp \
        >"$T/rear.log" 2>&1 </dev/null & pids="$pids $!"
    rear_pid=$!
    wait_ready "$T/front.log"
    wait_ready "$T/rear.log"

    echo; echo "=== cameras published, preload not loaded: these checks must fail"
    expect fail python "$here/v4l2-compat.py" 0 "Front camera"

    echo; echo "=== idle: both devices listed, neither camera opened"
    expect pass with_preload python "$here/v4l2-compat.py" 0 "Front camera"
    expect pass with_preload python "$here/v4l2-compat.py" 1 "Rear camera"
    expect fail grep -q 'open in' "$T/front.log" "$T/rear.log"

    echo; echo "=== front camera as /dev/video0, plain V4L2 calls"
    expect pass with_preload python "$here/v4l2-read.py" /dev/video0 YUYV 1280 720 300 "Front camera"

    echo; echo "=== switching: rear, then front again"
    expect pass with_preload python "$here/v4l2-read.py" /dev/video1 NV12 1280 720 90 "Rear camera"
    expect pass with_preload python "$here/v4l2-read.py" /dev/video0 NV12 1280 720 90 "Front camera"

    if command -v chromium-browser >/dev/null; then
        echo; echo "=== Chromium (Termux's Bionic build) through its own V4L2 backend"
        expect pass with_preload python "$here/run-chromium.py" "$here/chromium-camera.html" "$T"
    fi

    if command -v clang >/dev/null && clang -O2 -o "$T/libv4l2-read" "$here/libv4l2-read.c" -lv4l2 2>/dev/null; then
        echo; echo "=== rear camera as /dev/video1, through libv4l2's syscall() calls"
        expect pass with_preload "$T/libv4l2-read" /dev/video1 150 "Rear camera"
    fi

    echo; echo "=== ordinary programs under the preload"
    expect pass with_preload bash -c 'ls -l /dev/video0 /dev/video1 && cat /sys/class/video4linux/video*/name'
    expect pass with_preload python -c 'import json, sqlite3, ssl, subprocess; print(subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip())'
    bench='import os, time
t = time.perf_counter()
for _ in range(100000):
    os.stat("/data/data/com.termux/files/usr/bin/bash")
    os.close(os.open("/data/data/com.termux/files/usr/bin/bash", os.O_RDONLY))
print(f"stat+open+close: {(time.perf_counter() - t) * 10:.2f} us per round")'
    printf 'without preload: '; python -c "$bench"
    printf 'with preload:    '; with_preload python -c "$bench"

    # Closed by the 2 s timer, or earlier by Android when the other camera opened.
    echo; echo "=== cameras released 2 s after the last stream"
    sleep 3
    expect pass grep -qx idle "$ANDROID_V4L2_DIR/state/video0"
    expect pass grep -qx idle "$ANDROID_V4L2_DIR/state/video1"

    echo; echo "=== cameras stopped: the devices must disappear"
    kill "$front_pid" "$rear_pid"
    wait "$front_pid" "$rear_pid" 2>/dev/null
    expect fail with_preload python "$here/v4l2-compat.py" 0

    echo; echo "=== front camera node log"; cat "$T/front.log"
    echo; echo "=== rear camera node log"; cat "$T/rear.log"
    echo; echo "RESULT: $fails unexpected"
    [ "$fails" -eq 0 ]
    exit
fi

test -x "$node" || { echo "Install android-v4l2 first." >&2; exit 2; }
T=$(mktemp -d "$PREFIX/tmp/v4l2test.XXXXXX")
chmod 700 "$T"
trap 'rm -rf "$T"' EXIT
dbus-run-session -- bash "$0" --session "$T" 2>&1 | grep --line-buffered -v '^dbus-daemon'
exit "${PIPESTATUS[0]}"
