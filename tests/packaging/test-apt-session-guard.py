#!/usr/bin/env python3
"""livecd-desktop's APT guard: `pkg install` may add packages to a running desktop, not replace them.

Builds real archives with dpkg-deb and answers dpkg-query from a table, so it needs no root.
"""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

GUARD = Path(__file__).resolve().parents[2] / 'packages/livecd-desktop/apt-session-guard'
FAKE_DPKG_QUERY = '''#!/bin/sh
# dpkg-query --show --showformat=... PACKAGE, from "name version" lines in $INSTALLED.
for package; do :; done
version=$(sed -n "s/^$package //p" "$INSTALLED")
test -n "$version" || exit 1
printf 'installed %s' "$version"
'''


class Guard(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp())
        self.home = self.work / 'home'
        (self.home / '.local/state/livecd').mkdir(parents=True)
        bin_dir = self.work / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'dpkg-query').write_text(FAKE_DPKG_QUERY)
        (bin_dir / 'dpkg-query').chmod(0o755)
        self.installed = self.work / 'installed'
        self.installed.write_text('libfoo 1.0\n')
        self.env = {**os.environ, 'HOME': str(self.home), 'INSTALLED': str(self.installed),
                    'PATH': f'{bin_dir}:{os.environ["PATH"]}'}
        self.env.pop('LIVECD_SETUP_LOCKED', None)
        self.lock = None

    def tearDown(self):
        if self.lock:
            self.lock.close()

    def deb(self, package, version):
        root = self.work / f'{package}-{version}'
        (root / 'DEBIAN').mkdir(parents=True)
        (root / 'DEBIAN/control').write_text(f'Package: {package}\nVersion: {version}\nArchitecture: all\n'
                                             'Maintainer: test\nDescription: test\n')
        path = self.work / f'{package}_{version}_all.deb'
        subprocess.run(['dpkg-deb', '--build', str(root), str(path)], check=True, capture_output=True)
        return path

    def hold_lock(self):
        # As the desktop does: another open file description, so the guard's own flock fails.
        self.lock = (self.home / '.local/state/livecd/session.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def guard(self, *archives, **env):
        return subprocess.run([sys.executable, str(GUARD)], input=''.join(f'{a}\n' for a in archives),
                              env={**self.env, **env}, capture_output=True, text=True)

    def test_upgrade_without_desktop(self):
        self.assertEqual(self.guard(self.deb('libfoo', '2.0')).returncode, 0)

    def test_new_package_on_running_desktop(self):
        self.hold_lock()
        self.assertEqual(self.guard(self.deb('newapp', '1.0')).returncode, 0)

    def test_reinstall_on_running_desktop(self):
        self.hold_lock()
        self.assertEqual(self.guard(self.deb('libfoo', '1.0')).returncode, 0)

    def test_upgrade_on_running_desktop_is_refused(self):
        self.hold_lock()
        result = self.guard(self.deb('newapp', '1.0'), self.deb('libfoo', '2.0'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('libfoo', result.stderr)
        self.assertNotIn('newapp', result.stderr)
        self.assertIn('livecd stop', result.stderr)

    def test_setup_that_holds_the_lock_may_upgrade(self):
        self.hold_lock()
        self.assertEqual(self.guard(self.deb('libfoo', '2.0'), LIVECD_SETUP_LOCKED='1').returncode, 0)


if __name__ == '__main__':
    unittest.main()
