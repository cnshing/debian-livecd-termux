#!/usr/bin/env python3
"""Exercise pinned fallback, offline behavior and idempotent Mali upgrades."""
import hashlib
import importlib.util
import json
import os
import shlex
import pwd
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('panvk_install', REPO / 'tools/install-panvk-desktop.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class Install(unittest.TestCase):
    def exercise(self, current=False, repository=False, offline=False, corrupt=False):
        calls = []
        item = {'name': 'driver', 'version': '2-1', 'file': 'driver.deb',
                'sha256': hashlib.sha256(b'payload').hexdigest()}
        def run(command, **kwargs):
            calls.append(command)
            name = command[0]
            code, output = 0, ''
            if name == 'dpkg-query': code, output = (0, 'installed\t3-1') if current else (1, '')
            if name == 'apt-cache': code = 0 if repository else 1
            if name == 'curl': Path(command[-1]).write_bytes(b'bad' if corrupt else b'payload')
            return subprocess.CompletedProcess(command, code, output, '')
        with mock.patch.object(installer.subprocess, 'run', side_effect=run), \
             mock.patch.object(installer.subprocess, 'check_output', return_value='Package: driver\nVersion: 2-1\n'), \
             mock.patch.object(installer, 'cache_repository', return_value=Path('/pinned/source.list')):
            installer.ensure([item], 'https://example.invalid', offline, Path('/fixture-prefix'))
        return calls

    def test_current_package_is_not_downgraded_or_downloaded(self):
        calls = self.exercise(current=True)
        self.assertFalse(any(c[0] in ('apt-get', 'curl') for c in calls))

    def test_offline_repository_uses_apt_without_download(self):
        calls = self.exercise(repository=True, offline=True)
        self.assertFalse(any(c[0] == 'curl' for c in calls))
        self.assertEqual(calls[-1][-1], 'driver=2-1')

    def test_old_online_repository_uses_verified_asset(self):
        calls = self.exercise()
        self.assertTrue(any(c[0] == 'curl' for c in calls))
        self.assertTrue(any(c[0] == 'apt-get' and c[-1] == 'update' for c in calls))
        self.assertEqual(calls[-1][0], 'apt-get')
        self.assertTrue(calls[-1][-1].endswith('/driver.deb'))

    def test_missing_offline_package_and_corrupt_asset_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'offline repository lacks'):
            self.exercise(offline=True)
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.exercise(corrupt=True)

    def test_installer_defaults_only_qualified_mali_and_preserves_saved_software(self):
        block = (REPO / 'install.sh').read_text().split('# Qualcomm uses Turnip;', 1)[1].split('# Earlier versions', 1)[0]
        block = '# Qualcomm uses Turnip;' + block
        block = block.replace('test -e /dev/kgsl-3d0', 'false')
        block = block.replace('python - ', shlex.quote(sys.executable) + ' - ')
        block = block.replace('python "$repo/src/native/panvk_device.py"', 'test "$QUALIFIED" = 1')
        block = block.replace('test -r /dev/mali0 && test -w /dev/mali0', 'false')
        for supported, saved, expected in [('1', {}, 'zink'), ('1', {'native_renderer': 'software'}, 'software'), ('0', {}, None)]:
            with self.subTest(supported=supported, saved=saved), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                config = home / '.local/lib/livecd/config.json'
                config.parent.mkdir(parents=True)
                config.write_text(json.dumps(saved))
                subprocess.run(['bash', '-c', 'set -euo pipefail; repo=.; state=.; ' + block],
                    env={**os.environ, 'HOME': folder, 'QUALIFIED': supported},
                    capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(config.read_text()).get('native_renderer'), expected)

    def test_cached_repository_keeps_newer_candidate_at_project_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = []
            for version in ['1-1', '2-1']:
                tree = root / ('package-' + version)
                (tree / 'DEBIAN').mkdir(parents=True)
                (tree / 'DEBIAN/control').write_text('Package: mesa-vulkan-icd-panvk-kbase\n'
                    + 'Version: ' + version + '\nArchitecture: all\nMaintainer: test <test@example.invalid>\nDescription: fixture\n')
                deb = root / ('driver-' + version + '.deb')
                subprocess.run(['dpkg-deb', '--build', str(tree), str(deb)], check=True, capture_output=True)
                sources.append(installer.cache_repository([deb], root / ('prefix-' + version)))
            source = root / 'sources.list'
            source.write_text(''.join(p.read_text() for p in sources))
            (root / 'lists/partial').mkdir(parents=True)
            (root / 'cache').mkdir()
            (root / 'empty').mkdir()
            (root / 'status').write_text('')
            options = []
            for key, value in {
                'Dir::Etc::SourceList': source, 'Dir::Etc::SourceParts': '-',
                'Dir::Etc::Preferences': root / 'prefix-2-1/etc/apt/preferences.d/livecd-panvk',
                'Dir::Etc::PreferencesParts': root / 'empty', 'Dir::State::lists': root / 'lists',
                'Dir::State::status': root / 'status', 'Dir::Cache': root / 'cache',
                'APT::Architecture': 'aarch64', 'APT::Sandbox::User': pwd.getpwuid(os.getuid()).pw_name,
            }.items():
                options += ['-o', str(key) + '=' + str(value)]
            subprocess.run(['apt-get', *options, 'update'], capture_output=True, text=True, check=True)
            policy = subprocess.check_output(['apt-cache', *options, 'policy', 'mesa-vulkan-icd-panvk-kbase'], text=True)
            self.assertIn('Candidate: 2-1', policy)
            self.assertIn('2-1 1001', policy)

    def test_incompatible_device_does_not_touch_apt(self):
        with mock.patch.object(installer, 'qualified', return_value=False), \
             mock.patch.object(installer, 'ensure') as ensure:
            installer.main()
            ensure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
