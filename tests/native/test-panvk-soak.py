#!/usr/bin/env python3
"""Reject partial, interrupted and mismatched desktop soak evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('soak', Path(__file__).with_name('check-panvk-soak.py'))
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)


class SoakTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        processes = {name: {'pid': pid, 'libraries': ['/candidate/libvulkan_panfrost.so'],
                            'devices': [{'target': '/dev/mali0'}], 'fd_count': 10,
                            'status': 'State:\tS (sleeping)\nVmRSS:\t1000 kB\n'}
                     for pid, name in enumerate(('shell', 'cube', 'gears'), 100)}
        self.result = {'completed': True, 'shell': processes['shell'],
                       'soak': {'seconds_requested': 1800, 'seconds_completed': 1800.1,
                                'samples': [{'elapsed': t, 'processes': copy.deepcopy(processes),
                                             'capture': f'{t}.png'} for t in range(0, 1800, 30)],
                                'final': copy.deepcopy(processes)}}
        for sample in self.result['soak']['samples']:
            (self.root / sample['capture']).write_bytes(b'\x89PNG\r\n\x1a\n' + b'\0' * 20 + str(sample['elapsed']).encode())
        (self.root / 'isolation.json').write_text('{"ok": true}')
        (self.root / 'soak-gears.log').write_text('100 frames in 5.0 seconds = 20.0 FPS\n' * 360)

    def check(self):
        (self.root / 'result.json').write_text(json.dumps(self.result))
        return soak.check(self.root)

    def test_complete(self):
        self.assertEqual(self.check()['samples'], 60)

    def test_short_or_incomplete(self):
        for change in ({'completed': False}, {'unexpected_process_exit': {'name': 'cube'}}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.result)
                self.result.update(change)
                with self.assertRaises(AssertionError): self.check()
                self.result = original
        self.result['soak']['seconds_completed'] = 151.5
        with self.assertRaisesRegex(AssertionError, 'short'): self.check()

    def test_gap(self):
        del self.result['soak']['samples'][1:5]
        with self.assertRaisesRegex(AssertionError, 'gap'): self.check()

    def test_workload_restarted(self):
        self.result['soak']['final']['cube']['pid'] += 1
        with self.assertRaisesRegex(AssertionError, 'restarted'): self.check()

    def test_driver_changed(self):
        self.result['soak']['samples'][3]['processes']['gears']['libraries'] = ['/other/libvulkan_panfrost.so']
        with self.assertRaisesRegex(AssertionError, 'driver changed'): self.check()

    def test_isolation(self):
        (self.root / 'isolation.json').write_text('{"ok": false}')
        with self.assertRaisesRegex(AssertionError, 'isolation'): self.check()

    def test_rendering_stalled(self):
        (self.root / 'soak-gears.log').write_text('100 frames in 5.0 seconds = 20.0 FPS\n')
        with self.assertRaisesRegex(AssertionError, 'progress'): self.check()

    def test_missing_capture(self):
        (self.root / '900.png').unlink()
        with self.assertRaises(FileNotFoundError): self.check()


if __name__ == '__main__':
    unittest.main()
