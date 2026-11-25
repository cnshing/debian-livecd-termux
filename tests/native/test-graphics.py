#!/usr/bin/env python3
"""Check GPU selection, ICD boundaries, recovery, and actual process evidence."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import graphics


class Graphics(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prefix = self.root / 'prefix'
        self.gpu = self.root / 'gpu'
        self.panvk = self.prefix / 'lib/panvk-kbase'
        self.turnip = self.gpu / 'share/vulkan/icd.d/freedreno_icd.aarch64.json'
        self.devices = {'/dev/mali0'}
        patches = (mock.patch.multiple(graphics, PREFIX=self.prefix, GPU=self.gpu,
                                      PANVK=self.panvk, ICD=self.turnip),
                   mock.patch.object(graphics.os, 'access', side_effect=lambda path, mode: str(path) in self.devices))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def manifest(self, path, driver):
        path.parent.mkdir(parents=True, exist_ok=True)
        driver.parent.mkdir(parents=True, exist_ok=True)
        driver.touch()
        path.write_text(json.dumps({'ICD': {'library_path': str(driver)}}))

    def install_panvk(self):
        path = self.panvk / 'bionic/panfrost_icd.json'
        self.manifest(path, path.parent / 'libvulkan_panfrost.so')
        return path

    def test_mali_selects_packaged_panvk_and_removes_android_library_shadowing(self):
        icd = self.install_panvk()
        env = {'LD_LIBRARY_PATH': f'{self.prefix}/lib:/private/gnome/lib',
               'GALLIUM_DRIVER': 'llvmpipe', 'VK_ICD_FILENAMES': '/wrong.json',
               'PANVK_KBASE_DRI3': 'raw'}
        graphics.apply_renderer(env, 'zink')
        self.assertEqual(env['VK_DRIVER_FILES'], str(icd))
        self.assertEqual(env['VK_ICD_FILENAMES'], str(icd))
        self.assertEqual(env['LD_LIBRARY_PATH'], f'{icd.parent}/x11:/private/gnome/lib')
        self.assertEqual(env['GALLIUM_DRIVER'], 'zink')
        self.assertEqual(env['LIVECD_NATIVE_VULKAN_DRIVER'], 'panvk')
        self.assertEqual(env['COGL_DRIVER'], 'gles2')
        self.assertNotIn('PANVK_KBASE_DRI3', env)
        self.assertTrue(graphics.legacy_drawing('zink'))

    def test_missing_panvk_does_not_select_cpu_or_turnip_silently(self):
        with self.assertRaisesRegex(RuntimeError, 'mesa-vulkan-icd-panvk-kbase'):
            graphics.apply_renderer({}, 'zink')

    def test_qualified_stack_defaults_nested_and_preserves_explicit_mode(self):
        self.install_panvk()
        with mock.patch.object(graphics, 'qualified_desktop_stack', return_value=True):
            env = graphics.apply_renderer({}, 'zink')
            self.assertEqual((env['PANVK_G77_LWG'], env['PANVK_G77_NESTED']), ('1', '1'))
            env = graphics.apply_renderer({'PANVK_G77_LWG': '0'}, 'zink')
            self.assertEqual((env['PANVK_G77_LWG'], env['PANVK_G77_NESTED']), ('0', '0'))

    def test_glibc_browser_uses_same_package_and_qualified_mode(self):
        icd = self.panvk / 'glibc/panfrost_icd.json'
        self.manifest(icd, icd.parent / 'libvulkan_panfrost.so')
        with mock.patch.object(graphics, 'qualified_desktop_stack', return_value=True):
            env = {'BIONILUX_LIBRARY_PATH': '/chrome/lib'}
            graphics.use_panvk(env, 'glibc')
        self.assertEqual(env['VK_DRIVER_FILES'], str(icd))
        self.assertEqual(env['BIONILUX_LIBRARY_PATH'], str(icd.parent / 'lib') + ':/chrome/lib')
        self.assertEqual((env['PANVK_G77_LWG'], env['PANVK_G77_NESTED']), ('1', '1'))

    def test_old_or_unqualified_driver_does_not_enable_workgroups(self):
        self.install_panvk()
        with mock.patch.object(graphics, 'qualified_mali', return_value=True):
            self.assertFalse(graphics.qualified_desktop_stack())
            env = graphics.apply_renderer({}, 'zink')
            self.assertNotIn('PANVK_G77_LWG', env)
        manifest = self.prefix / 'share/doc/mesa-vulkan-icd-panvk-kbase/SOURCE.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'variant': 'combined-ahb',
            'mesa_tree': 'b28956ffc095bda26bf8241badba014be178536b'}))
        with mock.patch.object(graphics, 'qualified_mali', return_value=False):
            self.assertFalse(graphics.qualified_desktop_stack())
        with mock.patch.object(graphics, 'qualified_mali', return_value=True):
            self.assertTrue(graphics.qualified_desktop_stack())

    def write_source(self, tree):
        manifest = self.prefix / 'share/doc/mesa-vulkan-icd-panvk-kbase/SOURCE.json'
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({'variant': 'combined-ahb', 'mesa_tree': tree}))

    def session(self, config=None):
        home = self.root / 'home'
        if config is not None:
            (home / '.local/lib/livecd').mkdir(parents=True, exist_ok=True)
            (home / '.local/lib/livecd/config.json').write_text(json.dumps(config))
        with mock.patch.object(graphics.Path, 'home', return_value=home), \
                mock.patch.object(graphics, 'qualified_mali', return_value=True):
            return graphics.session_presentation(graphics.apply_renderer({'PANVK_KBASE_DRI3': 'raw'}, 'zink'))

    def test_ahb_tree_opts_only_the_desktop_session_into_ahb(self):
        self.install_panvk()
        ahb = next(t for t, enabled in graphics.QUALIFIED_TREES.items() if enabled)
        self.write_source(ahb)
        env = self.session()
        self.assertEqual(env['PANVK_KBASE_DRI3'], 'ahb')
        self.assertEqual((env['PANVK_G77_LWG'], env['PANVK_G77_NESTED']), ('1', '1'))
        # A browser launcher reapplies the ICD: it keeps MIT-SHM, whatever it inherits.
        with mock.patch.object(graphics, 'qualified_mali', return_value=True):
            graphics.use_panvk(env, 'bionic')
        self.assertNotIn('PANVK_KBASE_DRI3', env)
        self.assertNotIn('PANVK_KBASE_DRI3', self.session({'panvk_presentation': 'shm'}))

    def test_shm_tree_unqualified_tree_and_turnip_keep_shm(self):
        self.install_panvk()
        self.write_source('b28956ffc095bda26bf8241badba014be178536b')
        env = self.session()
        self.assertNotIn('PANVK_KBASE_DRI3', env)
        self.assertEqual(env['PANVK_G77_LWG'], '1')
        self.write_source('0' * 40)
        self.assertNotIn('PANVK_KBASE_DRI3', self.session())
        self.assertNotIn('PANVK_G77_LWG', self.session())
        env = graphics.session_presentation({'LIVECD_NATIVE_VULKAN_DRIVER': 'turnip'})
        self.assertNotIn('PANVK_KBASE_DRI3', env)

    def test_glibc_never_receives_ahb(self):
        icd = self.panvk / 'glibc/panfrost_icd.json'
        self.manifest(icd, icd.parent / 'libvulkan_panfrost.so')
        env = {'PANVK_KBASE_DRI3': 'ahb'}
        graphics.use_panvk(env, 'glibc')
        self.assertNotIn('PANVK_KBASE_DRI3', env)

    def test_missing_or_outside_package_library_is_rejected(self):
        icd = self.install_panvk()
        for library in (icd.parent / 'missing.so', self.root / 'outside.so'):
            if library.name == 'outside.so':
                library.touch()
            icd.write_text(json.dumps({'ICD': {'library_path': str(library)}}))
            with self.subTest(library=library), self.assertRaisesRegex(RuntimeError, 'Invalid native Vulkan'):
                graphics.apply_renderer({}, 'zink')

    def test_turnip_selection_and_normal_drawing_are_preserved(self):
        self.devices = {'/dev/kgsl-3d0'}
        self.manifest(self.turnip, self.gpu / 'lib/libvulkan_freedreno.so')
        env = graphics.apply_renderer({}, 'zink')
        self.assertEqual(env['VK_DRIVER_FILES'], str(self.turnip))
        self.assertEqual(env['LIVECD_NATIVE_VULKAN_DRIVER'], 'turnip')
        self.assertFalse(graphics.legacy_drawing('zink'))
        self.assertTrue(graphics.legacy_drawing('software'))

    def test_software_recovery_clears_gpu_selection(self):
        env = {'VK_DRIVER_FILES': '/panvk.json', 'VK_ICD_FILENAMES': '/panvk.json',
               'LIVECD_NATIVE_VULKAN_DRIVER': 'panvk', 'PANVK_KBASE_DRI3': 'raw'}
        graphics.apply_renderer(env, 'software')
        self.assertEqual(env['GALLIUM_DRIVER'], 'llvmpipe')
        self.assertNotIn('VK_ICD_FILENAMES', env)
        self.assertNotIn('VK_DRIVER_FILES', env)
        self.assertNotIn('LIVECD_NATIVE_VULKAN_DRIVER', env)
        self.assertNotIn('PANVK_KBASE_DRI3', env)

    def test_process_evidence_requires_matching_driver_and_device(self):
        proc = self.root / 'proc/42'
        (proc / 'fd').mkdir(parents=True)
        (proc / 'maps').write_text('mapping /prefix/lib/libvulkan_panfrost.so\n')
        def path(value):
            return self.root / 'proc' if str(value) == '/proc' else Path(value)
        with mock.patch.object(graphics, 'Path', side_effect=path):
            self.assertIsNone(graphics.process_gpu(42)['driver'])
            (proc / 'fd/3').symlink_to('/dev/kgsl-3d0')
            self.assertIsNone(graphics.process_gpu(42)['driver'])
            (proc / 'fd/4').symlink_to('/dev/mali0')
            result = graphics.process_gpu(42)
            self.assertEqual(result['driver'], 'panvk')
            self.assertEqual(len(result['mali_devices']), 1)


if __name__ == '__main__':
    unittest.main()
