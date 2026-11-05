#!/data/data/com.termux/files/usr/bin/bash
# Real-microphone checks, on a private PulseAudio started the way the native desktop starts it.
# Plays short quiet tones through the speaker. Reports levels only; no audio is kept.
# Usage: test-real-mic.sh MIC_PY PATCHED_PROBE STOCK_PROBE
set -u
mic=${1:?} patched=${2:?} stock=${3:?}
rish=$HOME/.local/lib/shizuku/rish
shell_cmd() { RISH_APPLICATION_ID=com.termux timeout 20 "$rish" -c "$1" </dev/null 2>&1 | grep -v 'Waiting for'; }
T=$(mktemp -d "$PREFIX/tmp/mictest.XXXXXX"); chmod 700 "$T"
mkdir -p "$T/rt" "$T/st" "$T/cfg" "$T/home"
pa=
stop_pa() { [ -n "$pa" ] && kill "$pa" 2>/dev/null; wait "$pa" 2>/dev/null; pa=; }
trap 'stop_pa; rm -rf "$T"' EXIT
export PULSE_SERVER=unix:$T/s

start_pa() {
    rm -f "$T/s"
    (
        export PULSE_RUNTIME_PATH=$T/rt PULSE_STATE_PATH=$T/st PULSE_CONFIG_PATH=$T/cfg HOME=$T/home
        unset PULSE_SERVER
        exec pulseaudio --daemonize=no --exit-idle-time=-1 --use-pid-file=no -n --load=module-sles-sink \
            '--load=module-null-source source_name=android_no_microphone format=s16le rate=48000 channels=1 description="No microphone"' \
            "--load=module-native-protocol-unix socket=$T/s auth-anonymous=1"
    ) >"$T/pa.log" 2>&1 </dev/null &
    pa=$!
    for _ in $(seq 30); do [ -S "$T/s" ] && pactl info >/dev/null 2>&1 </dev/null && return; sleep 0.2; done
    echo "PulseAudio did not start"; exit 1
}
# Whether Android has a recorder open for the Termux UID.
android_recording() {
    shell_cmd 'dumpsys media.audio_flinger | awk "/^Input thread/{f=1;printf \"input thread open, \";next} f&&/Standby:/{print;f=0}"; dumpsys audio | grep -E " rec (start|stop|update) " | tail -1' | cut -c1-110
}
tone() {
    python3 -I -c '
import array, math, sys
pcm = array.array("h", (round(3277 * math.sin(2 * math.pi * 1000 * i / 48000)) for i in range(48000)))
for _ in range(int(sys.argv[1])):
    sys.stdout.buffer.write(pcm.tobytes())' "$1" \
        | timeout "$(($1 + 2))" pacat --raw --format=s16le --rate=48000 --channels=1 --device=OpenSL_ES_sink --latency-msec=100
}
# Level, 1 kHz prominence and delivery rate of a capture, without keeping it.
analyse() {
    timeout "$(($1 + 3))" parec "--device=$2" --raw --format=s16le --rate=48000 --channels=1 </dev/null 2>/dev/null | python3 -I -c '
import array, math, sys, time
want = int(float(sys.argv[1]) * 48000) * 2
start = time.monotonic()
data = sys.stdin.buffer.read(want)
elapsed = time.monotonic() - start
pcm = array.array("h", data[:len(data) - len(data) % 2])
n = len(pcm)
if not n:
    print("no samples"); sys.exit()
rms = math.sqrt(sum(x * x for x in pcm) / n)
def power(frequency):
    c = 2 * math.cos(2 * math.pi * frequency / 48000)
    a = b = 0.0
    for x in pcm:
        a, b = x + c * a - b, a
    return (a * a + b * b - c * a * b) / n / n
tone, nearby = power(1000), (power(700) + power(1300)) / 2
print(f"samples={n} in {elapsed:.2f}s rms_db={20 * math.log10(max(rms, 0.5) / 32768):.1f} "
      f"peak={max(map(abs, pcm))} 1kHz_over_neighbours_db={10 * math.log10(max(tone, 1e-9) / max(nearby, 1e-9)):.1f}")' "$1"
}

