#!/usr/bin/env python3
"""Host checks for packaged Firefox selection and safe fallback after mirror updates."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src/native'))
import acceleration

spec = importlib.util.spec_from_file_location('firefox_video_stage', REPO / 'packages/android-firefox-video/stage.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class FirefoxVideo(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.prefix = root / 'prefix'
        original = self.prefix / 'lib/firefox'
        original.mkdir(parents=True)
        for name in ('firefox', 'application.ini', 'libxul.so', 'gfxtest'):
            (original / name).write_text('installed ' + name)
        (self.prefix / 'bin').mkdir()
        (self.prefix / 'bin/firefox').symlink_to(original / 'firefox')
        for name in ('libgbm.so', 'libdrm.so'):
            (self.prefix / 'lib' / name).touch()
        self.runtime = self.prefix / 'lib/android-firefox-video'
        (self.runtime / 'application').mkdir(parents=True)
        (self.runtime / 'application/gfxtest').write_text('patched probe')
        (self.runtime / 'ffmpeg/lib').mkdir(parents=True)
        for name in ('libavcodec.so.63', 'libavutil.so.61'):
            (self.runtime / 'ffmpeg/lib' / name).touch()
        stage.install(self.prefix, self.runtime)
        self.dev = root / 'development'
        self.stack = root / 'vaapi'
        self.stack.mkdir()
        for patch in (
                mock.patch.multiple(acceleration, PREFIX=self.prefix, ROOT=self.dev),
                mock.patch.object(acceleration, 'settings', return_value={}),
                mock.patch.object(acceleration, 'gpu_enabled', return_value=True),
                mock.patch.object(acceleration, 'apply_renderer', side_effect=lambda env, renderer: env),
                mock.patch.object(acceleration, 'stack', return_value=(self.stack, {})),
                mock.patch.dict(os.environ, {}, clear=True)):
            patch.start()
            self.addCleanup(patch.stop)

    def prepare(self, override='auto'):
        errors = io.StringIO()
        with mock.patch.object(acceleration, 'video_environment') as video, \
                contextlib.redirect_stderr(errors):
            command, env = acceleration.prepare('firefox',
                [str(self.prefix / 'bin/firefox'), '--profile', '/disposable/profile'], 'bionic', override)
        return command, env, video, errors.getvalue()

    def test_package_stages_loader_and_shares_firefox_assets(self):
        # An interrupted package build can repeat its install stage.
        stage.install(self.prefix, self.runtime)
        self.assertFalse((self.runtime / 'application/firefox').is_symlink())
        self.assertTrue((self.runtime / 'application/libxul.so').is_symlink())
        self.assertEqual((self.runtime / 'application/gfxtest').read_text(), 'patched probe')
        self.assertTrue((self.runtime / 'lib/libgbm.so.1').is_file())
        self.assertTrue((self.runtime / 'lib/libdrm.so.2').is_file())
        self.assertIn('- android-firefox-video', (REPO / 'overlays/Browser/packages/termux.yaml').read_text())

    def test_a_fresh_install_selects_the_packaged_probe_and_decoders(self):
        command, env, video, errors = self.prepare()
        self.assertEqual(command[0], str(self.runtime / 'application/firefox'))
        self.assertEqual(env['LD_LIBRARY_PATH'].split(':'),
                         [str(self.runtime / 'ffmpeg/lib'), str(self.runtime / 'lib')])
        self.assertEqual(env['MOZ_DRM_DEVICE'], '/dev/kgsl-3d0')
        video.assert_called_once()
        self.assertEqual(errors, '')

    def test_mali_names_its_own_node_and_keeps_zink(self):
        def sw(env, *_):
            env['TERMUX_VA_GPU_BACKEND'] = 'sw'
        with mock.patch.object(acceleration, 'video_device', return_value='/dev/mali0'), \
                mock.patch.object(acceleration, 'video_environment', side_effect=sw), \
                mock.patch.dict(os.environ, {'GALLIUM_DRIVER': 'zink'}):
            _, env = acceleration.prepare('firefox',
                [str(self.prefix / 'bin/firefox'), '--profile', '/disposable/profile'], 'bionic', 'auto')
        self.assertEqual(env['MOZ_DRM_DEVICE'], '/dev/mali0')
        self.assertEqual(env['GALLIUM_DRIVER'], 'zink')
        self.assertNotIn('TERMUX_VA_DISABLE_HEVC', env)

    def test_probe_accepts_only_zink_on_the_named_android_gpu(self):
        source = Path(self.temporary.name) / 'gfx'
        source.mkdir()
        (source / 'glxtest.cpp').write_text('''    if (deviceExtensions &&
        strstr(deviceExtensions, "EGL_MESA_device_software")) {''')
        stage.patch(source)
        patched = (source / 'glxtest.cpp').read_text()
        for needle in ('"/dev/kgsl-3d0"', '"Turnip Adreno"', '"/dev/mali0"', '"PANVK"', '"zink"',
                       'set_render_device_path(node)'):
            self.assertIn(needle, patched)
        with self.assertRaises(RuntimeError):
            stage.patch(source)

    def test_receipt_hash_taken_before_stripping_still_selects_video(self):
        # CI hashes $PREFIX's unstripped Firefox; packaging then strips the installed binary and
        # the loader copy alike (v0.12.0 on the Galaxy S20: hardware video silently off).
        receipt = self.runtime / 'manifest.json'
        data = json.loads(receipt.read_text())
        data['inputs']['binary'] = '0' * 64
        receipt.write_text(json.dumps(data))
        command, _, video, errors = self.prepare()
        self.assertEqual(command[0], str(self.runtime / 'application/firefox'))
        video.assert_called_once()
        self.assertEqual(errors, '')

    def test_firefox_binary_or_application_ini_changes_fall_back_without_starting_video(self):
        for name in ('firefox', 'application.ini'):
            with self.subTest(name=name):
                original = self.prefix / 'lib/firefox' / name
                saved = original.read_bytes()
                original.write_bytes(saved + b' newer mirror build')
                command, env, video, errors = self.prepare()
                self.assertEqual(command[0], str(self.prefix / 'bin/firefox'))
                self.assertNotIn('LD_LIBRARY_PATH', env)
                self.assertNotIn('MOZ_DRM_DEVICE', env)
                video.assert_not_called()
                self.assertIn('Firefox changed', errors)
                self.assertIn('using software decoding', errors)
                original.write_bytes(saved)

    def test_corrupt_metadata_or_missing_decoders_fall_back(self):
        receipt = self.runtime / 'manifest.json'
        original = receipt.read_text()
        for invalid in ('{invalid json', '[]', '{"format":1,"abi":"bionic","inputs":null}'):
            with self.subTest(invalid=invalid):
                receipt.write_text(invalid)
                command, _, video, errors = self.prepare()
                self.assertEqual(command[0], str(self.prefix / 'bin/firefox'))
                video.assert_not_called()
                self.assertIn('metadata', errors)
        receipt.write_text(original)
        decoder = self.runtime / 'ffmpeg/lib/libavcodec.so.63'
        decoder.unlink()
        _, _, video, errors = self.prepare()
        video.assert_not_called()
        self.assertIn('incomplete', errors)
        receipt.unlink()
        _, _, video, errors = self.prepare()
        video.assert_not_called()
        self.assertIn('install android-firefox-video', errors)

    def test_stale_development_override_does_not_hide_a_compatible_package(self):
        self.dev.mkdir()
        (self.dev / 'firefox').symlink_to(self.runtime, target_is_directory=True)
        (self.dev / 'firefox-ffmpeg').mkdir()
        (self.dev / 'firefox-ffmpeg/manifest.json').write_text('{}')
        command, _, video, errors = self.prepare()
        self.assertEqual(command[0], str(self.runtime / 'application/firefox'))
        video.assert_called_once()
        self.assertEqual(errors, '')

    def test_explicit_software_override_does_not_load_the_private_runtime(self):
        command, env, video, errors = self.prepare('off')
        self.assertEqual(command[0], str(self.prefix / 'bin/firefox'))
        self.assertNotIn('LD_LIBRARY_PATH', env)
        video.assert_not_called()
        self.assertEqual(errors, '')

    def test_only_native_chromium_requests_implicit_sync_completion(self):
        for profile, override, disabled, expected in (
                ('chromium', 'on', False, '1'), ('chromium', 'on', True, '0'),
                ('chromium', 'off', False, None), ('generic', 'on', False, None),
                ('firefox', 'on', False, None)):
            with self.subTest(profile=profile, override=override, disabled=disabled), \
                    mock.patch.object(acceleration, 'chromium_has_vaapi', return_value=True), \
                    mock.patch.object(acceleration, 'video_environment'), \
                    mock.patch.dict(os.environ, {'LIVECD_VA_DISABLE_COMPLETION': '1' if disabled else '0'}):
                _, env = acceleration.prepare(profile,
                    [str(self.prefix / 'bin/firefox'), '--profile', '/disposable/profile'], 'bionic', override)
                self.assertEqual(env.get('TERMUX_VA_SYNC_END_PICTURE'), expected)


    def test_encode_preference_follows_the_launcher_decision(self):
        for expected in (False, True):
            with self.subTest(expected=expected), \
                    mock.patch.object(Path, 'home', return_value=Path(self.temporary.name)):
                acceleration.command_line('firefox', [str(self.prefix / 'bin/firefox')], 'bionic', True, True,
                                          firefox_encode=expected)
                text = (Path(self.temporary.name) / '.config/livecd-native/firefox/user.js').read_text()
                self.assertEqual('user_pref("media.use-remote-encoder.video.platform", true);' in text, expected)

    def test_encoding_default_on_adreno_opt_in_on_mali(self):
        manifest = self.runtime / 'manifest.json'
        data = json.loads(manifest.read_text())
        socket = Path(self.temporary.name) / 'va.sock'
        status = Path(self.temporary.name) / 'status'
        listed = 'video/avc OMX.qcom.video.encoder.avc\nvideo/hevc OMX.qcom.video.encoder.hevc\n'
        # (settings, mali, runtime revision, daemon encoder list, runtime has encoders, expected)
        cases = (({}, False, 7, listed, True, True),                       # Adreno default
                 ({'firefox_encode': False}, False, 7, listed, True, False),  # user turned it off
                 ({}, False, 6, listed, True, False),                      # runtime before the WebRTC fix
                 ({'firefox_encode': True}, False, 6, listed, True, True),  # explicit opt-in still works
                 ({}, False, 7, 'video/hevc OMX.qcom.video.encoder.hevc\n', True, False),  # no H.264 encoder
                 ({}, False, 7, None, True, False),                        # no daemon list
                 ({}, False, 7, listed, False, False),                     # runtime without encoders
                 ({}, True, 7, listed, True, False),                       # Mali: still opt-in
                 ({'firefox_encode': True}, True, 7, listed, True, True))
        for config, mali, revision, encoders, runtime_encodes, expected in cases:
            with self.subTest(config=config, mali=mali, revision=revision, encoders=encoders,
                              runtime_encodes=runtime_encodes):
                data.pop('encoding', None)
                if runtime_encodes:
                    data['encoding'] = {'input': 'i420', 'codecs': ['h264', 'hevc', 'vp9']}
                manifest.write_text(json.dumps(data))
                listing = Path(str(socket) + '.encoders')
                listing.unlink(missing_ok=True)
                if encoders is not None:
                    listing.write_text(encoders)
                status.write_text('Package: android-firefox-video\nStatus: install ok installed\n'
                                  f'Version: 9.0.2-{revision}\n')
                with mock.patch.object(acceleration, 'settings', return_value=config), \
                        mock.patch.object(acceleration, 'mali_usable', return_value=mali), \
                        mock.patch.object(acceleration, 'DPKG_STATUS', status), \
                        mock.patch.object(acceleration.os.path, 'exists',
                                          side_effect=lambda path: str(path) == '/dev/kgsl-3d0' or
                                          os.path.lexists(path)):
                    self.assertEqual(acceleration.firefox_encode_ready(socket), expected)

if __name__ == '__main__':
    unittest.main()
