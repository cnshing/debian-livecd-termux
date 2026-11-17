#!/usr/bin/env python3
"""Device qualification, Binder lifecycle, and reversible window policy checks."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import shlex
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'packages/android-legacy-dex-fullscreen'
spec = importlib.util.spec_from_file_location('dex_fullscreen', PACKAGE / 'controller.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class Qualification(unittest.TestCase):
    def test_only_samsung_android11_arm64_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            getprop = Path(directory) / 'getprop'
            getprop.write_text('''#!/bin/sh
case $1 in
ro.product.manufacturer) echo "$MANUFACTURER";;
ro.build.version.sdk) echo "$SDK";;
ro.product.cpu.abi) echo "$ABI";;
esac
''')
            getprop.chmod(0o755)
            for vendor, sdk, abi, accepted in [
                ('samsung', '30', 'arm64-v8a', True), ('SAMSUNG', '30', 'arm64-v8a', True),
                ('samsung', '33', 'arm64-v8a', False), ('samsung', '29', 'arm64-v8a', False),
                ('google', '30', 'arm64-v8a', False), ('samsung', '30', 'armeabi-v7a', False),
                ('', '', '', False),
            ]:
                with self.subTest(vendor=vendor, sdk=sdk, abi=abi):
                    result = subprocess.run(['sh', str(PACKAGE / 'device.sh')], env={**os.environ,
                        'ANDROID_LEGACY_DEX_GETPROP': str(getprop), 'MANUFACTURER': vendor, 'SDK': sdk, 'ABI': abi})
                    self.assertEqual(result.returncode == 0, accepted)

    def test_shell_permission_is_required_but_debuggable_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            marker = directory / 'app-private-access'
            (directory / 'id').write_text('#!/bin/sh\necho "$TEST_UID"\n')
            (directory / 'run-as').write_text(f'#!/bin/sh\ntouch {marker}\nexit 1\n')
            for name in ['id', 'run-as']:
                (directory / name).chmod(0o755)
            for uid, accepted in [('2000', True), ('10309', False), ('0', False)]:
                result = subprocess.run(['sh', '-c', controller.guard()], env={**os.environ,
                    'PATH': str(directory) + ':' + os.environ['PATH'], 'TEST_UID': uid}, capture_output=True)
                self.assertEqual(result.returncode == 0, accepted)
            self.assertFalse(marker.exists())

    def test_remote_paths_cannot_escape_the_owned_session(self):
        self.assertEqual(controller.remote_path(controller.REMOTE_PREFIX + 'Abc123'),
                         controller.REMOTE_PREFIX + 'Abc123')
        for bad in [None, '', '/data/local/tmp', controller.REMOTE_PREFIX + '../other',
                    controller.REMOTE_PREFIX + 'x;id', controller.REMOTE_PREFIX + 'x/file']:
            with self.subTest(path=bad), self.assertRaises(ValueError):
                controller.remote_path(bad)

    def test_status_parsing_handles_shizuku_notices(self):
        self.assertEqual(controller.record('Waiting for authorization\n{"pid":7,"phase":"running"}\n')['pid'], 7)
        with self.assertRaises(RuntimeError):
            controller.record('Permission denied')


class Supervision(unittest.TestCase):
    def test_window_recreation_stays_in_the_same_shell_helper_and_cleanup_runs(self):
        directory = controller.REMOTE_PREFIX + 'test123'
        with tempfile.TemporaryDirectory() as state:
            probes = [{'pid': 11, 'phase': 'starting'},
                      {'pid': 11, 'phase': 'running', 'active': False},
                      {'pid': 11, 'phase': 'running', 'active': True}]
            def probe(_):
                if probes:
                    return probes.pop(0)
                raise KeyboardInterrupt()
            with mock.patch.object(controller, 'STATE', Path(state)), \
                 mock.patch.object(controller, 'supported', return_value=True), \
                 mock.patch.object(controller, 'stage', return_value=directory), \
                 mock.patch.object(controller, 'launch') as launch, \
                 mock.patch.object(controller, 'probe', side_effect=probe), \
                 mock.patch.object(controller, 'detach') as detach, \
                 mock.patch.object(controller.time, 'sleep'):
                with self.assertRaises(KeyboardInterrupt):
                    controller.run()
                launch.assert_called_once_with(directory)
                detach.assert_called_once_with(directory)

    def test_failed_shell_helper_is_not_reported_ready(self):
        with tempfile.TemporaryDirectory() as state:
            with mock.patch.object(controller, 'STATE', Path(state)), \
                 mock.patch.object(controller, 'supported', return_value=True), \
                 mock.patch.object(controller, 'stage', return_value=controller.REMOTE_PREFIX + 'test123'), \
                 mock.patch.object(controller, 'launch'), \
                 mock.patch.object(controller, 'probe', return_value={'pid': 11, 'phase': 'failed'}), \
                 mock.patch.object(controller, 'shell', return_value='framework failure'), \
                 mock.patch.object(controller, 'detach'):
                with self.assertRaisesRegex(RuntimeError, 'Binder helper stopped'):
                    controller.run()
                self.assertEqual(json.loads((Path(state) / 'session.json').read_text())['phase'], 'failed')

    def test_stale_running_status_is_rejected_when_shell_process_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'status.json').write_text('{"pid":99999999,"start":"1","phase":"running"}')
            (path / 'id').write_text('#!/bin/sh\necho 2000\n')
            (path / 'id').chmod(0o755)
            def shell(script):
                result = subprocess.run(['sh', '-c', script], capture_output=True, text=True,
                    env={**os.environ, 'PATH': directory + ':' + os.environ['PATH']}, check=True)
                return result.stdout
            with mock.patch.object(controller, 'remote_path', return_value=shlex.quote(directory)), \
                 mock.patch.object(controller, 'shell', side_effect=shell):
                self.assertEqual(controller.probe('test')['phase'], 'failed')

    def test_stop_does_not_claim_success_when_restoration_failed(self):
        with tempfile.TemporaryDirectory() as state:
            path = Path(state) / 'session.json'
            path.write_text(json.dumps({'phase': 'failed', 'error': 'Window restoration unconfirmed'}))
            with mock.patch.object(controller, 'STATE', Path(state)), \
                 mock.patch.object(controller, 'owner', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'restoration unconfirmed'):
                    controller.stop()


class WindowPolicy(unittest.TestCase):
    def test_reversibility_replacement_and_firmware_eligibility(self):
        compiler = shutil.which('javac')
        self.assertIsNotNone(compiler, 'Install a JDK to run the window policy checks')
        with tempfile.TemporaryDirectory() as classes:
            sources = PACKAGE / 'java/org/livecd/dexfullscreen'
            subprocess.run([compiler, '-source', '8', '-target', '8', '-d', classes,
                str(sources / 'WindowPolicy.java'), str(sources / 'WindowState.java'),
                str(Path(__file__).with_name('WindowPolicyTest.java'))], check=True)
            subprocess.run(['java', '-cp', classes, 'org.livecd.dexfullscreen.WindowPolicyTest'], check=True)


if __name__ == '__main__':
    unittest.main()
