#!/data/data/com.termux/files/usr/bin/python
"""Acceptance test for the cameras the installed desktop publishes.

Run inside the running desktop session, as its programs see it:
    livecd-native exec python tests/camera/test-desktop-camera.py [--stream]

It starts no PipeWire or camera node of its own and supplies no preload: a
missing or broken desktop integration fails it. Without --stream it opens no
camera. --stream captures from each camera, switches between them, and has
both asked for at once; frames are judged only by rate and luma levels, so
no picture of whoever is in front of the phone is kept.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PRELOAD = 'libandroid-v4l2.so'
EXPECTED = [('/dev/video0', 'Front camera'), ('/dev/video1', 'Rear camera')]
results = []


def check(label, ok, detail=''):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} {label}{': ' + detail if detail else ''}", flush=True)
    return ok


def camera_status():
    status = json.loads(subprocess.check_output(['livecd-native', 'status'], text=True))
    return status, status.get('integrations', {}).get('features', {}).get('camera', {})


def states():
    return [device.get('state') for device in camera_status()[1].get('devices', [])]


def wait_states(wanted, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if states() == wanted:
            return True
        time.sleep(0.25)
    return False


def read(device, fmt, frames, name, timeout=5):
    env = dict(os.environ, V4L2_READ_TIMEOUT=str(timeout))
    return subprocess.Popen([sys.executable, str(HERE / 'v4l2-read.py'), device, fmt, '1280', '720', str(frames), name],
                            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)


def finished(process, label):
    output = process.communicate(timeout=120)[0]
    lines = [line for line in output.splitlines() if line.startswith(('frames', 'luma', 'wrong', 'timed'))]
    levels = next((line for line in lines if line.startswith('luma')), '')
    try:
        spread = float(levels.split('spread ')[1].split(',')[0])
    except (IndexError, ValueError):
        spread = 0
    # A covered or uniform picture has almost no spread; a scene has some.
    return check(label, process.returncode == 0 and spread > 1, '; '.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stream', action='store_true', help='open the cameras and capture frames')
    args = parser.parse_args()

    preload = os.environ.get('LD_PRELOAD', '')
    check('the session preloads the camera library', PRELOAD in preload, preload)
    status, camera = camera_status()
    check('the desktop reports its cameras ready', camera.get('status') == 'ready', json.dumps(camera))
    devices = [(device.get('device'), device.get('name')) for device in camera.get('devices', [])]
    check('front is /dev/video0 and rear is /dev/video1', devices == EXPECTED, str(devices))
    shell = status.get('shell')
    try:
        maps = Path(f'/proc/{shell}/maps').read_text()
    except (OSError, TypeError):
        maps = ''
    check('GNOME Shell, started by the desktop, has the preload loaded', PRELOAD in maps, f'pid {shell}')

    for number, (device, name) in enumerate(EXPECTED):
        result = subprocess.run([sys.executable, str(HERE / 'v4l2-compat.py'), str(number), name],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        failed = [line for line in result.stdout.splitlines() if line.startswith('FAIL')]
        check(f'{device} looks like a V4L2 device', result.returncode == 0, '; '.join(failed) or name)

    dump = subprocess.run(['pw-dump'], env={k: v for k, v in os.environ.items() if k != 'LD_PRELOAD'},
                          stdin=subprocess.DEVNULL, capture_output=True, text=True)
    try:
        nodes = sorted((o['info']['props'].get('object.path'), o['info']['props'].get('node.description'))
                       for o in json.loads(dump.stdout) if o.get('type') == 'PipeWire:Interface:Node'
                       and o['info']['props'].get('media.class') == 'Video/Source')
    except (ValueError, KeyError, TypeError):
        nodes = []
    check('PipeWire programs see the same two cameras', nodes == [('v4l2:' + d, n) for d, n in EXPECTED],
          str(nodes))
    check('neither camera is open while idle', states() == ['idle', 'idle'], str(states()))

    if args.stream:
        finished(read('/dev/video0', 'YUYV', 150, 'Front camera'), 'front camera streams')
        finished(read('/dev/video1', 'NV12', 90, 'Rear camera'), 'switching to the rear camera streams')
        finished(read('/dev/video0', 'NV12', 90, 'Front camera'), 'switching back to the front camera streams')
        check('both cameras are released after the last stream', wait_states(['idle', 'idle'], 6), str(states()))

        # Both asked for at once: the newer stream gets its camera; the older keeps
        # its identity and resumes once the newer one is done.
        front = read('/dev/video0', 'NV12', 300, 'Front camera', timeout=15)
        time.sleep(3)
        rear = read('/dev/video1', 'NV12', 60, 'Rear camera')
        time.sleep(1)
        print('states with both streaming:', states(), flush=True)
        finished(rear, 'the newer stream gets its camera')
        finished(front, 'the older stream resumes the same camera')
        check('both cameras are released afterwards', wait_states(['idle', 'idle'], 6), str(states()))

    print(f'RESULT: {results.count(False)} failed of {len(results)}')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
