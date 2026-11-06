#!/usr/bin/env python3
"""Host checks for android-v4l2 and its desktop wiring.
Usage: python3 tests/camera/test-camera-controller.py

The lifecycle test runs the real supervisor against stand-in pipewire,
wireplumber and camera-node programs, so it needs no phone or camera."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
CONTROLLER = REPO / 'packages/android-v4l2/camera.py'
spec = importlib.util.spec_from_file_location('camera', CONTROLLER)
camera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera)
sys.path.insert(0, str(REPO / 'src/native'))
import desktop

# This phone's cameras, as camera-list reports them: rear 0, front 1, two more
# lenses, and a depth camera without YUV output.
NOTE10 = [
    {'id': '0', 'facing': 'rear', 'sizes': [[4032, 3024], [1920, 1080], [1280, 720], [640, 480]],
     'fps_ranges': [[15, 15], [7, 24], [24, 24], [8, 30], [30, 30]]},
    {'id': '1', 'facing': 'front', 'sizes': [[3216, 1808], [1280, 720], [640, 480]],
     'fps_ranges': [[15, 15], [8, 30], [30, 30]]},
    {'id': '2', 'facing': 'rear', 'sizes': [[1280, 720]], 'fps_ranges': [[30, 30]]},
    {'id': '3', 'facing': 'front', 'sizes': [[1280, 720]], 'fps_ranges': [[30, 30]]},
    {'id': '4', 'facing': 'rear', 'sizes': [], 'fps_ranges': [[5, 5], [20, 20]]},
]


class Selection(unittest.TestCase):
    def test_front_and_rear_by_lens_direction_not_camera_id(self):
        chosen = camera.choose(NOTE10)
        self.assertEqual([(c['device'], c['name'], c['camera']) for c in chosen],
                         [('/dev/video0', 'Front camera', '1'), ('/dev/video1', 'Rear camera', '0')])
        self.assertEqual({(c['size'], c['fps'], c['fps_min']) for c in chosen}, {('1280x720', 30, 30)})

    def test_a_phone_listing_front_first_keeps_the_same_devices(self):
        swapped = [dict(NOTE10[1], id='0'), dict(NOTE10[0], id='1')]
        self.assertEqual([(c['device'], c['camera']) for c in camera.choose(swapped)],
                         [('/dev/video0', '0'), ('/dev/video1', '1')])

    def test_depth_only_and_missing_directions_publish_nothing(self):
        self.assertEqual(camera.choose([NOTE10[4]]), [])
        self.assertEqual([c['name'] for c in camera.choose([NOTE10[0], NOTE10[4]])], ['Rear camera'])

    def test_sizes_and_rates_come_from_what_android_lists(self):
        self.assertEqual(camera.pick_size([[4000, 3000], [960, 720], [640, 360]]), (640, 360))
        self.assertEqual(camera.pick_size([[4000, 3000], [960, 720], [800, 600]]), (960, 720))
        self.assertEqual(camera.pick_size([[4000, 3000], [1920, 1440]]), (1920, 1440))
        self.assertEqual(camera.pick_fps([[15, 15], [8, 30]]), (8, 30))
        self.assertEqual(camera.pick_fps([[15, 15], [24, 24], [60, 60]]), (24, 24))


class Environment(unittest.TestCase):
    def test_helpers_get_android_libraries_and_the_session_pipewire(self):
        run = Path('/run/session')
        with mock.patch.dict(os.environ, {
                'LD_LIBRARY_PATH': '/prefix/lib', 'PIPEWIRE_REMOTE': 'fx', 'PIPEWIRE_RUNTIME_DIR': '/fx',
                'LD_PRELOAD': f'/lib/libandroid-procfs.so:{camera.PRELOAD}:/lib/libtermux-exec.so'}, clear=True):
            env = camera.child_environment(run)
        self.assertNotIn('LD_LIBRARY_PATH', env)
        self.assertNotIn('PIPEWIRE_REMOTE', env)
        self.assertEqual(env['LD_PRELOAD'], '/lib/libandroid-procfs.so:/lib/libtermux-exec.so')
        self.assertEqual(env['PIPEWIRE_RUNTIME_DIR'], str(run))
        self.assertEqual(env['ANDROID_V4L2_DIR'], str(run / 'android-v4l2'))


class DesktopWiring(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.command = root / 'bin/android-v4l2'
        self.command.parent.mkdir()
        self.command.touch(mode=0o755)
        self.library = root / 'lib/libandroid-v4l2.so'
        self.library.parent.mkdir()
        self.library.touch()
        self.config = root / 'config'
        self.config.mkdir()
        self.patches = mock.patch.multiple(desktop, CAMERA=self.command, CAMERA_PRELOAD=self.library,
                                           CONFIG=self.config, RESOURCE_PRELOAD=root / 'lib/missing.so')
        self.patches.start()

    def tearDown(self):
        self.patches.stop()
        self.temporary.cleanup()

    def preload(self, accepted=True, inherited='/lib/libtermux-exec.so'):
        with mock.patch.dict(os.environ, {'LD_PRELOAD': inherited}, clear=True), \
                mock.patch.object(desktop, 'probe_preload', return_value=accepted), \
                mock.patch.object(desktop, 'apply_renderer', side_effect=lambda env, renderer: env), \
                contextlib.redirect_stderr(io.StringIO()):
            return desktop.environment()['LD_PRELOAD'].split(':')

    def test_session_preloads_the_camera_last(self):
        self.assertEqual(self.preload(), ['/lib/libtermux-exec.so', str(self.library)])

    def test_a_session_program_asking_again_gets_the_camera_once(self):
        inside = f'/lib/libtermux-exec.so:{self.library}'
        self.assertEqual(self.preload(inherited=inside), ['/lib/libtermux-exec.so', str(self.library)])

    def test_camera_stays_out_when_disabled_or_rejected(self):
        self.assertEqual(self.preload(accepted=False), ['/lib/libtermux-exec.so'])
        (self.config / 'integrations.json').write_text('{"camera": false}')
        self.assertEqual(self.preload(), ['/lib/libtermux-exec.so'])
        self.assertEqual(desktop.camera_status(Path(self.temporary.name)), {'status': 'disabled'})

    def test_status_reports_a_dead_supervisor_as_stopped(self):
        run = Path(self.temporary.name)
        record = {'pid': os.getpid(), 'start': desktop.process_identity(os.getpid())[1], 'status': 'ready',
                  'devices': [{'device': '/dev/video0', 'name': 'Front camera', 'state': 'idle', 'camera': '1'}]}
        (run / 'android-v4l2.json').write_text(json.dumps(record))
        self.assertEqual(desktop.camera_status(run), {'status': 'ready', 'devices': [
            {'device': '/dev/video0', 'name': 'Front camera', 'state': 'idle'}]})
        (run / 'android-v4l2.json').write_text(json.dumps(dict(record, start='1')))
        self.assertEqual(desktop.camera_status(run)['status'], 'stopped')


class PermissionNotice(unittest.TestCase):
    def test_a_refused_camera_stays_reported_until_one_opens(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(camera, 'LOGS', Path(temporary) / 'logs'):
            run = Path(temporary)
            supervisor = camera.Supervisor(run)
            supervisor.status['devices'] = camera.choose(NOTE10)
            for directory in ('dev', 'state'):
                (run / 'android-v4l2' / directory).mkdir(parents=True)
            for number in (0, 1):
                (run / 'android-v4l2/dev' / f'video{number}').touch()

            def after(front_state):
                (run / 'android-v4l2/state/video0').write_text(front_state + '\n')
                (run / 'android-v4l2/state/video1').write_text('idle\n')
                supervisor.refresh()
                return json.loads((run / 'android-v4l2.json').read_text()).get('detail', '')

            self.assertNotIn('CAMERA', after('idle'))
            self.assertIn('pm grant com.termux.api android.permission.CAMERA', after('waiting permission-denied'))
            self.assertIn('CAMERA', after('idle'))
            self.assertNotIn('CAMERA', after('open'))


STAND_INS = {
    'pipewire': '''
        touch "$PIPEWIRE_RUNTIME_DIR/pipewire-0"
        trap 'rm -f "$PIPEWIRE_RUNTIME_DIR/pipewire-0"; exit 0' TERM
        while :; do sleep 0.1; done''',
    'wireplumber': '''
        trap 'exit 0' TERM
        while :; do sleep 0.1; done''',
    'camera-list': f'''
        echo '{json.dumps(NOTE10)}' ''',
    # Publishes like camera-node: state first, the /dev marker last.
    'camera-node': '''
        for arg; do case $arg in --device=*) n=${arg#--device=};; esac; done
        echo "$$" >> "$PIPEWIRE_RUNTIME_DIR/pids-$n"
        mkdir -p "$ANDROID_V4L2_DIR/state" "$ANDROID_V4L2_DIR/dev"
        echo idle > "$ANDROID_V4L2_DIR/state/video$n"
        touch "$ANDROID_V4L2_DIR/dev/video$n"
        trap 'rm -f "$ANDROID_V4L2_DIR/dev/video$n" "$ANDROID_V4L2_DIR/state/video$n"; exit 0' TERM
        while :; do sleep 0.1; done''',
}


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.bin = root / 'bin'
        self.bin.mkdir()
        for name, body in STAND_INS.items():
            path = self.bin / name
            path.write_text('#!/bin/sh\n' + textwrap.dedent(body) + '\n')
            path.chmod(0o755)
        self.run_dir = root / 'run'
        self.run_dir.mkdir(mode=0o700)
        self.home = root / 'home'
        launcher = (f'import importlib.util, sys; from pathlib import Path\n'
                    f'spec = importlib.util.spec_from_file_location("camera", {str(CONTROLLER)!r})\n'
                    f'camera = importlib.util.module_from_spec(spec); spec.loader.exec_module(camera)\n'
                    f'camera.LIBEXEC = Path({str(self.bin)!r})\n'
                    f'camera.LOGS = Path({str(self.home)!r}) / "logs"\n'
                    f'sys.exit(camera.Supervisor(Path({str(self.run_dir)!r})).main())\n')
        env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}', XDG_RUNTIME_DIR=str(self.run_dir),
                   LD_LIBRARY_PATH='/should/not/pass')
        self.supervisor = subprocess.Popen([sys.executable, '-c', launcher], env=env)

    def tearDown(self):
        if self.supervisor.poll() is None:
            self.supervisor.kill()
            self.supervisor.wait()
        self.temporary.cleanup()

    def status(self):
        try:
            return json.loads((self.run_dir / 'android-v4l2.json').read_text())
        except (OSError, ValueError):
            return {}

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(self.status()):
                return self.status()
            time.sleep(0.1)
        self.fail('timed out; last status ' + json.dumps(self.status()))

    def pids(self, number):
        return [int(line) for line in (self.run_dir / f'pids-{number}').read_text().split()]

    def test_publishes_restarts_and_cleans_up(self):
        status = self.wait_for(lambda s: s.get('status') == 'ready')
        self.assertEqual([(d['device'], d['state']) for d in status['devices']],
                         [('/dev/video0', 'idle'), ('/dev/video1', 'idle')])

        # A node that dies comes back as the same device; the other is untouched.
        first = self.pids(0)[0]
        os.kill(first, signal.SIGKILL)
        self.wait_for(lambda s: len(self.pids(0)) == 2 and s.get('status') == 'ready')
        self.assertEqual(len(self.pids(1)), 1)

        self.supervisor.send_signal(signal.SIGTERM)
        self.assertEqual(self.supervisor.wait(timeout=10), 0)
        self.assertEqual(self.status()['status'], 'stopped')
        for pid in self.pids(0)[1:] + self.pids(1):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        self.assertEqual(list((self.run_dir / 'android-v4l2').rglob('*')), [])
        self.assertFalse((self.run_dir / 'pipewire-0').exists())


if __name__ == '__main__':
    unittest.main()
