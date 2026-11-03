#!/data/data/com.termux/files/usr/bin/python
"""Measure native EQ through the backend monitor using quiet 100/1000 Hz tones.

Requires a disposable running livecd-audio session. The existing backend's
default monitor is observed; no physical output is selected or changed.
"""
import array
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from autoeq import convert


def main():
    record = json.loads((Path.home() / ".local/state/livecd-audio/session.json").read_text())
    env = dict(os.environ, **record["env"])
    backend = dict(os.environ, PULSE_SERVER=record["backend"])

    def call(args, target=env):
        return subprocess.run(args, env=target, capture_output=True, text=True, check=True).stdout.strip()

    monitor = call(["pactl", "get-default-sink"], backend) + ".monitor"
    previous = call(["easyeffects", "--active-preset", "output"])
    previous_bypass = call(["gsettings", "get", "com.github.wwmm.easyeffects", "bypass"])
    name = "native-eq-verification-" + uuid.uuid4().hex
    directory = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "easyeffects/output"
    preset = directory / f"{name}.json"
    preset.write_text(json.dumps(convert("Preamp: 0 dB\nFilter 1: ON PK Fc 1000 Hz Gain -12 dB Q 1\n")))
    results = {"backend_monitor": monitor, "tone_amplitude": 0.01, "frequencies": {}}
    try:
        call(["easyeffects", "--load-preset", name])
        with tempfile.TemporaryDirectory(prefix="livecd-eq-probe-") as temp:
            temp = Path(temp)
            for frequency in (100, 1000):
                tone = temp / "tone.raw"
                samples = array.array("f", (0.01 * math.sin(2 * math.pi * frequency * (i // 2) / 48000)
                                           for i in range(48000 * 2 * 12)))
                tone.write_bytes(samples.tobytes())
                values = {}
                with tone.open("rb") as source:
                    player = subprocess.Popen(["pacat", "--playback", "--raw", "--format=float32le",
                                               "--rate=48000", "--channels=2", "--stream-name=NativeEQVerification"],
                                              env=env, stdin=source)
                    try:
                        for label, bypass in (("bypass", "1"), ("filtered", "2")):
                            call(["easyeffects", "--bypass=" + bypass])
                            time.sleep(1)
                            path = temp / "recording.raw"
                            with path.open("wb") as output:
                                recorder = subprocess.Popen(["parec", "--raw", "--format=float32le", "--rate=48000",
                                                             "--channels=2", "--device=" + monitor],
                                                            env=backend, stdout=output)
                                try:
                                    time.sleep(1.5)
                                finally:
                                    recorder.terminate()
                                    recorder.wait(timeout=5)
                            data = array.array("f")
                            data.frombytes(path.read_bytes())
                            data = data[len(data) // 2:]
                            if not data:
                                raise RuntimeError("No samples captured from the backend monitor")
                            values[label + "_rms"] = math.sqrt(sum(v * v for v in data) / len(data))
                    finally:
                        player.terminate()
                        player.wait(timeout=5)
                values["attenuation_db"] = 20 * math.log10(values["filtered_rms"] / values["bypass_rms"])
                results["frequencies"][str(frequency)] = values
        low = results["frequencies"]["100"]["attenuation_db"]
        peak = results["frequencies"]["1000"]["attenuation_db"]
        results["passed"] = abs(low) < 1 and abs(peak + 12) < 0.5
        print(json.dumps(results, indent=2))
        if not results["passed"]:
            raise RuntimeError("Parametric filter response outside acceptance tolerance")
    finally:
        if previous and (directory / f"{previous}.json").exists():
            call(["easyeffects", "--load-preset", previous])
        else:
            call(["gsettings", "set", "com.github.wwmm.easyeffects.streamoutputs", "plugins", "[]"])
            call(["gsettings", "set", "com.github.wwmm.easyeffects", "last-loaded-output-preset", "''"])
        call(["easyeffects", "--bypass=" + ("1" if previous_bypass == "true" else "2")])
        preset.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
