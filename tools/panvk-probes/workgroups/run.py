#!/usr/bin/env python3
"""Private device experiment; never changes installed ICDs or renderer config."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--patched", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(exist_ok=False, parents=True)
here = Path(__file__).resolve().parent
results = []
for variant, driver, enabled in (
    ("baseline", args.baseline, False),
    ("patched-off", args.patched, False),
    ("patched-on", args.patched, True),
):
    driver = driver.resolve(strict=True)
    cases = [(shape, "run") for shape in ("128-1-1", "256-1-1", "512-1-1")]
    if enabled:
        cases += [(shape, "run") for shape in ("1024-1-1", "32-30-1", "8-8-16")]
        cases += [("nested", "reject"), ("769-1-1", "reject")]
    else:
        cases += [("1024-1-1", "skip")]
    for shape, mode in cases:
        dims = [1024, 1, 1] if shape == "nested" else list(map(int, shape.split("-")))
        env = os.environ.copy()
        for name in ("LD_PRELOAD", "PANVK_G77_LWG", "MESA_GL_VERSION_OVERRIDE",
                     "MESA_GLSL_VERSION_OVERRIDE", "PANVK_LWG_PRINT"):
            env.pop(name, None)
        env["PANVK_G77_LWG"] = "1" if enabled else "0"
        env["MESA_SHADER_CACHE_DISABLE"] = "true"
        command = [str(here / "check"), str(driver), str(here / f"{shape}.spv"),
                   *map(str, dims), mode]
        try:
            run = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=20)
            output, code = run.stdout, run.returncode
        except subprocess.TimeoutExpired as error:
            output = str(error.stdout or b"") + "\nTIMEOUT"
            code = 124
        log = f"{variant}-{shape}.txt"
        (args.out / log).write_text(output)
        result = {"variant": variant, "shape": shape, "mode": mode, "returncode": code,
                  "driver": str(driver), "sha256": hashlib.sha256(driver.read_bytes()).hexdigest(),
                  "log": log}
        results.append(result)
        (args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"{variant} {shape} {mode}: {code}\n{output}", flush=True)
        if code:
            raise SystemExit("Stopped at the first failed case; inspect the driver/compiler logs.")
print("PASS: all controls, output oracles and rejection cases passed")
