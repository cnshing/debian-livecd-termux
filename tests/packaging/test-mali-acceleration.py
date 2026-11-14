#!/usr/bin/env python3
"""Check Mali media routing and independent rendering/decoding overrides."""
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import acceleration
import mali


class MaliMedia(unittest.TestCase):
    def setUp(self):
        for patch in (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(acceleration, 'settings', return_value={}),
            mock.patch.object(acceleration, 'stack', return_value=None),
            mock.patch.object(acceleration, 'gpu_enabled', return_value=False),
            mock.patch.object(acceleration, 'apply_renderer', side_effect=lambda env, mode: env),
            mock.patch.object(mali, 'available', return_value=True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def prepare(self, video='auto'):
        return acceleration.prepare('mpv', ['/native/mpv', 'video.mp4'], 'bionic', video)

    def test_qualified_mpv_uses_gles_and_mediacodec_in_a_software_desktop(self):
        argv, env = self.prepare()
        self.assertEqual(Path(argv[1]).name, 'mali.py')
        self.assertIn('--opengl-es=yes', argv)
        self.assertIn('--gpu-api=opengl', argv)
        self.assertIn('--hwdec=mediacodec-copy', argv)
        self.assertNotIn('--gpu-api=vulkan', argv)
        self.assertFalse(any('angle' in arg.lower() for arg in argv))

    def test_disabling_gpu_keeps_hardware_decoding(self):
        os.environ['LIVECD_MPV_GPU'] = '0'
        argv, _ = self.prepare()
        self.assertEqual(argv[0], '/native/mpv')
        self.assertIn('--vo=x11', argv)
        self.assertIn('--hwdec=mediacodec-copy', argv)

    def test_disabling_video_keeps_gles_rendering(self):
        argv, _ = self.prepare('off')
        self.assertIn('--gpu-api=opengl', argv)
        self.assertIn('--hwdec=no', argv)
        self.assertNotIn('--hwdec=mediacodec-copy', argv)

    def test_explicit_player_overrides_are_preserved_after_profile_defaults(self):
        argv, _ = acceleration.prepare('mpv',
            ['/native/mpv', '--hwdec=no', 'video.mp4'], 'bionic', 'on')
        self.assertLess(argv.index('--hwdec=mediacodec-copy'), argv.index('--hwdec=no'))

    def test_mali_vaapi_uses_cpu_surfaces_without_adreno_imports(self):
        selected = (Path('/private/va'), {
            'libraries': ['lib'], 'preloads': [], 'driver_directory': 'dri'})
        env = {}
        with mock.patch.object(acceleration.os, 'access', return_value=True), \
                mock.patch.object(acceleration, 'ensure_daemon'):
            acceleration.video_environment(env, selected, 'bionic', {})
        self.assertEqual(env['TERMUX_VA_GPU_BACKEND'], 'sw')
        self.assertNotIn('TERMUX_VA_X11_DRI3', env)
        self.assertNotIn('TERMUX_VA_CONTIGUOUS_DMABUF', env)

    def test_explicit_generic_vaapi_works_without_desktop_gpu(self):
        selected = (Path('/private/va'), {
            'libraries': [], 'preloads': [], 'driver_directory': 'dri'})
        with mock.patch.object(acceleration, 'stack', return_value=selected), \
                mock.patch.object(acceleration.os, 'access', return_value=True), \
                mock.patch.object(acceleration, 'ensure_daemon'):
            argv, env = acceleration.prepare('generic', ['/native/ffmpeg'], 'bionic', 'on')
        self.assertEqual(argv, ['/native/ffmpeg'])
        self.assertEqual(env['GALLIUM_DRIVER'], 'softpipe')
        self.assertEqual(env['LIBVA_DRIVER_NAME'], 'termuxva')

    def test_non_mali_path_keeps_existing_renderer_policy(self):
        with mock.patch.object(mali, 'available', return_value=False):
            argv, _ = self.prepare()
        self.assertEqual(argv[0], '/native/mpv')
        self.assertIn('--vo=x11', argv)
        self.assertIn('--hwdec=mediacodec-copy', argv)


class PanVKBrowsers(unittest.TestCase):
    """Browsers on Mali use ANGLE's Vulkan back end on the packaged PanVK driver."""

    def setUp(self):
        import shutil
        import tempfile
        import graphics
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.panvk = self.tmp / 'panvk-kbase'
        for abi in ('bionic', 'glibc'):
            (self.panvk / abi).mkdir(parents=True)
            driver = self.panvk / abi / 'libvulkan_panfrost.so'
            driver.touch()
            (self.panvk / abi / 'panfrost_icd.json').write_text(
                '{"ICD": {"library_path": "libvulkan_panfrost.so"}}')
        receipt = self.tmp / 'build-source.json'
        receipt.write_text('0010-clip-pixmap-damage')
        for patch in (
            mock.patch.dict(os.environ, {'DISPLAY': ':5'}, clear=True),
            mock.patch.object(acceleration, 'settings', return_value={}),
            mock.patch.object(acceleration, 'stack', return_value=None),
            mock.patch.object(acceleration, 'RECEIPT', receipt),
            mock.patch.object(acceleration, 'ROOT', self.tmp / 'acceleration'),
            mock.patch.object(acceleration, 'preferred_renderer', return_value='software'),
            mock.patch.object(acceleration, 'ensure_daemon'),
            mock.patch.object(graphics, 'PANVK', self.panvk),
            mock.patch.object(graphics.os, 'access', return_value=True),
            mock.patch.object(acceleration.os.path, 'exists', return_value=False),
            mock.patch.object(mali, 'available', return_value=True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_chromium_uses_angle_on_panvk_in_a_software_desktop(self):
        argv, env = acceleration.prepare('chromium', ['/chromium'], 'bionic', 'off')
        self.assertIn('--use-angle=vulkan', argv)
        self.assertNotIn('--disable-gpu', argv)
        self.assertEqual(env['VK_DRIVER_FILES'], str(self.panvk / 'bionic/panfrost_icd.json'))
        self.assertEqual(env['LD_LIBRARY_PATH'].split(':')[0], str(self.panvk / 'bionic/x11'))
        self.assertNotIn('TU_DEBUG', env)

    def test_chromium_from_the_desktop_never_sees_libandroid_stub(self):
        # The desktop session's library path, as a launched browser inherits it.
        os.environ['LD_LIBRARY_PATH'] = '/gnome-48/lib:' + str(acceleration.PREFIX / 'lib')
        _, env = acceleration.prepare('chromium', ['/chromium'], 'bionic', 'off')
        paths = env['LD_LIBRARY_PATH'].split(':')
        self.assertEqual(paths, [str(self.panvk / 'bionic/x11'), '/gnome-48/lib'])

    def test_chrome_uses_glibc_panvk_ahead_of_its_own_libraries(self):
        argv, env = acceleration.prepare('chrome', ['/chrome'], 'glibc', 'off')
        self.assertTrue(argv[0].endswith('/bionilux'))
        self.assertIn('--use-angle=vulkan', argv)
        self.assertEqual(env['VK_DRIVER_FILES'], str(self.panvk / 'glibc/panfrost_icd.json'))
        paths = env['BIONILUX_LIBRARY_PATH'].split(':')
        self.assertEqual(paths[0], str(self.panvk / 'glibc/lib'))
        self.assertIn(str(acceleration.PREFIX / 'opt/google/chrome/lib'), paths)
        self.assertNotIn('TURNIP_KMD', env)

    def test_browser_video_uses_the_mali_node_and_cpu_surfaces(self):
        selected = (self.tmp / 'va', {'libraries': ['lib'], 'preloads': [], 'driver_directory': 'dri',
                                      'vulkan_icd': 'freedreno_icd.json', 'mesa_library_directory': 'mesa'})
        with mock.patch.object(acceleration, 'stack', return_value=selected):
            argv, env = acceleration.prepare('chrome', ['/chrome'], 'glibc', 'on')
        self.assertIn('--hardware-video-device-path=/dev/mali0', argv)
        self.assertEqual(env['TERMUX_VA_GPU_BACKEND'], 'sw')
        self.assertEqual(env['VK_DRIVER_FILES'], str(self.panvk / 'glibc/panfrost_icd.json'))
        self.assertEqual(env['BIONILUX_LIBRARY_PATH'].split(':')[0], str(self.panvk / 'glibc/lib'))

    def test_glibc_mali_driver_precedes_the_prebuilt_mesa(self):
        root = self.tmp / 'va'
        manifest = {'libraries': ['mesa/lib', 'lib'], 'preloads': [], 'driver_directory': 'mesa/dri',
                    'mali': {'libraries': ['mali'], 'driver_directory': 'mali/dri'}}
        with mock.patch.object(acceleration, 'stack', return_value=(root, manifest)):
            argv, env = acceleration.prepare('chrome', ['/chrome'], 'glibc', 'on')
        self.assertEqual(env['LIBVA_DRIVERS_PATH'], str(root / 'mali/dri'))
        paths = env['BIONILUX_LIBRARY_PATH'].split(':')
        self.assertLess(paths.index(str(root / 'mali')), paths.index(str(root / 'mesa/lib')))
        self.assertEqual(env['TERMUX_VA_SYNC_END_PICTURE'], '1')
        # Without it Exynos holds HEVC pictures back and the wait above fails each one.
        self.assertEqual(env['TERMUX_VA_HEVC_REORDER_PICS'], '0')
        self.assertEqual(env['TERMUX_VA_H264_REORDER_FRAMES'], '0')
        self.assertFalse(any('AcceleratedVideoEncoder' in arg for arg in argv))
        self.assertNotIn('--video-capture-use-gpu-memory-buffer', argv)

    def test_adreno_keeps_the_prebuilt_glibc_driver(self):
        root = self.tmp / 'va'
        manifest = {'libraries': ['mesa/lib', 'lib'], 'preloads': [], 'driver_directory': 'mesa/dri',
                    'mali': {'libraries': ['mali'], 'driver_directory': 'mali/dri'}}
        env = {}
        with mock.patch.object(acceleration, 'mali_usable', return_value=False):
            acceleration.video_environment(env, (root, manifest), 'glibc', {})
        self.assertEqual(env['LIBVA_DRIVERS_PATH'], str(root / 'mesa/dri'))
        self.assertEqual(env['BIONILUX_LIBRARY_PATH'].split(':'), [str(root / 'mesa/lib'), str(root / 'lib')])
        self.assertEqual(env['TERMUX_VA_GPU_BACKEND'], 'kgsl')
        # Qualcomm's decoder stops returning frames at a count of 0; it keeps the bridge's default.
        self.assertNotIn('TERMUX_VA_HEVC_REORDER_PICS', env)
        self.assertNotIn('TERMUX_VA_H264_REORDER_FRAMES', env)

    def test_completion_can_be_disabled_for_a_control_run(self):
        selected = (self.tmp / 'va', {'libraries': [], 'preloads': [], 'driver_directory': 'dri'})
        with mock.patch.object(acceleration, 'stack', return_value=selected), \
                mock.patch.dict(os.environ, {'LIVECD_VA_DISABLE_COMPLETION': '1'}):
            _, env = acceleration.prepare('chrome', ['/chrome'], 'glibc', 'on')
        self.assertEqual(env['TERMUX_VA_SYNC_END_PICTURE'], '0')

    def test_disabled_video_does_not_select_a_va_driver(self):
        _, env = acceleration.prepare('chrome', ['/chrome'], 'glibc', 'off')
        self.assertNotIn('LIBVA_DRIVERS_PATH', env)
        self.assertNotIn('TERMUX_VA_SYNC_END_PICTURE', env)

    def test_stack_rejects_a_missing_or_external_mali_driver(self):
        import json
        root = self.tmp / 'va'
        (root / 'mesa/dri').mkdir(parents=True)
        (root / 'mesa/dri/termuxva_drv_video.so').touch()
        manifest = {'format': 1, 'abi': 'glibc', 'libraries': ['mesa'], 'preloads': [],
                    'driver_directory': 'mesa/dri',
                    'mali': {'libraries': ['mali'], 'driver_directory': 'mali/dri'}}
        (root / 'manifest.json').write_text(json.dumps(manifest))
        self.assertIsNone(acceleration.checked_stack(root, 'glibc'))
        (root / 'mali/dri').mkdir(parents=True)
        driver = root / 'mali/dri/termuxva_drv_video.so'
        driver.touch()
        self.assertIsNotNone(acceleration.checked_stack(root, 'glibc'))
        driver.unlink()
        external = self.tmp / 'unpackaged-driver.so'
        external.touch()
        driver.symlink_to(external)
        self.assertIsNone(acceleration.checked_stack(root, 'glibc'))

    def test_without_the_package_browsers_keep_the_desktop_policy(self):
        for abi in ('bionic', 'glibc'):
            (self.panvk / abi / 'panfrost_icd.json').unlink()
        argv, env = acceleration.prepare('chromium', ['/chromium'], 'bionic', 'off')
        self.assertIn('--disable-gpu', argv)
        self.assertNotIn('panvk-kbase', env.get('VK_DRIVER_FILES', ''))

    def test_explicit_gpu_override_still_wins(self):
        os.environ['LIVECD_CHROMIUM_GPU'] = '0'
        argv, _ = acceleration.prepare('chromium', ['/chromium'], 'bionic', 'off')
        self.assertIn('--disable-gpu', argv)


if __name__ == '__main__':
    unittest.main()
