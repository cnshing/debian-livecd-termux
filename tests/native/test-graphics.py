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
