#!/data/data/com.termux/files/usr/bin/bash
# Is the microphone detected inside the running native desktop? Uses the session's own environment,
# an X11 mixer and Serein's engine, with compositor screenshots at each state. Needs pavucontrol.
# Usage: test-desktop.sh MIC_PY PROBE OUTPUT_DIRECTORY
set -u
mic=${1:?} probe=${2:?} out=${3:?}
session=$HOME/.local/bin/livecd-native
mkdir -p "$out"
in_session() { "$session" exec "$@" </dev/null; }
shot() {
    sleep 1.5
    in_session python -c "import sys; sys.path.insert(0, '$HOME/.local/lib/livecd-native'); from capture import screenshot; screenshot('$out/$1.png')" 2>&1 | tail -1 | cut -c1-120
    echo "screenshot: $1"
}
state() {
    in_session pactl info | grep 'Default Source'
    in_session pactl list short sources | cut -f2,4,5
    echo "recording clients: $(in_session pactl list source-outputs | grep -cE '^Source Output #')"
}
mixer=
trap '[ -n "$mixer" ] && kill "$mixer" 2>/dev/null; python3 -I "$mic" off >/dev/null 2>&1 </dev/null' EXIT
export PULSE_SERVER=unix:$PREFIX/tmp/livecd-host/pulse.sock

echo "=== 1. Started session, microphone off"
state
"$session" exec pavucontrol --tab=4 >"$out/pavucontrol.log" 2>&1 </dev/null &
mixer=$!
sleep 6
shot 1-off

echo; echo "=== 2. Microphone on"
python3 -I "$mic" on </dev/null
state
shot 2-on

echo; echo "=== 3. Serein's engine as a session client"
in_session "$probe" 0 | grep -E '^(host|default input|default output|listed input)' | cut -c1-110
"$session" exec "$probe" 14 > "$out/serein.txt" 2>&1 </dev/null &
client=$!
sleep 5
state
in_session pactl list source-outputs | grep -E 'Source Output #|Source:|Sample Specification|application.name|application.process.binary' | sed 's/^\s*//' | cut -c1-90
shot 3-recording-input-tab
"$session" exec pavucontrol --tab=2 >/dev/null 2>&1 </dev/null &
sleep 2
shot 4-recording-tab
wait "$client"
grep -E '^(engine|t=)' "$out/serein.txt" | sed 's/microphone_unavailable=false //' | cut -c1-90

echo; echo "=== 4. Microphone off"
python3 -I "$mic" off </dev/null
"$session" exec pavucontrol --tab=4 >/dev/null 2>&1 </dev/null &
state
shot 5-off-again
kill "$mixer" 2>/dev/null; mixer=
echo; echo "=== 5. Android recorder after off"
RISH_APPLICATION_ID=com.termux timeout 15 "$HOME/.local/lib/shizuku/rish" -c 'dumpsys media.audio_flinger | grep -cE "^Input thread"; dumpsys audio | grep -E " rec (start|stop|update) " | tail -1' </dev/null 2>&1 | grep -v 'Waiting for' | cut -c1-110
echo; echo "=== done"
