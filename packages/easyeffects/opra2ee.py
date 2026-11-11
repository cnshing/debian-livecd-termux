#!/usr/bin/env python3
# opra2ee.py converts database_v1.jsonl to EasyEffects Parametric EQ Harman IE/OE presets.
import json, re, sys
from pathlib import Path

PRIORITY = ["oratory1990", "AutoEQ", "Rtings/AutoEQ"] 
TYPES = {"peak_dip": "Bell", "low_shelf": "Lo-shelf", "high_shelf": "Hi-shelf",
         "low_pass": "Lo-pass", "high_pass": "Hi-pass"}  # band_pass/band_stop skipped, none in the data today

def rank(eq):
    # Prioritize by Harman first, then author, then plain EQs.
    d = eq.get("details", "").lower()
    non_harman = "harman" not in d and not d.startswith("measured by")
    a = eq["author"]
    return (non_harman, PRIORITY.index(a) if a in PRIORITY else len(PRIORITY), " • " in d)

def preset(eq):
    bands = {}
    for b in eq["parameters"]["bands"]:
        if b["type"] not in TYPES:
            continue
        bands[f"band{len(bands)}"] = {
            # EasyEffects 7 schema range is 10-24000 Hz (one OPRA band sits at 8.5 Hz)
            "type": TYPES[b["type"]], "frequency": min(max(b["frequency"], 10), 24000),
            "gain": b.get("gain_db", 0.0), "q": b.get("q", 0.707),
            # Same mode EasyEffects' own APO import uses, matching the biquads OPRA EQs are made for
            "mode": "APO (DR)", "slope": "x1", "mute": False, "solo": False}
    return {"output": {"blocklist": [], "plugins_order": ["equalizer#0"], "equalizer#0": {
        "bypass": False, "input-gain": eq["parameters"]["gain_db"], "output-gain": 0.0,
        "mode": "IIR", "num-bands": len(bands), "split-channels": False,
        "balance": 0.0, "left": bands, "right": bands}}}

def main(src, dest):
    vendors, products, best = {}, {}, {}
    for line in open(src, encoding="utf-8"):
        e = json.loads(line)
        if e["type"] == "vendor":
            vendors[e["id"]] = e["data"]["name"]
        elif e["type"] == "product":
            products[e["id"]] = e["data"]
        elif e["type"] == "eq":
            pid = e["data"]["product_id"]
            if pid not in best or rank(e["data"]) < rank(best[pid]):
                best[pid] = e["data"]
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for pid, eq in best.items():
        p = products[pid]
        # CC BY-SA: credit the EQ creator, so it goes in the name
        name = f'{vendors.get(p["vendor_id"], p["vendor_id"])} {p["name"]} ({eq["author"]})'
        name = re.sub(r'[/\\:*?"<>|]', "-", name)
        out = dest / f"{name}.json"
        if out.exists():  # same display name, different OPRA product
            out = dest / f"{name} [{pid}].json"
        out.write_text(json.dumps(preset(eq)))
    print(f"wrote {len(best)} presets")
    return best

if __name__ == "__main__":
    main(*sys.argv[1:3])
