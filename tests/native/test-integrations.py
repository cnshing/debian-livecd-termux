#!/usr/bin/env python3
"""Host checks for the desktop's integration startup. Usage: python3 tests/native/test-integrations.py"""
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
from integrations import Integrations


class BluetoothStart(unittest.TestCase):
    def integration(self, failures):
        self.calls = []
        integration = Integrations.__new__(Integrations)
        integration.stopping = threading.Event()
        integration.stopping.wait = lambda timeout: False

        def command(*arguments, timeout=None):
            self.calls.append(arguments)
            if len(self.calls) <= failures:
                raise RuntimeError('OpenSL voice output failed (12)')
            return '{}'
        integration.command = command
        return integration

    def test_retries_while_android_releases_the_previous_route(self):
        self.integration(2).bluetooth_on()
        self.assertEqual(self.calls, [('livecd-mic-bluetooth', 'on', '--default')] * 3)

    def test_gives_up_after_three_attempts(self):
        with self.assertRaises(RuntimeError):
            self.integration(3).bluetooth_on()
        self.assertEqual(len(self.calls), 3)


if __name__ == '__main__':
    unittest.main()
