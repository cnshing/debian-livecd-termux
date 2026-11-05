#!/data/data/com.termux/files/usr/bin/python
"""Opt-in Android microphone for the native desktop's PulseAudio.

Clients such as Serein record from PulseAudio's default source. With no other source, that is
the speaker monitor, so a silent source stays loaded to take over whenever the microphone is off.
"""

import argparse
import array
import json
import math
import os
from pathlib import Path
import subprocess
import sys


PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
SOCKET = PREFIX / "tmp/livecd-host/pulse.sock"
MICROPHONE = "android_microphone"
SILENCE = "android_no_microphone"
SPEC = "format=s16le rate=48000 channels=1"
# module-sles-source defaults to fixed 125 ms blocks, more than a 20 ms record queue accepts.
LATENCY_MS = 20
NO_PERMISSION = """Android refused the microphone. Termux has no RECORD_AUDIO permission of its own:
install Termux:API from the same source as Termux, then grant it:
  adb shell pm grant com.termux.api android.permission.RECORD_AUDIO
The permission then applies to every Termux process."""


def pactl(*args, check=True):
    return subprocess.run(["pactl", *args], check=check, text=True, capture_output=True, stdin=subprocess.DEVNULL)


def module_index(name, source=""):
    for line in pactl("list", "short", "modules").stdout.splitlines():
        index, module, argument = (line.split("\t") + ["", ""])[:3]
        if module == name and (not source or f"source_name={source}" in argument):
            return index
    return None


def default_source():
    return pactl("get-default-source").stdout.strip()


def ensure_silence():
    if not module_index("module-null-source", SILENCE):
        pactl("load-module", "module-null-source", f"source_name={SILENCE}", *SPEC.split(),
              'description="No microphone"')


def turn_off():
    ensure_silence()
    pactl("set-default-source", SILENCE)
    module = module_index("module-sles-source", MICROPHONE)
    if module:
        pactl("unload-module", module)
    module = module_index("module-suspend-on-idle")
    if module:
        pactl("unload-module", module)


def turn_on():
    ensure_silence()
    if not module_index("module-sles-source", MICROPHONE):
        # Without this the source keeps Android's recorder open while nothing is listening.
        if not module_index("module-suspend-on-idle"):
            pactl("load-module", "module-suspend-on-idle", "timeout=1")
        loaded = pactl("load-module", "module-sles-source", f"source_name={MICROPHONE}", *SPEC.split(),
                       f"latency={LATENCY_MS}", 'source_properties=device.description="Microphone"', check=False)
        if loaded.returncode:
            turn_off()
            sys.exit(NO_PERMISSION)
    pactl("set-default-source", MICROPHONE)


def measure(seconds):
    """Report the default source's level. The audio is read into memory and discarded."""
    source = default_source()
    process = subprocess.Popen(["parec", f"--device={source}", "--raw", "--format=s16le", "--rate=48000", "--channels=1"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    try:
        data = process.stdout.read(int(seconds * 48000) * 2)
    finally:
        process.terminate()
        process.wait()
    pcm = array.array("h", data[:len(data) - len(data) % 2])
    rms = math.sqrt(sum(sample * sample for sample in pcm) / len(pcm)) if pcm else 0
    level = round(20 * math.log10(rms / 32768), 1) if rms else None
    return {"source": source, "samples": len(pcm), "rms_db": level, "peak": max(map(abs, pcm), default=0)}


def status():
    sources = {source["name"]: source for source in json.loads(pactl("--format=json", "list", "sources").stdout)}
    current = default_source()
    microphone = sources.get(MICROPHONE)
    return {
        "default_source": current,
        "default_is_monitor": current.endswith(".monitor"),
        "microphone": microphone["state"].lower() if microphone else "off",
        "silent_fallback": SILENCE in sources,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("on", "off", "status", "test"))
    parser.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args()
    os.environ.setdefault("PULSE_SERVER", f"unix:{SOCKET}")
    if pactl("info", check=False).returncode:
        sys.exit("PulseAudio is not running; start the desktop first.")
    if args.command == "on":
        turn_on()
    elif args.command == "off":
        turn_off()
    elif args.command == "test":
        print(json.dumps(measure(args.seconds)))
        return
    print(json.dumps(status()))


if __name__ == "__main__":
    main()
