#!/data/data/com.termux/files/usr/bin/bash
# Exercises android-pulseaudio-mic against a private PulseAudio started the way the native desktop starts it.
# Usage: test-mic.sh MIC_PY
set -u
mic=${1:?Usage: test-mic.sh MIC_PY}
T=$(mktemp -d "$PREFIX/tmp/mictest.XXXXXX"); chmod 700 "$T"
mkdir -p "$T/rt" "$T/st" "$T/cfg" "$T/home"
pa=
trap '[ -n "$pa" ] && kill "$pa" 2>/dev/null; wait 2>/dev/null; rm -rf "$T"' EXIT
export PULSE_SERVER=unix:$T/s
(
    export PULSE_RUNTIME_PATH=$T/rt PULSE_STATE_PATH=$T/st PULSE_CONFIG_PATH=$T/cfg HOME=$T/home
    unset PULSE_SERVER
    exec pulseaudio --daemonize=no --exit-idle-time=-1 --use-pid-file=no -n --load=module-sles-sink \
        '--load=module-null-source source_name=android_no_microphone format=s16le rate=48000 channels=1 description="No microphone"' \
        "--load=module-native-protocol-unix socket=$T/s auth-anonymous=1"
) >"$T/pa.log" 2>&1 </dev/null &
pa=$!
for _ in $(seq 30); do [ -S "$T/s" ] && pactl info >/dev/null 2>&1 </dev/null && break; sleep 0.2; done

step() { echo; echo "--- $*"; python3 -I "$mic" "$@" </dev/null; echo "exit=$?"; }
echo "=== started as the desktop starts it"
pactl info </dev/null | grep 'Default Source'
pactl list short sources </dev/null | cut -f2,4,5
pactl list sources </dev/null | grep -E 'Name:|Description:'
step status
step test --seconds 1
step on
step status
step test --seconds 3
step off
step status
step off
pactl info </dev/null | grep 'Server Version'
echo; echo "=== done"
