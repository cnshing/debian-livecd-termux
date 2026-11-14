#!/usr/bin/env python3
"""Private device experiment; never changes installed ICDs or renderer config."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--baseline", type=Path, required=True)
parser.add_argument("--patched", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--shader-cache", action="store_true", help="Use a private cache shared by sibling runs")
args = parser.parse_args()
args.out.mkdir(exist_ok=False, parents=True)
here = Path(__file__).resolve().parent
results = []
cache_uuids = {}
for variant, driver, enabled in (
    ("baseline", args.baseline, False),
    ("patched-off", args.patched, False),
    ("patched-on", args.patched, True),
):
    driver = driver.resolve(strict=True)
    cases = [(shape, "run") for shape in ("128-1-1", "256-1-1")]
    if enabled:
        cases += [(shape, "run") for shape in ("257-1-1", "511-1-1", "512-1-1", "513-1-1",
                  "769-1-1", "1023-1-1", "1024-1-1", "32-30-1", "8-8-16", "17-19-3")]
        cases += [("nested", "reject")]
    else:
        cases += [("1024-1-1", "skip")]
    for shape, mode in cases:
        dims = [1024, 1, 1] if shape == "nested" else list(map(int, shape.split("-")))
        env = os.environ.copy()
        for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "PANVK_G77_LWG", "MESA_GL_VERSION_OVERRIDE",
                     "MESA_GLSL_VERSION_OVERRIDE", "PANVK_LWG_PRINT"):
            env.pop(name, None)
        env["PANVK_G77_LWG"] = "1" if enabled else "0"
        env["MESA_SHADER_CACHE_DISABLE"] = "false" if args.shader_cache else "true"
        env["XDG_CACHE_HOME"] = str(args.out.resolve().parent / "shader-cache")
        command = [str(here / "check"), str(driver), str(here / f"{shape}.spv"),
                   *map(str, dims), mode]
        try:
            run = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=20)
            output, code = run.stdout, run.returncode
        except subprocess.TimeoutExpired as error:
            output = str(error.stdout or b"") + "\nTIMEOUT"
            code = 124
        uuid = re.search(r"pipelineCacheUUID=([0-9a-f]{32})", output)
        if not uuid:
            raise SystemExit("Missing pipeline cache identity")
        previous = cache_uuids.setdefault(variant, uuid[1])
        if previous != uuid[1]:
            raise SystemExit("Cache identity changed between identical driver modes")
        log = f"{variant}-{shape}.txt"
        (args.out / log).write_text(output)
        result = {"variant": variant, "shape": shape, "mode": mode, "returncode": code,
                  "shader_cache": args.shader_cache,
                  "driver": str(driver), "sha256": hashlib.sha256(driver.read_bytes()).hexdigest(),
                  "log": log}
        results.append(result)
        (args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"{variant} {shape} {mode}: {code}\n{output}", flush=True)
        if code:
            raise SystemExit("Stopped at the first failed case; inspect the driver/compiler logs.")
if cache_uuids['patched-off'] == cache_uuids['patched-on']:
    raise SystemExit("Opt-in and opt-out must not share a pipeline cache UUID")
(args.out / 'cache-uuids.json').write_text(json.dumps(cache_uuids, indent=2) + "\n")
print("PASS: all controls, output oracles, rejection cases and cache identities passed")
