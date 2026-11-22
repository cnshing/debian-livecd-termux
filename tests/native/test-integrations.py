#!/usr/bin/env python3
"""Host checks for the desktop's integration startup. Usage: python3 tests/native/test-integrations.py"""
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
from integrations import Integrations


class MicrophoneStartup(unittest.TestCase):
    def integration(self, options=None, microphone='off'):
        integration = Integrations.__new__(Integrations)
        integration.options = options or {}
        integration.stopping = threading.Event()
        integration.lock = threading.Lock()
        integration.result = {'features': {}}
        integration.cleanup = []
        integration.command = mock.Mock(return_value='{"microphone": "' + microphone + '"}')
        integration.bluetooth_on = mock.Mock()
        integration.bluetooth_state = mock.Mock(return_value={'active': False})
        return integration

    @mock.patch('integrations.os.access', return_value=True)
    def test_disabled_bluetooth_uses_phone_microphone(self, access):
        integration = self.integration({'bluetooth': False})
        integration.microphone()
        integration.bluetooth_on.assert_not_called()
        integration.bluetooth_state.assert_not_called()
        self.assertEqual(integration.command.call_args_list, [
            mock.call('android-pulseaudio-mic', 'status', timeout=5),
            mock.call('android-pulseaudio-mic', 'on', timeout=15)])
        self.assertEqual(integration.status()['features']['bluetooth']['status'], 'disabled')

    @mock.patch('integrations.os.access', return_value=True)
    def test_default_startup_publishes_on_demand_microphone(self, access):
        integration = self.integration()
        integration.microphone()
        integration.bluetooth_on.assert_called_once_with()
        self.assertEqual(integration.status()['features']['microphone']['status'], 'bluetooth')
        self.assertEqual(len(integration.command.call_args_list), 1)

    @mock.patch('integrations.os.access', return_value=True)
    def test_opt_in_failure_falls_back_to_phone_microphone(self, access):
        integration = self.integration({'bluetooth': True})
        integration.bluetooth_on.side_effect = RuntimeError('No connected headset')
        integration.microphone()
        integration.command.assert_called_with('android-pulseaudio-mic', 'on', timeout=15)
        self.assertEqual(integration.status()['features']['bluetooth']['status'], 'unavailable')

    @mock.patch('integrations.os.access', return_value=True)
    def test_disabled_microphone_starts_neither_route(self, access):
        integration = self.integration({'microphone': False, 'bluetooth': True})
        integration.microphone()
        integration.command.assert_not_called()
        integration.bluetooth_on.assert_not_called()

    @mock.patch('integrations.os.access', return_value=True)
    def test_existing_microphone_is_preserved(self, access):
        integration = self.integration({'bluetooth': True}, microphone='suspended')
        integration.microphone()
        integration.bluetooth_on.assert_not_called()
        self.assertEqual(len(integration.command.call_args_list), 1)
        self.assertEqual(integration.cleanup, [])


class BluetoothStart(unittest.TestCase):
    def integration(self, failures):
        self.calls = []
        integration = Integrations.__new__(Integrations)
        integration.stopping = threading.Event()
        integration.stopping.wait = lambda timeout: False

        def command(*arguments, timeout=None):
            self.calls.append(arguments)
            if len(self.calls) <= failures:
                raise RuntimeError('No matching Bluetooth call device')
            return '{}'
        integration.command = command
        return integration

    def test_retries_while_android_discovers_the_headset(self):
        self.integration(2).bluetooth_on()
        self.assertEqual(self.calls, [('android-pulseaudio-bluetooth', 'auto', '--default')] * 3)

    def test_gives_up_after_three_attempts(self):
        with self.assertRaises(RuntimeError):
            self.integration(3).bluetooth_on()
        self.assertEqual(len(self.calls), 3)


if __name__ == '__main__':
    unittest.main()
