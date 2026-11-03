#!/data/data/com.termux/files/usr/bin/bash
# Does physical sound reach the capture? Pulses the vibration motor, which works in silent mode
# and which the microphone hears through the phone's body, and compares the on and off periods.
# Also checks that a suspended sink still resumes. Reports levels only; no audio is kept.
# Usage: test-acoustic.sh MIC_PY PROBE
set -u
mic=${1:?} probe=${2:?}
rish=$HOME/.local/lib/shizuku/rish
shell_cmd() { RISH_APPLICATION_ID=com.termux timeout 20 "$rish" -c "$1" </dev/null 2>&1 | grep -v 'Waiting for'; }
T=$(mktemp -d "$PREFIX/tmp/mictest.XXXXXX"); chmod 700 "$T"
mkdir -p "$T/rt" "$T/st" "$T/cfg" "$T/home"
pa=
stop_pa() { [ -n "$pa" ] && kill "$pa" 2>/dev/null; wait "$pa" 2>/dev/null; pa=; }
trap 'stop_pa; rm -rf "$T"' EXIT
export PULSE_SERVER=unix:$T/s

(
    export PULSE_RUNTIME_PATH=$T/rt PULSE_STATE_PATH=$T/st PULSE_CONFIG_PATH=$T/cfg HOME=$T/home
    unset PULSE_SERVER
    exec pulseaudio --daemonize=no --exit-idle-time=-1 --use-pid-file=no -n --load=module-sles-sink \
        '--load=module-null-source source_name=livecd_no_microphone format=s16le rate=48000 channels=1 description="No microphone"' \
        "--load=module-native-protocol-unix socket=$T/s auth-anonymous=1"
) >"$T/pa.log" 2>&1 </dev/null &
pa=$!
for _ in $(seq 30); do [ -S "$T/s" ] && pactl info >/dev/null 2>&1 </dev/null && break; sleep 0.2; done

echo "=== phone"
shell_cmd 'dumpsys audio | grep -A5 -E "^- STREAM_MUSIC:" | grep -E "streamVolume"; dumpsys audio | grep -m1 -E "mode \(external\)"; dumpsys activity activities | grep -m1 -E " ResumedActivity:"; dumpsys power | grep -m1 -E "mWakefulness="' | cut -c1-110

echo; echo "=== 1. Controller on, as a client will find it"
python3 -I "$mic" on </dev/null
sleep 3
pactl list short sinks </dev/null | cut -f2,5
pactl list short sources </dev/null | cut -f2,5

echo; echo "=== 2. Raw capture: loudness during and between vibration pulses"
RISH_APPLICATION_ID=com.termux python3 -I - "$rish" <<'PY'
import array, math, subprocess, sys, threading, time
rish = sys.argv[1]
capture = subprocess.Popen(["parec", "--device=livecd_microphone", "--raw", "--format=s16le", "--rate=48000", "--channels=1"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
frames = []
def read():
    while True:
        chunk = capture.stdout.read(4800)
        if len(chunk) < 4800:
            return
        pcm = array.array("h", chunk)
        frames.append((time.monotonic(), math.sqrt(sum(x * x for x in pcm) / len(pcm))))
threading.Thread(target=read, daemon=True).start()
time.sleep(1.5)
pulses = []
for _ in range(4):
    pulses.append(time.monotonic())
    subprocess.Popen([rish, "-c", "cmd vibrator vibrate -f 1500 livecd-mic-test"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
capture.terminate()
def db(values):
    return 20 * math.log10(max(sum(values) / max(len(values), 1), 0.5) / 32768)
for number, start in enumerate(pulses, 1):
    on = [r for t, r in frames if start + 0.8 <= t <= start + 1.4]
    off = [r for t, r in frames if start + 2.2 <= t <= start + 2.9]
    print(f"pulse {number}: during {db(on):.1f} dB ({len(on)} frames), after {db(off):.1f} dB ({len(off)} frames), difference {db(on) - db(off):.1f} dB")
PY

echo; echo "=== 3. Serein's engine: 2 s pulses starting at about t=3, 7 and 11"
(
    sleep 2
    for _ in 1 2 3; do
        RISH_APPLICATION_ID=com.termux timeout 5 "$rish" -c 'cmd vibrator vibrate -f 2000 livecd-mic-test' </dev/null >/dev/null 2>&1
        sleep 4
    done
) & pulses=$!
"$probe" 14 </dev/null | grep -E '^(default input|t=)' | sed 's/ready=true microphone_unavailable=false default=Microphone //' | cut -c1-110
wait "$pulses"

echo; echo "=== 4. After suspending, does the sink still run? (monitor level of a tone)"
sleep 2
pactl list short sinks </dev/null | cut -f2,5
python3 -I -c '
import array, math, sys
pcm = array.array("h", (round(3277 * math.sin(2 * math.pi * 1000 * i / 48000)) for i in range(48000)))
for _ in range(4):
    sys.stdout.buffer.write(pcm.tobytes())' | timeout 6 pacat --raw --format=s16le --rate=48000 --channels=1 --device=OpenSL_ES_sink --latency-msec=100 &
tone=$!
sleep 0.5
pactl list short sinks </dev/null | cut -f2,5
timeout 3 parec --device=OpenSL_ES_sink.monitor --raw --format=s16le --rate=48000 --channels=1 </dev/null 2>/dev/null | python3 -I -c '
import array, math, sys
pcm = array.array("h", sys.stdin.buffer.read(96000))
print(f"monitor rms {20 * math.log10(max(math.sqrt(sum(x * x for x in pcm) / max(len(pcm), 1)), 0.5) / 32768):.1f} dB over {len(pcm)} samples")'
wait "$tone"

echo; echo "=== 5. Controller off"
python3 -I "$mic" off </dev/null
echo; echo "=== done"
