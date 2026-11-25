#!/usr/bin/env python3
"""Exercise public-plane bounds and the live-display guard without Android."""
import ctypes as C
import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe, x11 = load('ahb-import'), load('ahb-x11')


class Android:
    def __init__(self, count=1, pixel_stride=4, row_stride=20, null=False):
        self.data = (C.c_ubyte * 40)(*([0x5A] * 40))
        self.planes = probe.Planes(planeCount=count)
        self.planes.planes[0] = probe.Plane(None if null else C.addressof(self.data), pixel_stride, row_stride)
        self.unlocks = 0

    def AHardwareBuffer_lockPlanes(self, buffer, usage, fence, rect, output):
        C.memmove(output, C.byref(self.planes), C.sizeof(self.planes))
        return 0

    def AHardwareBuffer_unlock(self, buffer, fence):
        self.unlocks += 1
        return 0


class PublicPlanes(unittest.TestCase):
    def test_odd_sized_pattern_preserves_row_padding(self):
        android = Android()
        expected = (bytes((255, 0, 0, 255)) + bytes((0, 0, 255, 255)) * 2 +
                    bytes((255, 255, 0, 255)) + bytes((0, 255, 255, 255)) * 2)
        self.assertEqual(probe.pattern(3, 2), expected)
        probe.locked_pixels(android, None, 3, 2, write=expected)
        self.assertEqual(bytes(android.data)[12:20], b'Z' * 8)
        self.assertEqual(bytes(android.data)[32:40], b'Z' * 8)
        self.assertEqual(probe.locked_pixels(android, None, 3, 2), expected)
        self.assertEqual(android.unlocks, 2)

    def test_unsupported_planes_are_unlocked_without_access(self):
        for arguments in ({'count': 2}, {'count': 0}, {'pixel_stride': 8},
                          {'row_stride': 8}, {'null': True}):
            with self.subTest(arguments):
                android = Android(**arguments)
                with mock.patch.object(C, 'string_at', side_effect=AssertionError('Read invalid plane')):
                    with self.assertRaises(probe.ProbeError):
                        probe.locked_pixels(android, None, 3, 2)
                self.assertEqual(android.unlocks, 1)

    def test_live_display_rejected_before_loading_libraries(self):
        with mock.patch.dict(os.environ, {'DISPLAY': ':0', 'LIVECD_FULLSCREEN_TEST': 'test'}), \
                mock.patch.object(C, 'CDLL', side_effect=AssertionError('Loaded XCB')):
            with self.assertRaises(RuntimeError):
                x11.present(None, None, ':0', None, {}, None)

    def test_short_write_rejected_before_locking(self):
        android = Android()
        with self.assertRaises(probe.ProbeError):
            probe.locked_pixels(android, None, 3, 2, write=b'\0')
        self.assertEqual(android.unlocks, 0)

    def test_private_display_requires_ownership_marker(self):
        with mock.patch.dict(os.environ, {'DISPLAY': ':74'}, clear=True), \
                mock.patch.object(C, 'CDLL', side_effect=AssertionError('Loaded XCB')):
            with self.assertRaises(RuntimeError):
                x11.present(None, None, ':74', None, {}, None)


if __name__ == '__main__':
    unittest.main()