echo "=== phone"
date '+%F %T'
shell_cmd 'dumpsys package com.termux.api | grep -E "versionName|RECORD_AUDIO" | sort -u; cmd appops get com.termux RECORD_AUDIO; dumpsys activity activities | grep -E "mResumedActivity|ResumedActivity:" | head -2; dumpsys audio | grep -A5 -E "^- STREAM_MUSIC:" | grep -E "streamVolume"; dumpsys audio | grep -m1 -E "mode \(external\)"' | cut -c1-120

echo; echo "=== 1. Module block size against Serein's record queue"
for latency in default 20 10; do
    arg=; [ "$latency" != default ] && arg="latency=$latency"
    for variant in stock patched; do
        start_pa
        if pactl load-module module-sles-source source_name=real format=s16le rate=48000 channels=1 $arg >/dev/null </dev/null; then
            pactl set-default-source real </dev/null
            probe=$patched; [ "$variant" = stock ] && probe=$stock
            result=$(timeout 8 "$probe" 4 </dev/null 2>&1 | grep -E '^t=4s' | sed 's/default=[^=]*peak/peak/')
            echo "latency=$latency cpal=$variant: ${result:-STALLED: no engine output within 8 s}"
        else
            echo "latency=$latency cpal=$variant: module refused"
        fi
        stop_pa
    done
done

start_pa
echo; echo "=== 2. Controller: on"
python3 -I "$mic" on </dev/null; echo "exit=$?"
sleep 3
echo; echo "=== 3. Idle with the microphone on: source state and Android recorder"
pactl list short sources </dev/null | cut -f2,4,5
android_recording

echo; echo "=== 4. Ambient capture, then the speaker tone through the air (needs media volume above 0)"
analyse 3 android_microphone
tone 5 & tone_pid=$!
sleep 1
analyse 3 android_microphone
wait "$tone_pid"

echo; echo "=== 5. While something records: Android recorder"
timeout 4 parec --device=android_microphone --raw </dev/null >/dev/null 2>&1 & rec=$!
sleep 2
pactl list short sources </dev/null | cut -f2,5
android_recording
wait "$rec"
sleep 3
echo "--- 3 s after it stopped"
pactl list short sources </dev/null | cut -f2,5
android_recording

echo; echo "=== 6. Serein's engine on the real microphone (patched cpal), ambient then tone"
"$patched" 4 </dev/null | grep -E '^(default input|engine|t=)' | cut -c1-120
tone 6 & tone_pid=$!
sleep 1
"$patched" 4 </dev/null | grep -E '^t=' | cut -c1-120
wait "$tone_pid"

echo; echo "=== 7. Same with stock cpal"
timeout 8 "$stock" 4 </dev/null | grep -E '^(default input|engine|t=)' | cut -c1-120 || true

echo; echo "=== 8. Microphone turned off mid-call: does Serein stay safe?"
tone 9 & tone_pid=$!
"$patched" 7 </dev/null > "$T/mid.txt" & probe=$!
sleep 3
python3 -I "$mic" off </dev/null
wait "$probe"; wait "$tone_pid"
grep -E '^t=' "$T/mid.txt" | cut -c1-120

echo; echo "=== 9. Idle without suspend-on-idle, for comparison: is the recorder held open?"
stop_pa; start_pa
pactl load-module module-sles-source source_name=real format=s16le rate=48000 channels=1 latency=20 >/dev/null </dev/null
sleep 3
pactl list short sources </dev/null | cut -f2,5
android_recording
stop_pa
sleep 1
echo "--- PulseAudio stopped: Android recorder"
android_recording
echo; echo "=== done"
