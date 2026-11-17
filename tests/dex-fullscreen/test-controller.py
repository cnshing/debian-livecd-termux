#!/usr/bin/env python3
"""Device qualification, refusal, and process restart supervision without Android."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
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

    def test_nondebuggable_app_is_rejected_before_writing_payload_or_attaching(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'id').write_text('#!/bin/sh\necho 2000\n')
            (directory / 'run-as').write_text('#!/bin/sh\necho "not debuggable" >&2\nexit 1\n')
            for name in ['id', 'run-as']:
                (directory / name).chmod(0o755)
            marker = directory / 'unsafe-action'
            result = subprocess.run(['sh', '-c', controller.guard() + f'touch {marker}\n'],
                env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH']}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('must be debuggable', result.stderr)
            self.assertFalse(marker.exists())

    def test_status_parsing_handles_shizuku_notices(self):
        self.assertEqual(controller.record('Waiting for authorization\n{"pid":7,"phase":"running"}\n')['pid'], 7)
        with self.assertRaises(RuntimeError):
            controller.record('Permission denied')


class Supervision(unittest.TestCase):
    def test_restarts_attach_to_new_process_and_cleanup_only_current_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            probes = [(11, None), (11, {'pid': 11, 'phase': 'running'}), (None, None), (12, None)]
            def probe():
                if probes:
                    return probes.pop(0)
                raise KeyboardInterrupt()
            with mock.patch.object(controller, 'STATE', Path(directory)), \
                 mock.patch.object(controller, 'supported', return_value=True), \
                 mock.patch.object(controller, 'staging', return_value='stage'), \
                 mock.patch.object(controller, 'shell'), \
                 mock.patch.object(controller, 'probe', side_effect=probe), \
                 mock.patch.object(controller, 'attach', side_effect=lambda pid: {'pid': pid, 'phase': 'running'}) as attach, \
                 mock.patch.object(controller, 'detach') as detach, \
                 mock.patch.object(controller.time, 'sleep'):
                with self.assertRaises(KeyboardInterrupt):
                    controller.run()
                self.assertEqual(attach.call_args_list, [mock.call(11), mock.call(12)])
                detach.assert_called_once()

    def test_refused_helper_status_is_a_failure(self):
        with mock.patch.object(controller, 'payload_id', return_value='test'), \
             mock.patch.object(controller, 'shell', return_value='{"pid":11,"phase":"failed"}'):
            with self.assertRaisesRegex(RuntimeError, 'refused'):
                controller.attach(11)


if __name__ == '__main__':
    unittest.main()
