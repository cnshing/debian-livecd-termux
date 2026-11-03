#!/data/data/com.termux/files/usr/bin/bash
# Exercises the camera node, the livecd-v4l2 preload and patched pw-v4l2 against
# a private PipeWire, WirePlumber and D-Bus; the desktop's audio and display are
# not touched. Needs CAMERA granted to com.termux.api, and opens the front
# (ID 1) and back (ID 0) cameras.
# Usage: test-v4l2-preload.sh PIPEWIRE_SRC [FRAME_DIR]
#   PIPEWIRE_SRC: a PipeWire 1.4.9 source tree
#   FRAME_DIR: where to keep the last front-camera frame (1280x720 YUYV) and
#              Chromium's JPEG for a pixel check; by default they are deleted
#              with the other output
set -u
here=$(cd "$(dirname "$0")" && pwd)

if [ "${1:-}" = --session ]; then
    T=$2
    export XDG_RUNTIME_DIR=$T/run PIPEWIRE_RUNTIME_DIR=$T/run
    mkdir -m 700 "$T/run"
    pids=
    trap 'for p in $pids; do kill "$p" 2>/dev/null; done; wait 2>/dev/null' EXIT
    pipewire >"$T/pipewire.log" 2>&1 </dev/null & pids="$pids $!"
    for _ in $(seq 50); do [ -S "$T/run/pipewire-0" ] && break; sleep 0.1; done
    wireplumber --profile=policy >"$T/wireplumber.log" 2>&1 </dev/null & pids="$pids $!"
    sleep 1

    preload="${LD_PRELOAD:+$LD_PRELOAD }$T/lib/liblivecd-v4l2.so"
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
    wait_ready() { for _ in $(seq 50); do grep -q ready "$1" && return; sleep 0.1; done; }

    echo "=== no camera published, preload loaded: the device must not exist"
    expect fail with_preload python "$here/v4l2-compat.py" 0

    "$T/camnode" 1 1280 720 30 0 --device=0 --stamp >"$T/front.log" 2>&1 </dev/null & pids="$pids $!"
    front=$!
    "$T/camnode" 0 1280 720 30 0 --device=1 --stamp >"$T/back.log" 2>&1 </dev/null & pids="$pids $!"
    back=$!
    wait_ready "$T/front.log"
    wait_ready "$T/back.log"

    echo; echo "=== cameras published, preload not loaded: these checks must fail"
    expect fail python "$here/v4l2-compat.py" 0 "Phone camera 1"
    expect fail "$T/libv4l2-read" /dev/video1 30

    echo; echo "=== front camera as /dev/video0, plain V4L2 calls"
    expect pass with_preload python "$here/v4l2-compat.py" 0 "Phone camera 1"
    expect pass with_preload python "$here/v4l2-read.py" /dev/video0 YUYV 1280 720 300 "$T/front-yuyv.raw" "Phone camera 1"

    echo; echo "=== efficiency: the same stream through pw-v4l2 alone, then through this preload"
    summary() { grep -E 'fps|median|CPU' | sed -E 's/exposure start to application: //; s/this process //' | tr '\n' ';'; echo; }
    for _ in 1 2; do
        printf 'pw-v4l2 alone: '
        LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD }$T/lib/libpw-v4l2.so" python "$here/v4l2-read.py" /dev/video0 YUYV 1280 720 300 </dev/null | summary
        printf 'livecd-v4l2:   '
        with_preload python "$here/v4l2-read.py" /dev/video0 YUYV 1280 720 300 </dev/null | summary
    done

    if command -v chromium-browser >/dev/null; then
        echo; echo "=== Chromium (Termux's Bionic build) through its own V4L2 backend"
        expect pass with_preload python "$here/run-chromium.py" "$here/chromium-camera.html" "$T"
    fi

    echo; echo "=== back camera as /dev/video1, through libv4l2's syscall() calls"
    expect pass with_preload python "$here/v4l2-compat.py" 1 "Phone camera 0"
    expect pass with_preload "$T/libv4l2-read" /dev/video1 150 "Phone camera 0"

    echo; echo "=== ordinary programs under the preload"
    expect pass with_preload bash -c 'ls -l /dev/video0 /dev/video1 && cat /sys/class/video4linux/video*/name'
    expect pass with_preload python -c 'import json, sqlite3, ssl, subprocess; print(subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip())'
    expect pass with_preload sh -c 'clang --version | head -1'
    bench='import os, time
t = time.perf_counter()
for _ in range(100000):
    os.stat("/data/data/com.termux/files/usr/bin/bash")
    os.close(os.open("/data/data/com.termux/files/usr/bin/bash", os.O_RDONLY))
print(f"stat+open+close: {(time.perf_counter() - t) * 10:.2f} us per round")'
    printf 'without preload: '; python -c "$bench"
    printf 'with preload:    '; with_preload python -c "$bench"

    echo; echo "=== cameras stopped: the devices must disappear"
    kill "$front" "$back"
    wait "$front" "$back" 2>/dev/null
    expect fail with_preload python "$here/v4l2-compat.py" 0

    echo; echo "=== front camera node log"; cat "$T/front.log"
    echo; echo "=== back camera node log"; cat "$T/back.log"
    echo; echo "RESULT: $fails unexpected"
    [ "$fails" -eq 0 ]
    exit
fi

src=${1:?Usage: test-v4l2-preload.sh PIPEWIRE_SRC}
T=$(mktemp -d "$PREFIX/tmp/v4l2test.XXXXXX")
chmod 700 "$T"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/lib" "$T/pw/pipewire-v4l2/src"
cp "$src"/pipewire-v4l2/src/{pipewire-v4l2.c,v4l2-func.c,pipewire-v4l2.h} "$T/pw/pipewire-v4l2/src/" || exit 1
(cd "$T/pw" && patch -p1 -s <"$here/pw-v4l2-bionic-realpath.patch" && patch -p1 -s <"$here/pw-v4l2-device-path.patch") || exit 1
: >"$T/pw/config.h"
pw_flags=$(pkg-config --cflags --libs libpipewire-0.3)
cd "$here" || exit 1
# shellcheck disable=SC2086
clang -O2 -shared -fPIC -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32 -D_LARGEFILE64_SOURCE -U_TIME_BITS \
    -fvisibility=hidden -I"$T/pw" -o "$T/lib/libpw-v4l2.so" \
    "$T"/pw/pipewire-v4l2/src/{pipewire-v4l2.c,v4l2-func.c} $pw_flags -lm &&
    clang -O2 -Wall -shared -fPIC -U_FORTIFY_SOURCE -o "$T/lib/liblivecd-v4l2.so" livecd-v4l2.c &&
    clang -O2 -Wall -o "$T/camnode" camnode.c $pw_flags -lcamera2ndk -lmediandk &&
    clang -O2 -Wall -o "$T/libv4l2-read" libv4l2-read.c -lv4l2 || exit 1
dbus-run-session -- bash "$0" --session "$T" 2>&1 | grep --line-buffered -v '^dbus-daemon'
status=${PIPESTATUS[0]}
[ -n "${2:-}" ] && cp "$T/front-yuyv.raw" "$T/chromium.jpg" "$2/" 2>/dev/null
exit "$status"
