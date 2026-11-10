#!/usr/bin/env python3
"""Host checks for the signal probe's converter loading and audio route cleanup."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

path = Path(__file__).with_name('verify-signal.py')
spec = importlib.util.spec_from_file_location('verify_signal', path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Converter(unittest.TestCase):
    def test_extensionless_installed_converter_without_pythonpath(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / 'bin/easyeffects-autoeq'
            installed.parent.mkdir()
            installed.write_text('def convert(text):\n    return {"installed": text}\n')
            with mock.patch.dict(os.environ, {'PREFIX': directory}):
                self.assertEqual(probe.load_converter()('test'), {'installed': 'test'})

    def test_checkout_fallback(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'PREFIX': directory}):
            result = probe.load_converter()('Preamp: 0 dB\nFilter 1: ON PK Fc 1000 Hz Gain -12 dB Q 1\n')
            self.assertEqual(result['output']['equalizer#0']['left']['band0']['gain'], -12)


class MeasurementRoute(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.default = 'bluetooth'
        self.backend = {'PULSE_SERVER': 'unix:/backend/pulse'}

    def call(self, command, backend):
        self.assertIs(backend, self.backend)
        self.calls.append(command)
        if command[1] == 'get-default-sink':
            return self.default
        if command[1] == 'load-module':
            self.assertEqual(command[2], 'module-null-sink')
            return '42'
        if command[1] == 'set-default-sink':
            self.default = command[2]
        if command[1:4] == ['--format=json', 'list', 'sinks']:
            return json.dumps([{'name': self.default, 'index': 7}])
        if command[1:4] == ['--format=json', 'list', 'sink-inputs']:
            return json.dumps([{'sink': 7, 'properties': {'application.id': 'org.pipewire.PipeWire'}}])
        return ''

    def assert_restored(self):
        self.assertEqual(self.default, 'bluetooth')
        self.assertEqual(self.calls[-2:], [['pactl', 'set-default-sink', 'bluetooth'],
                                          ['pactl', 'unload-module', '42']])

    def test_measurement_uses_a_clocked_null_sink_and_restores_the_default(self):
        with probe.measurement_sink(self.call, self.backend) as monitor:
            self.assertTrue(self.default.startswith('native_eq_measurement_'))
            self.assertEqual(monitor, self.default + '.monitor')
        self.assert_restored()

    def test_measurement_failure_also_restores_the_default(self):
        with self.assertRaisesRegex(RuntimeError, 'measurement failed'):
            with probe.measurement_sink(self.call, self.backend):
                raise RuntimeError('measurement failed')
        self.assert_restored()

    def test_tunnel_timeout_cleans_up_before_sampling(self):
        with mock.patch.object(probe.time, 'monotonic', side_effect=[0, 16]):
            with self.assertRaisesRegex(RuntimeError, 'did not reach'):
                with probe.measurement_sink(self.call, self.backend):
                    self.fail('A tunnel that has not reached the sink cannot be measured')
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
