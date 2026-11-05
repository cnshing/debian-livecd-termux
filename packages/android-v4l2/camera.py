#!/data/data/com.termux/files/usr/bin/python
"""Android's front and rear cameras for native Linux programs.

run      supervise a PipeWire for this session ($XDG_RUNTIME_DIR/pipewire-0),
         WirePlumber, and one camera node per lens direction; libandroid-v4l2.so
         presents the nodes to V4L2 programs as /dev/video0 (front) and
         /dev/video1 (rear). The desktop session starts this.
status   print the running supervisor's state as JSON
list     print Android's cameras and the choice run would make, opening none
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

PREFIX = Path('/data/data/com.termux/files/usr')
LIBEXEC = PREFIX / 'libexec/android-v4l2'
PRELOAD = PREFIX / 'lib/android-v4l2/libandroid-v4l2.so'
LOGS = Path.home() / '.local/state/android-v4l2'
# Lens direction, device number and name; Android's camera IDs differ between phones.
DEVICES = (('front', 0, 'Front camera'), ('rear', 1, 'Rear camera'))
TARGET_AREA = 1280 * 720
TARGET_FPS = 30
RESTARTS = 5  # within RESTART_WINDOW seconds, before giving up on a camera
RESTART_WINDOW = 60
NO_PERMISSION = ('Android refused the camera. Termux has no CAMERA permission of its own; grant it to '
                 'Termux:API, which shares its user ID: adb shell pm grant com.termux.api android.permission.CAMERA')


def runtime():
    value = os.environ.get('XDG_RUNTIME_DIR')
    if not value or not Path(value).is_dir():
        raise SystemExit('android-v4l2: XDG_RUNTIME_DIR must name the session runtime directory')
    return Path(value)


def status_path(run):
    return run / 'android-v4l2.json'


def child_environment(run):
    env = dict(os.environ)
    # $PREFIX/lib holds libandroid-stub's libmediandk.so, which must not shadow Android's.
    env.pop('LD_LIBRARY_PATH', None)
    preload = [item for item in env.get('LD_PRELOAD', '').replace(':', ' ').split()
               if Path(item).name != PRELOAD.name]
    if preload:
        env['LD_PRELOAD'] = ':'.join(preload)
    else:
        env.pop('LD_PRELOAD', None)
    # The audio-effects PipeWire sets these for its own processes only.
    for key in [key for key in env if key.startswith('PIPEWIRE_')]:
        del env[key]
    env.update(PIPEWIRE_RUNTIME_DIR=str(run), ANDROID_V4L2_DIR=str(run / 'android-v4l2'))
    return env


def enumerate_cameras(env):
    result = subprocess.run([str(LIBEXEC / 'camera-list')], env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f'camera-list exited with status {result.returncode}')
    return json.loads(result.stdout)


def pick_size(sizes):
    sizes = [tuple(size) for size in sizes]
    smaller = [size for size in sizes if size[0] * size[1] <= TARGET_AREA]
    if smaller:
        return max(smaller, key=lambda size: (size[0] * 9 == size[1] * 16, size[0] * size[1]))
    return min(sizes, key=lambda size: size[0] * size[1])


def pick_fps(ranges):
    """An auto-exposure range Android lists: fixed at 30 fps if possible, so frames
    arrive at the rate the node advertises."""
    usable = [(low, high) for low, high in map(tuple, ranges) if high <= TARGET_FPS]
    if not usable:
        return TARGET_FPS, TARGET_FPS
    return max(usable, key=lambda item: (item[1], item[0]))


def choose(cameras):
    """The first camera Android lists for each direction that offers YUV output."""
    chosen = []
    for facing, device, name in DEVICES:
        camera = next((camera for camera in cameras if camera['facing'] == facing and camera['sizes']), None)
        if camera:
            width, height = pick_size(camera['sizes'])
            low, high = pick_fps(camera['fps_ranges'])
            chosen.append({'device': f'/dev/video{device}', 'number': device, 'name': name, 'facing': facing,
                           'camera': camera['id'], 'size': f'{width}x{height}', 'fps': high, 'fps_min': low})
    return chosen


def write_status(run, status):
    path = status_path(run)
    temporary = path.with_name('.' + path.name + '.tmp')
    temporary.write_text(json.dumps(status))
    temporary.replace(path)


class Supervisor:
    def __init__(self, run):
        self.run = run
        self.env = child_environment(run)
        self.v4l2 = run / 'android-v4l2'
        self.stopping = False
        self.status = {'pid': os.getpid(), 'start': process_start(os.getpid()), 'status': 'starting',
                       'devices': []}
        self.core = []
        self.nodes = {}
        self.core_error = None
        self.denied = False
        LOGS.mkdir(parents=True, exist_ok=True)

    def report(self, status, detail=None):
        self.status['status'] = status
        if detail:
            self.status['detail'] = detail
        else:
            self.status.pop('detail', None)
        write_status(self.run, self.status)

    def spawn(self, name, command):
        log = open(LOGS / f'{name}.log', 'w')
        try:
            return subprocess.Popen(command, env=self.env, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT)
        finally:
            log.close()

    def start_core(self):
        socket = self.run / 'pipewire-0'
        socket.unlink(missing_ok=True)
        pipewire = self.spawn('pipewire', ['pipewire'])
        self.core = [pipewire]
        deadline = time.monotonic() + 10
        while not socket.exists():
            if pipewire.poll() is not None or self.stopping or time.monotonic() > deadline:
                raise RuntimeError('PipeWire did not start; see ' + str(LOGS / 'pipewire.log'))
            time.sleep(0.05)
        # The policy profile links streams without probing Android's inaccessible ALSA,
        # Bluetooth and V4L2 hardware.
        self.core.append(self.spawn('wireplumber', ['wireplumber', '--profile=policy']))

    def start_node(self, device):
        command = [str(LIBEXEC / 'camera-node'), '--camera=' + device['camera'],
                   f'--device={device["number"]}', '--name=' + device['name'], '--size=' + device['size'],
                   f'--fps={device["fps"]}', f'--fps-min={device["fps_min"]}']
        self.nodes[device['number']] = self.spawn(f'video{device["number"]}', command)

    def unpublish(self, number):
        """What a node that died without cleaning up left behind: programs must not
        find a device that nothing serves."""
        sys_dir = self.v4l2 / 'sys/class/video4linux' / f'video{number}'
        for path in (self.v4l2 / 'dev' / f'video{number}', self.v4l2 / 'state' / f'video{number}',
                     *(sys_dir.iterdir() if sys_dir.is_dir() else ())):
            path.unlink(missing_ok=True)
        if sys_dir.is_dir():
            sys_dir.rmdir()

    def stop_children(self):
        children = [*self.nodes.values(), *self.core]
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 5
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        self.nodes, self.core = {}, []
        for path in sorted(self.v4l2.rglob('*'), reverse=True) if self.v4l2.exists() else ():
            path.rmdir() if path.is_dir() else path.unlink()

    def refresh(self):
        before = json.dumps(self.status)
        for device in self.status['devices']:
            if device.get('state') == 'failed':
                continue
            device['state'] = 'starting'
            if (self.v4l2 / 'dev' / f'video{device["number"]}').exists():
                try:
                    device['state'] = (self.v4l2 / 'state' / f'video{device["number"]}').read_text().strip()
                except OSError:
                    device['state'] = 'idle'
        live = [device for device in self.status['devices'] if device['state'] != 'failed']
        status = 'failed' if not live else 'ready' if all(device['state'] != 'starting' for device in live) \
            else 'starting'
        details = [f'{device["name"]} kept exiting; see {LOGS / ("video%d.log" % device["number"])}'
                   for device in self.status['devices'] if device['state'] == 'failed']
        # Kept after the stream gives up, until a camera opens: then it was granted.
        if any(device['state'] == 'waiting permission-denied' for device in live):
            self.denied = True
        elif any(device['state'] == 'open' for device in live):
            self.denied = False
        if self.denied:
            details.append(NO_PERMISSION)
        if status == 'starting' and self.core_error:
            details.append(self.core_error)
        self.status['status'] = status
        self.status.pop('detail', None)
        if details:
            self.status['detail'] = '; '.join(details)
        if json.dumps(self.status) != before:
            write_status(self.run, self.status)

    def supervise(self):
        restarts = {}

        def allowed(key):
            now = time.monotonic()
            recent = [moment for moment in restarts.get(key, []) if now - moment < RESTART_WINDOW]
            restarts[key] = recent + [now]
            return len(recent) < RESTARTS

        while not self.stopping:
            try:
                self.start_core()
                for device in self.status['devices']:
                    if device.get('state') != 'failed':
                        self.start_node(device)
                while not self.stopping:
                    if any(child.poll() is not None for child in self.core):
                        raise RuntimeError('PipeWire or WirePlumber exited; see ' + str(LOGS))
                    for device in self.status['devices']:
                        node = self.nodes.get(device['number'])
                        if not node or node.poll() is None:
                            continue
                        del self.nodes[device['number']]
                        self.unpublish(device['number'])
                        self.refresh()
                        if allowed(device['device']):
                            time.sleep(1)
                            self.start_node(device)
                        else:
                            device['state'] = 'failed'
                            self.status['detail'] = (f'{device["name"]} kept exiting; see '
                                                     + str(LOGS / f'video{device["number"]}.log'))
                    self.refresh()
                    self.core_error = None
                    time.sleep(0.5)
            except (OSError, RuntimeError) as error:
                if self.stopping:
                    break
                self.stop_children()
                if not allowed('core'):
                    self.report('failed', str(error))
                    return 1
                self.core_error = str(error)
                self.report('starting', self.core_error)
                time.sleep(2)
        return 0

    def main(self):
        def stop(_signum, _frame):
            self.stopping = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            try:
                self.status['devices'] = choose(enumerate_cameras(self.env))
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
                self.report('unavailable', 'Cannot read Android camera characteristics: ' + str(error))
                return 1
            if not self.status['devices']:
                self.report('unavailable', 'Android lists no front or rear camera with YUV output')
                return 0
            self.report('starting')
            return self.supervise()
        finally:
            self.stop_children()
            for device in self.status['devices']:
                device['state'] = 'stopped'
            if self.status['status'] not in ('failed', 'unavailable'):
                self.report('stopped')


def process_start(pid):
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return None if fields[0] == 'Z' else fields[19]


def running_status(run):
    data = json.loads(status_path(run).read_text())
    try:
        alive = process_start(int(data['pid'])) == data['start']
    except (OSError, ValueError, KeyError, TypeError):
        alive = False
    if not alive and data.get('status') in ('starting', 'ready'):
        data['status'] = 'stopped'
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['run', 'status', 'list'])
    args = parser.parse_args()
    if args.action == 'list':
        cameras = enumerate_cameras(child_environment(Path(os.environ.get('TMPDIR', PREFIX / 'tmp'))))
        print(json.dumps({'cameras': cameras, 'chosen': choose(cameras)}, indent=2))
        return 0
    run = runtime()
    if args.action == 'run':
        return Supervisor(run).main()
    try:
        print(json.dumps(running_status(run)))
    except (OSError, ValueError):
        print(json.dumps({'status': 'stopped'}))
    return 0



if __name__ == '__main__':
    sys.exit(main())
