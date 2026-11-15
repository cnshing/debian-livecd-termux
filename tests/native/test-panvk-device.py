#!/usr/bin/env python3
"""Check that desktop defaults require the measured device and kbase ABI."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import panvk_device


class Device(unittest.TestCase):
    def probe(self, machine='aarch64', kernel='4.19.87-test', device='x1s', abi=(11, 35), denied=False):
        def version(fd, command, data, mutate):
            data[:] = struct.pack('HH', *abi)
        with mock.patch.object(panvk_device.os, 'uname', return_value=SimpleNamespace(machine=machine, release=kernel)), \
             mock.patch.object(panvk_device.subprocess, 'check_output', return_value=device), \
             mock.patch.object(panvk_device.os, 'open', side_effect=PermissionError if denied else None, return_value=17), \
             mock.patch.object(panvk_device.fcntl, 'ioctl', side_effect=version), \
             mock.patch.object(panvk_device.os, 'close') as close:
            result = panvk_device.qualified()
            self.assertEqual(close.call_count, int(machine == 'aarch64' and kernel.startswith('4.19.87') and device == 'x1s' and not denied))
            return result

    def test_measured_device_is_accepted(self):
        self.assertTrue(self.probe())

    def test_other_hardware_or_kernel_is_rejected(self):
        for options in ({'machine': 'x86_64'}, {'kernel': '5.10.0'}, {'device': 'd2s'}, {'abi': (11, 34)}, {'denied': True}):
            with self.subTest(options=options):
                self.assertFalse(self.probe(**options))


if __name__ == '__main__':
    unittest.main()
