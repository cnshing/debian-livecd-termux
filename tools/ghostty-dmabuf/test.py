#!/usr/bin/env python3
"""Check environment isolation and the assembled package's boundaries/integrity."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('launcher', HERE / 'launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class EnvironmentTests(unittest.TestCase):
    def test_android_kernel_guard_and_fd_close(self):
        def version(fd, request, buffer, mutate):
            self.assertEqual(request, (3 << 30) | (4 << 16) | 0x8000)
            buffer[:] = b'\x0b\x00\x23\x00'
        with patch.object(launcher.subprocess, 'check_output', return_value='x1s\n'), \
             patch.object(launcher.os, 'uname', return_value=SimpleNamespace(machine='aarch64', release='4.19.87-27102101')), \
             patch.object(launcher.os, 'open', return_value=7), \
             patch.object(launcher.os, 'close') as close, \
             patch.object(launcher.fcntl, 'ioctl', side_effect=version):
            launcher.check_device()
            close.assert_called_once_with(7)
        with patch.object(launcher.subprocess, 'check_output', return_value='other-phone\n'), \
             patch.object(launcher.os, 'uname', return_value=SimpleNamespace(machine='aarch64', release='4.19.87')), \
             patch.object(launcher.os, 'open') as device_open:
            with self.assertRaisesRegex(RuntimeError, 'qualified only'):
                launcher.check_device()
            device_open.assert_not_called()

    def test_private_stack_preserves_caller_environment(self):
        original = {'DISPLAY': ':88', 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/bus',
                    'LD_LIBRARY_PATH': str(launcher.PREFIX / 'lib') + ':/private/gnome',
                    'GSK_RENDERER': 'cairo', 'LIBGL_ALWAYS_SOFTWARE': '1',
                    'PANVK_G77_NESTED': '1', 'ZINK_DEBUG': 'validation',
                    'MESA_SHADER_CACHE_DISABLE': 'false', 'HOME': '/home/test'}
        before = original.copy()
        env = launcher.environment(original, Path('/private/stack'))
        self.assertEqual(original, before)
        self.assertEqual(env['DISPLAY'], ':88')
        self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'], original['DBUS_SESSION_BUS_ADDRESS'])
        self.assertNotIn(str(launcher.PREFIX / 'lib'), env['LD_LIBRARY_PATH'].split(':'))
        self.assertTrue(env['LD_LIBRARY_PATH'].endswith(':/private/gnome'))
        self.assertEqual(env['GSK_RENDERER'], 'gl')
        self.assertEqual(env['MESA_SHADER_CACHE_DISABLE'], 'true')
        self.assertEqual(env['ZINK_LINEAR_DMABUF_EXPORT'], '1')
        self.assertEqual(env['VK_DRIVER_FILES'], '/private/stack/icd.json')
        self.assertEqual(env['__EGL_VENDOR_LIBRARY_FILENAMES'], '/private/stack/egl-vendor.json')
        self.assertNotIn('LIBGL_ALWAYS_SOFTWARE', env)
        self.assertNotIn('PANVK_G77_NESTED', env)


    def test_changed_library_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lib = root / 'lib.so'
            lib.write_bytes(b'measured')
            (root / 'MANIFEST.json').write_text(json.dumps({'version': 'test',
                'files': {'lib.so': hashlib.sha256(b'measured').hexdigest()}, 'links': {}}))
            self.assertEqual(launcher.verify(root)['version'], 'test')
            lib.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'Package file changed'):
                launcher.verify(root)


def check_deb(deb):
    lock = json.loads((HERE / 'lock.json').read_text())
    with tempfile.TemporaryDirectory() as folder:
        stage = Path(folder)
        subprocess.run(['dpkg-deb', '-R', str(deb), str(stage)], check=True)
        prefix = stage / 'data/data/com.termux/files/usr'
        allowed = ('lib/ghostty-panvk-dmabuf/', 'share/doc/ghostty-panvk-dmabuf/',
                   'bin/ghostty-panvk-dmabuf')
        for path in stage.rglob('*'):
            if not path.is_file() and not path.is_symlink():
                continue
            if path.parent == stage / 'DEBIAN':
                assert path.name == 'control', 'Unexpected maintainer script'
            else:
                assert path.is_relative_to(prefix), 'File outside Termux prefix'
                assert str(path.relative_to(prefix)).startswith(allowed), 'File outside opt-in paths'
        root = prefix / 'lib/ghostty-panvk-dmabuf'
        manifest = json.loads((root / 'MANIFEST.json').read_text())
        actual_files, actual_links = {}, {}
        for path in root.rglob('*'):
            name = str(path.relative_to(root))
            if path.is_symlink():
                actual_links[name] = path.readlink().as_posix()
            elif path.is_file() and name != 'MANIFEST.json':
                actual_files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        assert manifest['files'] == actual_files
        assert manifest['links'] == actual_links
        assert actual_files['gtk/libgtk-4.so.1'] == lock['gtk']['library_sha256']
        assert actual_files['mesa/libgallium-26.2.6.so'] == lock['mesa']['library_sha256']
        assert actual_files['driver/bionic/libvulkan_panfrost.so'] == lock['driver']['sha256']
        assert not (root / 'android_stub').exists()
        for name, target in actual_links.items():
            if name.startswith('x11/'):
                assert target.startswith('/data/data/com.termux/files/usr/lib/')
            else:
                assert not target.startswith('/')
                assert (root / name).resolve().is_relative_to(root)
                assert (root / name).resolve().is_file()
        icd = json.loads((root / 'icd.json').read_text())
        assert (root / icd['ICD']['library_path']).resolve().is_file()
        assert (prefix / 'bin/ghostty-panvk-dmabuf').read_bytes() == (HERE / 'launcher.py').read_bytes()
        print('PASS: package boundaries, provenance, links, hashes, original library bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--deb', type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EnvironmentTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.deb:
        check_deb(args.deb)
