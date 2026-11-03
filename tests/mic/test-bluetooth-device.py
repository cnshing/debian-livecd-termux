#!/data/data/com.termux/files/usr/bin/python
"""Opt-in installed-package checks on a phone with an idle, connected Bluetooth headset.

Usage: python tests/mic/test-bluetooth-device.py
Captures four seconds into a level meter; keeps no audio. Requires the desktop's
PulseAudio, microphone permission and authorized Shizuku. Does not place a call.
"""

import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time


PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
MIC = str(PREFIX / "bin/livecd-mic")
BLUETOOTH = str(PREFIX / "bin/livecd-mic-bluetooth")


def run(*arguments, check=True):
    result = subprocess.run(arguments, text=True, capture_output=True, timeout=40)
    if check and result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result


def microphone_off():
    state = json.loads(run(MIC, "status").stdout)
    assert state["microphone"] == "off", state
    assert state["default_source"] == "livecd_no_microphone", state


def route_off():
    state = json.loads(run(BLUETOOTH, "devices").stdout)
    assert not state["sco_on"], state
    assert state["audio_mode"] == 0, state
    return state


def main():
    microphone_off()
    initial = route_off()
    assert initial["bluetooth_devices"], "Connect a Bluetooth headset with Calls enabled first"

    invalid = run(BLUETOOTH, "call", "--device", "2147483647", check=False)
    assert invalid.returncode == 1 and "No matching" in invalid.stderr, invalid
    microphone_off()
    route_off()
    print(json.dumps({"check": "invalid-device", "passed": True}), flush=True)

    capture = run(BLUETOOTH, "call", "--", MIC, "test", "--seconds", "4")
    messages = [json.loads(line) for line in capture.stdout.splitlines()]
    assert messages[0]["event"] == "ready", messages
    assert messages[1]["source"] == "livecd_bluetooth_input", messages
    assert messages[1]["samples"] == 192000, messages
    microphone_off()
    route_off()
    print(json.dumps({"check": "native-capture-and-exit", "passed": True,
                      "route": messages[0], "levels": messages[1]}), flush=True)

    controller = subprocess.Popen([BLUETOOTH, "call"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
    try:
        assert select.select([controller.stdout], [], [], 30)[0], "No session readiness within 30 s"
        ready = json.loads(controller.stdout.readline())
        assert ready["event"] == "ready", ready
        controller.send_signal(signal.SIGTERM)
        output, errors = controller.communicate(timeout=15)
        assert controller.returncode == 130, (controller.returncode, output, errors)
    finally:
        if controller.poll() is None:
            controller.terminate()
            try:
                controller.wait(timeout=15)
            except subprocess.TimeoutExpired:
                controller.kill()
                controller.wait()
        # A failing interruption test must still leave capture disabled.
        run(MIC, "off")
    microphone_off()
    final = route_off()
    print(json.dumps({"check": "sigterm-cleanup", "passed": True,
                      "final_android_state": final}), flush=True)

    defaults = {kind: run("pactl", f"get-default-{kind}").stdout.strip() for kind in ("source", "sink")}
    try:
        enabled = json.loads(run(BLUETOOTH, "on").stdout)
        assert enabled["active"] and enabled["input"] == "livecd_bluetooth_input", enabled
        assert enabled["output"] == "livecd_bluetooth_output", enabled
        sources = json.loads(run("pactl", "--format=json", "list", "sources").stdout)
        sinks = json.loads(run("pactl", "--format=json", "list", "sinks").stdout)
        source = next(item for item in sources if item["name"] == enabled["input"])
        sink = next(item for item in sinks if item["name"] == enabled["output"])
        assert source["description"].endswith(" Microphone"), source
        assert sink["description"].endswith(" Headphones"), sink
        for kind in ("source", "sink"):
            assert run("pactl", f"get-default-{kind}").stdout.strip() == defaults[kind]
        duplicate = json.loads(run(BLUETOOTH, "on").stdout)
        assert duplicate["controller_pid"] == enabled["controller_pid"], duplicate
        run(BLUETOOTH, "on", "--default")
        assert run("pactl", "get-default-source").stdout.strip() == enabled["input"]
        assert run("pactl", "get-default-sink").stdout.strip() == enabled["output"]
        print(json.dumps({"check": "named-linux-devices", "passed": True,
                          "input_description": source["description"],
                          "output_description": sink["description"]}), flush=True)
    finally:
        run(BLUETOOTH, "off")
    for kind in ("source", "sink"):
        assert run("pactl", f"get-default-{kind}").stdout.strip() == defaults[kind]
    assert "livecd_bluetooth_output" not in run("pactl", "list", "short", "sinks").stdout
    assert "livecd_bluetooth_input" not in run("pactl", "list", "short", "sources").stdout
    route_off()
    print(json.dumps({"check": "background-off-restores-defaults", "passed": True}), flush=True)

    # Only force-kill our own idle test controller; no capture client is running.
    enabled = json.loads(run(BLUETOOTH, "on").stdout)
    try:
        deadline = time.monotonic() + 5
        while True:
            source = next(item for item in json.loads(run("pactl", "--format=json", "list", "sources").stdout)
                          if item["name"] == enabled["input"])
            if source["state"] == "SUSPENDED":
                break
            assert time.monotonic() < deadline, "Test microphone never became idle"
            time.sleep(0.1)
        os.kill(enabled["controller_pid"], signal.SIGKILL)
        deadline = time.monotonic() + 5
        while json.loads(run(BLUETOOTH, "status").stdout)["active"]:
            assert time.monotonic() < deadline, "Killed controller still reports active"
            time.sleep(0.1)
    finally:
        run(BLUETOOTH, "off")
    assert "livecd_bluetooth_output" not in run("pactl", "list", "short", "sinks").stdout
    assert "livecd_bluetooth_input" not in run("pactl", "list", "short", "sources").stdout
    route_off()
    print(json.dumps({"check": "explicit-off-after-sigkill", "passed": True}), flush=True)


if __name__ == "__main__":
    os.environ.setdefault("PULSE_SERVER", f"unix:{PREFIX}/tmp/livecd-host/pulse.sock")
    main()
