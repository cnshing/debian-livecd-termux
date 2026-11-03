#!/data/data/com.termux/files/usr/bin/python
"""Import AutoEq's Equalizer APO parametric export into EasyEffects 7.

Choose headphones at https://autoeq.app and export EqualizerAPO ParametricEq.
No audio-device discovery or changes to Android routing are performed.
"""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
PREAMP = re.compile(rf"Preamp:\s*({NUMBER})\s*dB", re.I)
FILTER = re.compile(
    rf"Filter\s+\d+:\s+(ON|OFF)\s+(PK|LSC|HSC|LS|HS)\s+"
    rf"Fc\s+({NUMBER})\s+Hz\s+Gain\s+({NUMBER})\s+dB\s+Q\s+({NUMBER})", re.I
)
TYPES = {"PK": "Bell", "LS": "Lo-shelf", "LSC": "Lo-shelf",
         "HS": "Hi-shelf", "HSC": "Hi-shelf"}


def convert(text):
    bands = {}
    preamp = None
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if match := PREAMP.fullmatch(line):
            if preamp is not None:
                raise ValueError(f"line {lineno}: duplicate Preamp")
            preamp = float(match[1])
            if not math.isfinite(preamp) or not -36 <= preamp <= 36:
                raise ValueError(f"line {lineno}: preamp outside EasyEffects' -36..36 dB range")
            continue
        match = FILTER.fullmatch(line)
        if not match:
            raise ValueError(f"line {lineno}: unsupported APO syntax; export EqualizerAPO ParametricEq")
        if match[1].upper() == "OFF":
            continue
        frequency, gain, q = map(float, match.group(3, 4, 5))
        if not all(map(math.isfinite, (frequency, gain, q))):
            raise ValueError(f"line {lineno}: non-finite filter parameter")
        if not (10 <= frequency <= 24000 and -36 <= gain <= 36 and 0 <= q <= 100):
            raise ValueError(f"line {lineno}: filter outside EasyEffects' parameter ranges")
        if len(bands) == 32:
            raise ValueError("EasyEffects supports at most 32 bands")
        bands[f"band{len(bands)}"] = {
            "type": TYPES[match[2].upper()], "frequency": frequency, "gain": gain,
            "q": q, "mode": "APO (DR)", "slope": "x1", "mute": False, "solo": False,
        }
    if preamp is None or not bands:
        raise ValueError("A Preamp line and at least one enabled parametric filter are required")
    return {"output": {"blocklist": [], "plugins_order": ["equalizer#0"], "equalizer#0": {
        "bypass": False, "input-gain": preamp, "output-gain": 0.0,
        "mode": "IIR", "num-bands": len(bands), "split-channels": False,
        "balance": 0.0, "left": bands, "right": bands,
    }}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="AutoEq EqualizerAPO ParametricEq text export")
    parser.add_argument("--name", help="Preset name (default: export filename)")
    parser.add_argument("--replace", action="store_true", help="Replace an existing preset")
    args = parser.parse_args()
    name = args.name or args.file.stem
    if name in ("", ".", "..") or any(c in name for c in "/\\\0\n\r"):
        parser.error("Preset name must be a single filename without an extension")
    try:
        preset = convert(args.file.read_text(encoding="utf-8-sig"))
        config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        directory = config / "easyeffects/output"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{name}.json"
        # Exclusive creation prevents an import from silently destroying a user's preset.
        with destination.open("w" if args.replace else "x", encoding="utf-8") as output:
            json.dump(preset, output, indent=2, allow_nan=False)
            output.write("\n")
        print(destination)
        print(f"Apply: livecd-audio preset {shlex.quote(name)}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"AutoEq import failed: {exc}\n")


if __name__ == "__main__":
    main()
