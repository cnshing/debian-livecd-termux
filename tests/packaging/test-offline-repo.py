#!/usr/bin/env python3
"""tools/offline-repo.py: what it asks apt to resolve, and the second suite make-apt-repo.sh adds.

Resolving itself needs Termux's repositories, so CI's assemble job is the test of that.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('offline_repo', ROOT / 'tools/offline-repo.py')
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


class Seeds(unittest.TestCase):
    def test_hooks_name_the_packages_they_install(self):
        browsers = offline.hook_packages(ROOT / 'overlays/Browser+Chromium')
        for name in ('curl', 'jq', 'firefox', 'chromium', 'bionilux', 'glibc-repo', 'glibc'):
            self.assertIn(name, browsers)
        self.assertEqual(set(offline.hook_packages(ROOT / 'overlays/Music Player')),
                         {'glibc-repo', 'glibc', 'openssl-glibc'})
        everything = [name for overlay in (ROOT / 'overlays').iterdir() if overlay.is_dir()
                      for name in offline.hook_packages(overlay)]
        self.assertFalse([name for name in everything if name.startswith(('-', '$')) or name in ('install', 'apt-get')])

    def test_bootstrap_takes_literal_names(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'scripts/generate-bootstraps.sh'
            script.parent.mkdir()
            names = [f'tool{n}' for n in range(20)]
            script.write_text('\n'.join(['\tpull_package ${TERMUX_PACKAGE_MANAGER}', '\t\tpull_package proot',
                                         '\tpull_package "$add_pkg"'] + [f'\tpull_package {n}' for n in names]))
            self.assertEqual(offline.bootstrap(Path(directory)), sorted(names))

    def test_recipes_are_pinned(self):
        self.assertIn('livecd-desktop', offline.ours())


@unittest.skipUnless(shutil.which('apt-ftparchive') and shutil.which('dpkg-deb'), 'needs apt-utils and dpkg')
class SecondSuite(unittest.TestCase):
    def deb(self, directory, name):
        tree = directory / name
        (tree / 'DEBIAN').mkdir(parents=True)
        (tree / 'DEBIAN/control').write_text(f'Package: {name}\nVersion: 1.0\nArchitecture: aarch64\n'
                                             'Maintainer: test\nDescription: test\n')
        subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(tree), str(directory / f'{name}_1.0_aarch64.deb')],
                       check=True, capture_output=True)

    def test_termux_suite_sits_beside_livecd(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for name in ('ours', 'theirs'):
                (directory / name).mkdir()
                self.deb(directory / name, name)
            make = [str(ROOT / 'tools/make-apt-repo.sh')]
            subprocess.run(make + [str(directory / 'ours'), str(directory / 'repo')], check=True)
            subprocess.run(make + [str(directory / 'theirs'), str(directory / 'repo'), 'termux'], check=True)
            repo = directory / 'repo'
            self.assertEqual(offline.index_field(repo / 'dists/livecd/main/binary-aarch64/Packages', 'Package'), ['ours'])
            self.assertEqual(offline.index_field(repo / 'dists/termux/main/binary-aarch64/Packages', 'Package'), ['theirs'])
            self.assertIn('Codename: termux', (repo / 'dists/termux/Release').read_text())
            self.assertTrue((repo / 'pool/main/ours_1.0_aarch64.deb').is_file())
            self.assertTrue((repo / 'pool/termux/theirs_1.0_aarch64.deb').is_file())


if __name__ == '__main__':
    unittest.main()
