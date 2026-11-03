#!/data/data/com.termux/files/usr/bin/bash
# Live phone camera into the hardware encoder, through the paths ordinary Linux
# programs use: the camera as /dev/video0 (tests/camera's camnode and
# livecd-v4l2 preload) and the encoder as /dev/dri/renderD128 (the
# livecd-render-node preload), with both preloads loaded together as the
# desktop session would. A private PipeWire, WirePlumber and D-Bus carry the
# camera; the desktop's own services are not touched.
#
# The caller supplies the VA-API environment the way an installed system would
# (libva and its driver on the library and driver paths, and the daemon's
# socket); see run-phone-tests.sh. Needs CAMERA granted to com.termux.api, and
# opens the front camera.
# Usage: test-camera-encode.sh PIPEWIRE_SRC OUT_DIR
set -u
here=$(cd "$(dirname "$0")" && pwd)
camera=$here/../camera

if [ "${1:-}" = --session ]; then
    T=$2 O=$3
    export XDG_RUNTIME_DIR=$T/run PIPEWIRE_RUNTIME_DIR=$T/run
    mkdir -m 700 "$T/run"
    pids=
    trap 'for p in $pids; do kill "$p" 2>/dev/null; done; wait 2>/dev/null' EXIT
    pipewire >"$T/pipewire.log" 2>&1 </dev/null & pids="$pids $!"
    for _ in $(seq 50); do [ -S "$T/run/pipewire-0" ] && break; sleep 0.1; done
    wireplumber --profile=policy >"$T/wireplumber.log" 2>&1 </dev/null & pids="$pids $!"
    sleep 1
    "$T/camnode" 1 1280 720 30 0 --device=0 >"$O/camnode.log" 2>&1 </dev/null & pids="$pids $!"
    for _ in $(seq 50); do grep -q ready "$O/camnode.log" && break; sleep 0.1; done
    LD_PRELOAD="$T/lib/liblivecd-v4l2.so${LD_PRELOAD:+ $LD_PRELOAD}" python "$here/test-camera.py" --out "$O"
    exit
fi

src=${1:?Usage: test-camera-encode.sh PIPEWIRE_SRC OUT_DIR}
out=${2:?Usage: test-camera-encode.sh PIPEWIRE_SRC OUT_DIR}
mkdir "$out" || exit 1
T=$(mktemp -d "$PREFIX/tmp/camencode.XXXXXX")
chmod 700 "$T"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/lib" "$T/pw/pipewire-v4l2/src"
cp "$src"/pipewire-v4l2/src/{pipewire-v4l2.c,v4l2-func.c,pipewire-v4l2.h} "$T/pw/pipewire-v4l2/src/" || exit 1
(cd "$T/pw" && patch -p1 -s <"$camera/pw-v4l2-bionic-realpath.patch" && patch -p1 -s <"$camera/pw-v4l2-device-path.patch") || exit 1
: >"$T/pw/config.h"
pw_flags=$(pkg-config --cflags --libs libpipewire-0.3)
# The builds must not run under the caller's preloads.
# shellcheck disable=SC2086
env -u LD_PRELOAD clang -O2 -shared -fPIC -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32 -D_LARGEFILE64_SOURCE -U_TIME_BITS \
    -fvisibility=hidden -I"$T/pw" -o "$T/lib/libpw-v4l2.so" \
    "$T"/pw/pipewire-v4l2/src/{pipewire-v4l2.c,v4l2-func.c} $pw_flags -lm &&
    env -u LD_PRELOAD clang -O2 -Wall -shared -fPIC -U_FORTIFY_SOURCE -o "$T/lib/liblivecd-v4l2.so" "$camera/livecd-v4l2.c" &&
    env -u LD_PRELOAD clang -O2 -Wall -o "$T/camnode" "$camera/camnode.c" $pw_flags -lcamera2ndk -lmediandk || exit 1
dbus-run-session -- bash "$0" --session "$T" "$out" 2>&1 | grep --line-buffered -v '^dbus-daemon\|^tva-va: '
exit "${PIPESTATUS[0]}"
