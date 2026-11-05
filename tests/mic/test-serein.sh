#!/data/data/com.termux/files/usr/bin/bash
# What Serein's audio engine selects and hears from each PulseAudio source arrangement.
# Uses a private PulseAudio on its own socket; plays a quiet tone through the phone's speaker.
# Usage: test-serein.sh PROBE
set -u
probe=${1:?Usage: test-serein.sh PROBE}
T=$(mktemp -d "$PREFIX/tmp/mictest.XXXXXX"); chmod 700 "$T"
mkdir -p "$T/rt" "$T/st" "$T/cfg" "$T/home"
pa_pid=
stop_pa() { [ -n "$pa_pid" ] && kill "$pa_pid" 2>/dev/null; wait "$pa_pid" 2>/dev/null; pa_pid=; }
trap 'stop_pa; rm -rf "$T"' EXIT
export PULSE_SERVER=unix:$T/s

start_pa() {
    rm -f "$T/s"
    (
        export PULSE_RUNTIME_PATH=$T/rt PULSE_STATE_PATH=$T/st PULSE_CONFIG_PATH=$T/cfg HOME=$T/home
        unset PULSE_SERVER
        exec pulseaudio --daemonize=no --exit-idle-time=-1 --use-pid-file=no -n \
            --load=module-sles-sink "--load=module-native-protocol-unix socket=$T/s auth-anonymous=1"
    ) >>"$T/pa.log" 2>&1 </dev/null &
    pa_pid=$!
    for _ in $(seq 30); do [ -S "$T/s" ] && pactl info >/dev/null 2>&1 </dev/null && return; sleep 0.2; done
    echo "PulseAudio did not start"; tail -5 "$T/pa.log"; exit 1
}
# A quiet 1 kHz tone: -30 dBFS, so a monitor capture reads about -30 dB.
tone() {
    python3 -I -c '
import array, math, sys
seconds = float(sys.argv[1])
pcm = array.array("h", (round(1036 * math.sin(2 * math.pi * 1000 * i / 48000)) for i in range(48000)))
for _ in range(int(seconds)):
    sys.stdout.buffer.write(pcm.tobytes())' "$1" \
        | timeout "$(($1 + 2))" pacat --raw --format=s16le --rate=48000 --channels=1 --device=OpenSL_ES_sink --latency-msec=100
}
scene() { echo; echo "=== $*"; pactl info </dev/null | grep 'Default Source'; pactl list short sources </dev/null | cut -f2,5; }

start_pa
scene "A. The desktop's arrangement: only the sink's monitor"
tone 6 & "$probe" 5 </dev/null; wait $!
stop_pa

start_pa
pactl load-module module-null-source source_name=android_no_microphone rate=48000 channels=1 >/dev/null </dev/null
scene "B. A silent source added, same tone playing"
tone 6 & "$probe" 5 </dev/null; wait $!
stop_pa

start_pa
pactl load-module module-null-source source_name=android_no_microphone rate=48000 channels=1 >/dev/null </dev/null
pactl load-module module-sine-source source_name=stand_in_mic rate=48000 frequency=440 >/dev/null </dev/null
pactl set-default-source stand_in_mic </dev/null
scene "C. A stand-in microphone as default, no speaker output"
"$probe" 4 </dev/null
stop_pa

start_pa
module=$(pactl load-module module-sine-source source_name=stand_in_mic rate=48000 frequency=440 </dev/null)
pactl set-default-source stand_in_mic </dev/null
scene "D. Microphone removed mid-call, nothing else as default: speaker tone playing"
tone 10 & tone_pid=$!
"$probe" 8 </dev/null & probe_pid=$!
sleep 4
echo "-- removing the stand-in microphone"
pactl unload-module "$module" </dev/null
wait "$probe_pid"; wait "$tone_pid"
stop_pa

start_pa
pactl load-module module-null-source source_name=android_no_microphone rate=48000 channels=1 >/dev/null </dev/null
module=$(pactl load-module module-sine-source source_name=stand_in_mic rate=48000 frequency=440 </dev/null)
pactl set-default-source stand_in_mic </dev/null
scene "E. Microphone removed mid-call, silent source present: speaker tone playing"
tone 10 & tone_pid=$!
"$probe" 8 </dev/null & probe_pid=$!
sleep 4
echo "-- removing the stand-in microphone"
pactl unload-module "$module" </dev/null
wait "$probe_pid"; wait "$tone_pid"
stop_pa

start_pa
scene "F. Android refuses the real microphone at runtime: does PulseAudio stay up?"
if pactl load-module module-sles-source source_name=real_mic rate=48000 channels=1 </dev/null; then
    echo "module loaded: the Termux UID holds RECORD_AUDIO"
else
    echo "load refused"
fi
pactl info </dev/null | grep -E 'Server Version|Default Source'
stop_pa
echo; echo "=== done"
