#!/usr/bin/env python3
"""Programs started from the desktop session get the launcher's VA-API decode limits."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import desktop
import graphics


class SessionDecode(unittest.TestCase):
    def session(self, mali, settings=None):
        with tempfile.TemporaryDirectory() as root:
            stack = Path(root)
            (stack / 'lib.so').write_text('')
            (stack / 'manifest.json').write_text(json.dumps(
                {'session_preload': 'lib.so', 'driver_directory': 'dri'}))
            env, preload = {}, []
            with mock.patch.object(desktop, 'ACCELERATION', stack / 'none'), \
                    mock.patch.object(desktop, 'PREFIX', stack / 'p'), \
                    mock.patch.object(desktop.Path, 'resolve', lambda p: p), \
                    mock.patch.object(desktop, 'acceleration_settings', return_value=settings or {}), \
                    mock.patch.object(desktop, 'preload_works', return_value=True), \
                    mock.patch.object(graphics, 'mali_usable', return_value=mali):
                (stack / 'p/lib').mkdir(parents=True)
                (stack / 'p/lib/android-vaapi').symlink_to(stack)
                desktop.native_encode(env, preload)
            return env, preload

    def test_adreno_session_hides_h264_and_av1(self):
        env, preload = self.session(False)
        self.assertTrue(preload)
        self.assertEqual(env['TERMUX_VA_DISABLE_H264'], '1')
        self.assertEqual(env['TERMUX_VA_DISABLE_AV1'], '1')
        self.assertNotIn('TERMUX_VA_HEVC_REORDER_PICS', env)

    def test_mali_session_returns_hevc_pictures_at_once(self):
        env, _ = self.session(True)
        self.assertEqual(env['TERMUX_VA_HEVC_REORDER_PICS'], '0')
        self.assertEqual(env['TERMUX_VA_DISABLE_H264'], '1')

    def test_configured_codec_list_is_shared_with_the_launcher(self):
        env, _ = self.session(False, {'disabled_va_codecs': []})
        self.assertFalse([k for k in env if k.startswith('TERMUX_VA_DISABLE_')])


if __name__ == '__main__':
    unittest.main()
