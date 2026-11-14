#!/usr/bin/env python3
"""Check Ghostty context compatibility without changing the compositor's mode."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import terminal


class Terminal(unittest.TestCase):
    def test_qualified_package_routes_normal_launches_without_glx_probe(self):
        source = {'GALLIUM_DRIVER': 'llvmpipe', 'GSK_RENDERER': 'cairo'}
        with mock.patch.object(terminal, 'dmabuf_available', return_value=True), \
             mock.patch.object(terminal.subprocess, 'run') as run:
            argv = terminal.command(['--working-directory=/tmp/with spaces', '-e', 'echo', 'hello'], source)
            self.assertEqual(argv[0], str(terminal.PREFIX / 'bin/ghostty-panvk-dmabuf'))
            self.assertEqual(argv[1:], ['--working-directory=/tmp/with spaces', '-e', 'echo', 'hello'])
            self.assertEqual(terminal.environment(source), source)
            run.assert_not_called()

    def test_failed_device_or_hash_check_and_explicit_disable_keep_normal_terminal(self):
        for result in (subprocess.CompletedProcess([], 1, ''), subprocess.CompletedProcess([], 0, '')):
            with mock.patch.object(Path, 'is_file', return_value=True), \
                 mock.patch.object(terminal.subprocess, 'run', return_value=result):
                self.assertEqual(terminal.dmabuf_available({}), result.returncode == 0)
        with mock.patch.object(terminal.subprocess, 'run') as run:
            self.assertFalse(terminal.dmabuf_available({'LIVECD_GHOSTTY_DMABUF': '0'}))
            self.assertEqual(terminal.command([], {'LIVECD_GHOSTTY_DMABUF': '0'}), [str(terminal.PREFIX / 'bin/ghostty')])
            run.assert_not_called()

    def test_low_version_panvk_uses_software_only_for_the_terminal(self):
        original = {'LIVECD_NATIVE_VULKAN_DRIVER': 'panvk', 'LIVECD_NATIVE_RENDERER': 'zink',
                    'VK_DRIVER_FILES': '/panvk.json', 'GALLIUM_DRIVER': 'zink'}
        result = subprocess.CompletedProcess([], 0, 'OpenGL core profile version string: 4.2 (Core Profile)')
        with mock.patch.object(terminal.subprocess, 'run', return_value=result):
            env = terminal.environment(original)
        self.assertEqual(original['GALLIUM_DRIVER'], 'zink')
        self.assertEqual(env['GALLIUM_DRIVER'], 'llvmpipe')
        self.assertEqual(env['LIVECD_NATIVE_RENDERER'], 'software')
        self.assertNotIn('VK_ICD_FILENAMES', env)
        self.assertEqual(env['GSK_RENDERER'], 'cairo')

    def test_supported_panvk_keeps_gpu_rendering(self):
        result = subprocess.CompletedProcess([], 0, 'OpenGL core profile version string: 4.6 (Core Profile)')
        with mock.patch.object(terminal.subprocess, 'run', return_value=result):
            env = terminal.environment({'LIVECD_NATIVE_VULKAN_DRIVER': 'panvk', 'GALLIUM_DRIVER': 'zink'})
        self.assertEqual(env['GALLIUM_DRIVER'], 'zink')

    def test_failed_or_unreadable_probe_uses_the_working_software_path(self):
        for result in (subprocess.CompletedProcess([], 1, ''), subprocess.CompletedProcess([], 0, 'unknown')):
            with self.subTest(result=result), mock.patch.object(terminal.subprocess, 'run', return_value=result):
                self.assertEqual(terminal.environment({'LIVECD_NATIVE_VULKAN_DRIVER': 'panvk'})['GALLIUM_DRIVER'], 'llvmpipe')
        with mock.patch.object(terminal.subprocess, 'run', side_effect=subprocess.TimeoutExpired('glxinfo', 10)):
            self.assertEqual(terminal.environment({'LIVECD_NATIVE_VULKAN_DRIVER': 'panvk'})['GALLIUM_DRIVER'], 'llvmpipe')

    def test_turnip_and_software_do_not_need_a_probe(self):
        with mock.patch.object(terminal.subprocess, 'run') as run:
            for source in ({'LIVECD_NATIVE_VULKAN_DRIVER': 'turnip', 'GALLIUM_DRIVER': 'zink'},
                           {'GALLIUM_DRIVER': 'llvmpipe'}):
                self.assertEqual(terminal.environment(source)['GALLIUM_DRIVER'], source['GALLIUM_DRIVER'])
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
