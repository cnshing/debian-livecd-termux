#!/data/data/com.termux/files/usr/bin/python
"""Open firefox-camera.html in headless Firefox, launched as the desktop launches it.

Usage, inside the desktop session:
    livecd-native exec python tests/camera/run-firefox.py

Runs the desktop's `firefox` launcher from the session PATH with a temporary
profile that allows camera access without asking. Passes when Firefox lists
the front and rear cameras by name and streams each at 20 fps or more with a
picture that is not uniform. System extensions are disabled in this disposable
profile: their welcome tabs can hide the camera page and throttle its compositor.
Only rates and luma levels are reported.
"""
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time

PAGE = Path(__file__).resolve().parent / 'firefox-camera.html'
PREFERENCES = {
    'extensions.enabledScopes': '1',
    'extensions.autoDisableScopes': '15',
    'media.navigator.permission.disabled': 'true',
    'media.navigator.streams.fake': 'false',
    'devtools.console.stdout.content': 'true',
    'browser.shell.checkDefaultBrowser': 'false',
    'browser.aboutwelcome.enabled': 'false',
    'datareporting.policy.dataSubmissionEnabled': 'false',
    'toolkit.telemetry.reportingpolicy.firstRun': 'false',
}


def main():
    launcher = shutil.which('firefox')
    profile = tempfile.mkdtemp(prefix='camera-firefox-', dir=os.environ.get('TMPDIR'))
    try:
        Path(profile, 'user.js').write_text(''.join(f'user_pref("{k}", {v});\n' for k, v in PREFERENCES.items()))
        print('launcher:', launcher, flush=True)
        process = subprocess.Popen([launcher, '--headless', '--no-remote', '--profile', profile, PAGE.as_uri()],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        lines, buffer = [], b''
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 150
        try:
            while time.monotonic() < deadline and not any(l in ('done',) or l.startswith('error') for l in lines):
                if not selector.select(timeout=1):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                buffer += chunk
                *complete, buffer = buffer.split(b'\n')
                for raw in complete:
                    line = raw.decode(errors='replace')
                    if 'CAMTEST ' in line:
                        # Firefox escapes the quotes in what it prints from the console.
                        message = line.split('CAMTEST ', 1)[1].strip().rstrip('"').replace('\\"', '"')
                        lines.append(message)
                        print('firefox:', message, flush=True)
                    elif re.search(r'camera|v4l2|video ?capture|pipewire', line, re.I):
                        print('firefox log:', line[-200:], flush=True)
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    listed = next((l for l in lines if l.startswith('cameras ')), '')
    ok = 'Front camera' in listed and 'Rear camera' in listed
    print(f"{'PASS' if ok else 'FAIL'} Firefox lists both cameras: {listed or 'nothing'}")
    complete = 'done' in lines and not any(line.startswith('error') for line in lines)
    print(f"{'PASS' if complete else 'FAIL'} Firefox camera test completed")
    results = [ok, complete]
    for name in ('Front camera', 'Rear camera'):
        line = next((l for l in lines if l.startswith(f'stream "{name}')), '')
        match = re.search(r'fps ([\d.]+) mean ([\d.]+) spread ([\d.]+)', line)
        good = bool(match) and float(match[1]) >= 20 and float(match[3]) > 1
        results.append(good)
        print(f"{'PASS' if good else 'FAIL'} Firefox streams the {name.lower()}: "
              f"{match[0] if match else line or 'no stream'}")
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
