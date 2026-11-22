#!/usr/bin/env python3
"""Exercise on-demand Bluetooth with real PulseAudio and a simulated Android route.

Usage: python3 tests/mic/test-auto-bluetooth.py
Requires pulseaudio and its pactl/parec/pacat clients; never uses host audio hardware.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('bluetooth', Path(__file__).resolve().parents[2]
        / 'packages/android-pulseaudio-mic/bluetooth.py')
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


def eventually(check, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError('Condition did not become true within timeout')


@unittest.skipUnless(all(shutil.which(command) for command in ('pulseaudio', 'pactl', 'parec', 'pacat')),
                     'requires PulseAudio server and clients')
class AutoBluetooth(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bt-auto-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ('tmp', 'runtime', 'state', 'config', 'home'):
            (self.root / name).mkdir()
        self.env = dict(os.environ, PULSE_SERVER='unix:' + str(self.root / 'pulse'))
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        server_env = dict(self.env, PULSE_RUNTIME_PATH=str(self.root / 'runtime'),
            PULSE_STATE_PATH=str(self.root / 'state'), PULSE_CONFIG_PATH=str(self.root / 'config'),
            HOME=str(self.root / 'home'))
        server_env.pop('PULSE_SERVER')
        self.log = (self.root / 'pulse.log').open('w')
        self.addCleanup(self.log.close)
        self.pa = subprocess.Popen(['pulseaudio', '-n', '--daemonize=no', '--use-pid-file=no',
            '--exit-idle-time=-1', '--load=module-null-sink sink_name=media',
            '--load=module-null-sink sink_name=other',
            '--load=module-null-source source_name=' + bt.SILENCE,
            '--load=module-native-protocol-unix socket=' + str(self.root / 'pulse') + ' auth-anonymous=1'],
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, env=server_env)
        self.addCleanup(bt.stop_process, self.pa)
        eventually(lambda: (self.root / 'pulse').exists())
        bt.pulse('set-default-sink', 'media')
        bt.pulse('set-default-source', bt.SILENCE)
        self.real_pulse = bt.pulse
        self.route_events = []
        self.fail_next = False
        self.fail_capture = False
        self.loss = None
        test = self

        class Android:
            def __enter__(self):
                self.connection, self.peer = socket.socketpair()
                self.buffer = b''
                self.command = None
                return self

            def send(self, command, **arguments):
                self.command = command

            def receive(self):
                if self.command == 'devices':
                    return {'event': 'devices', 'bluetooth_devices': [{'id': 7, 'name': 'Test headset'}]}
                if test.fail_next:
                    test.fail_next = False
                    raise bt.RouteError('Android rejected route')
                if test.loss == self:
                    raise bt.RouteError('headset disconnected')
                test.route_events.append('enable')
                test.current_route = self
                return {'event': 'ready'}

            def __exit__(self, *ignored):
                if self.command == 'enable':
                    # Native recorder must be gone before releasing SCO.
                    sources = {item['name'] for item in bt.pulse_objects('sources')}
                    test.route_events.append(('release', bt.CAPTURE in sources))
                self.connection.close()
                self.peer.close()

        def pulse(*args):
            if args[:2] == ('load-module', 'module-sles-source'):
                if self.fail_capture:
                    raise bt.RouteError('Native capture failed')
                args = ('load-module', 'module-null-source', 'source_name=' + bt.CAPTURE,
                        'format=s16le', 'rate=48000', 'channels=1')
            return self.real_pulse(*args)

        player = self.root / 'player'
        player.write_text('#!/usr/bin/env python3\nimport os, select, sys\n'
            'fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NONBLOCK)\n'
            'print(\'{"ready":true}\', flush=True)\n'
            'while True:\n'
            ' select.select([fd], [], [])\n'
            ' if not os.read(fd, 65536): break\n')
        player.chmod(0o755)
        patch = mock.patch.multiple(bt, PREFIX=self.root, CONTROL=self.root / 'control', PLAYER=player,
                Bridge=Android, pulse=pulse, microphone=lambda command: {'microphone': 'off'})
        patch.start()
        self.addCleanup(patch.stop)
        self.errors = []

        def serve():
            try:
                with bt.ControlServer() as control:
                    bt.auto_session(0, True, control)
            except BaseException as error:
                self.errors.append(error)
        self.thread = threading.Thread(target=serve)
        self.thread.start()
        self.addCleanup(self.stop_controller)
        eventually(lambda: bt.control('status').get('active'))

    def stop_controller(self):
        if self.thread.is_alive():
            bt.control('off')
            self.thread.join(timeout=15)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors, [])

    def recording(self, source=bt.INPUT):
        process = subprocess.Popen(['parec', '--raw', '--device=' + source],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.log)
        self.addCleanup(bt.stop_process, process)
        return process

    def routed(self):
        return bt.control('status').get('route_active')

    def test_idle_enumeration_then_two_recorders_and_media_restoration(self):
        self.assertEqual(self.route_events, [])
        self.assertEqual(bt.pulse('get-default-source'), bt.INPUT)
        self.assertEqual(bt.pulse('get-default-sink'), 'media')
        self.assertNotIn(bt.CAPTURE, {item['name'] for item in bt.pulse_objects('sources')})
        unrelated = self.recording(bt.SILENCE)
        time.sleep(0.2)
        self.assertFalse(self.routed())
        with open('/dev/zero', 'rb') as silence:
            playback = subprocess.Popen(['pacat', '--playback', '--raw'], stdin=silence,
                                        stdout=subprocess.DEVNULL, stderr=self.log)
        self.addCleanup(bt.stop_process, playback)
        eventually(lambda: bool(bt.pulse_objects('sink-inputs')))
        stream_id = bt.pulse_objects('sink-inputs')[0]['index']

        def playback_sink():
            stream = next(item for item in bt.pulse_objects('sink-inputs') if item['index'] == stream_id)
            return next(item['name'] for item in bt.pulse_objects('sinks') if item['index'] == stream['sink'])

        self.assertEqual(playback_sink(), 'media')
        first = self.recording()
        eventually(self.routed)
        self.assertEqual(bt.pulse('get-default-sink'), bt.OUTPUT)
        self.assertEqual(playback_sink(), bt.OUTPUT)
        second = self.recording()
        source_id = next(item['index'] for item in bt.pulse_objects('sources') if item['name'] == bt.INPUT)
        eventually(lambda: len([item for item in bt.pulse_objects('source-outputs')
                               if item['source'] == source_id]) == 2)
        bt.stop_process(first)
        self.assertTrue(self.routed())
        bt.stop_process(second)
        eventually(lambda: not self.routed())
        self.assertEqual(bt.pulse('get-default-sink'), 'media')
        self.assertEqual(playback_sink(), 'media')
        self.assertIn(bt.INPUT, {item['name'] for item in bt.pulse_objects('sources')})
        self.assertEqual(self.route_events, ['enable', ('release', False)])
        third = self.recording()
        eventually(self.routed)
        self.stop_controller()
        self.assertEqual(bt.pulse('get-default-source'), bt.SILENCE)
        self.assertEqual(bt.pulse('get-default-sink'), 'media')
        self.assertEqual(self.route_events[-1], ('release', False))

    def test_route_failure_leaves_source_available_and_recovers(self):
        self.fail_next = True
        reader = self.recording()
        eventually(lambda: bt.control('status').get('route_error'))
        self.assertFalse(self.routed())
        self.assertNotIn(bt.CAPTURE, {item['name'] for item in bt.pulse_objects('sources')})
        self.assertEqual(bt.pulse('get-default-sink'), 'media')
        eventually(self.routed)
        self.assertNotIn('route_error', bt.control('status'))
        bt.stop_process(reader)
        eventually(lambda: not self.routed())

    def test_cork_releases_route_and_uncork_reacquires_without_reopening_device(self):
        recorder = subprocess.Popen([sys.executable, str(Path(__file__).with_name('cork-recorder.py')), bt.INPUT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True)
        self.addCleanup(bt.stop_process, recorder)
        self.addCleanup(recorder.stdin.close)
        self.addCleanup(recorder.stdout.close)
        self.assertTrue(json.loads(recorder.stdout.readline())['corked'])
        self.assertFalse(self.routed())
        recorder.stdin.write('u\n')
        recorder.stdin.flush()
        self.assertFalse(json.loads(recorder.stdout.readline())['corked'])
        eventually(self.routed)
        recorder.stdin.write('c\n')
        recorder.stdin.flush()
        self.assertTrue(json.loads(recorder.stdout.readline())['corked'])
        eventually(lambda: not self.routed())
        self.assertEqual(bt.pulse('get-default-sink'), 'media')
        recorder.stdin.write('u\n')
        recorder.stdin.flush()
        recorder.stdout.readline()
        eventually(self.routed)
        recorder.stdin.write('q\n')
        recorder.stdin.flush()
        recorder.wait(timeout=5)
        eventually(lambda: not self.routed())

    def test_route_loss_closes_capture_and_preserves_user_output_change(self):
        reader = self.recording()
        eventually(self.routed)
        bt.pulse('set-default-sink', 'other')
        self.loss = self.current_route
        self.loss.peer.sendall(b'lost\n')
        eventually(lambda: not self.routed())
        self.assertEqual(bt.pulse('get-default-sink'), 'other')
        self.assertEqual(self.route_events[-1], ('release', False))
        bt.stop_process(reader)

    def test_native_capture_failure_releases_route_and_removes_partial_output(self):
        self.fail_capture = True
        reader = self.recording()
        eventually(lambda: bt.control('status').get('route_error'))
        self.assertFalse(self.routed())
        self.assertNotIn(bt.OUTPUT, {item['name'] for item in bt.pulse_objects('sinks')})
        self.assertEqual(bt.pulse('get-default-sink'), 'media')
        self.assertEqual(self.route_events, ['enable', ('release', False)])
        bt.stop_process(reader)


if __name__ == '__main__':
    unittest.main()
