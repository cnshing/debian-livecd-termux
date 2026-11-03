#!/usr/bin/env python3
"""Open chromium-camera.html in headless Chromium and check what it reports.

Usage: run-chromium.py PAGE OUT_DIR
Passes when Chromium lists the cameras, streams the front one at 25 fps or
more, and the wall region is warm (red above blue), as the direct captures
were. Saves the page's JPEG of the last frame as OUT_DIR/chromium.jpg.
"""
import base64
import os
import selectors
import signal
import subprocess
import sys
import time

page, out = sys.argv[1], sys.argv[2]
# Lets the page turn the boot-clock stamps in each frame into wall-clock time.
offset = time.time_ns() - time.clock_gettime_ns(time.CLOCK_BOOTTIME)
cmd = ["chromium-browser", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run",
       "--use-fake-ui-for-media-stream", "--password-store=basic",
       "--enable-logging=stderr", "--log-level=0", f"--user-data-dir={out}/chromium-profile",
       f"file://{os.path.abspath(page)}?offset={offset}"]
proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        start_new_session=True)
results, errors = {}, []
selector = selectors.DefaultSelector()
selector.register(proc.stderr, selectors.EVENT_READ)
buffer, deadline = b"", time.monotonic() + 60
try:
    while time.monotonic() < deadline and "done" not in results and "error" not in results:
        if not selector.select(timeout=1):
            continue
        chunk = os.read(proc.stderr.fileno(), 65536)
        if not chunk:
            break
        buffer += chunk
        *lines, buffer = buffer.split(b"\n")
        for raw in lines:
            line = raw.decode(errors="replace")
            if "CAMTEST " in line:
                # [...:INFO:CONSOLE(12)] "CAMTEST fps 30.0", source: file:///...html (12)
                message = line.split("CAMTEST ", 1)[1].split('", source:')[0]
                key, _, value = message.partition(" ")
                results[key] = value
                if key != "jpeg":
                    print(f"chromium: {message}")
            elif ":ERROR:" in line and ("video" in line.lower() or "v4l2" in line.lower() or "capture" in line.lower()):
                errors.append(line[-200:])
finally:
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)

for line in errors[:5]:
    print("chromium log:", line)
if "jpeg" in results and "," in results["jpeg"]:
    with open(os.path.join(out, "chromium.jpg"), "wb") as f:
        f.write(base64.b64decode(results["jpeg"].split(",", 1)[1]))
try:
    fps = float(results.get("fps", 0))
    r, g, b = (int(x) for x in results.get("wall", "0 0 0").split())
except ValueError:
    fps, r, b = 0, 0, 0
ok = "done" in results and fps >= 25 and r > b
print(f"{'PASS' if ok else 'FAIL'} Chromium camera: {fps:.1f} fps, wall red {r} blue {b}, "
      f"exposure start to JavaScript {results.get('latency', 'unmeasured')} ms")
sys.exit(0 if ok else 1)
