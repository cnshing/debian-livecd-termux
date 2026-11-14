#!/usr/bin/env python3
"""Exercise the real installer block with mocked hardware, APT and downloads."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
BLOCK = (REPO / 'install.sh').read_text().split('# The measured G77 stack', 1)[1].split('# Runtime code', 1)[0]
BLOCK = '# The measured G77 stack' + BLOCK
BLOCK = BLOCK.replace('test -r /dev/mali0 && test -w /dev/mali0', 'true')
STUB = r'''
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f: f.write(json.dumps([name,*args])+'\n')
if name=='python':
    if len(args)>1 and args[1].endswith('/launcher.py'):
        sys.stdin.read()
        sys.exit(0 if os.environ.get('COMPATIBLE')=='1' else 1)
    os.execv(sys.executable,[sys.executable,*args])
if name=='apt-cache': sys.exit(0 if os.environ.get('REPO_PACKAGE')=='1' else 1)
if name=='dpkg': sys.exit(0 if os.environ.get('CURRENT_CONTROLLER')=='1' else 1)
if name=='dpkg-query': print('0.2.0-17',end='')
if name=='curl':
    data=b'controller' if 'livecd-desktop' in args[-3] else b'stack'
    if os.environ.get('CORRUPT')=='1': data=b'tampered'
    pathlib.Path(args[args.index('-o')+1]).write_bytes(data)
'''


class Install(unittest.TestCase):
    def exercise(self, **settings):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root / 'bin'
            binary.mkdir()
            for name in ('python', 'apt-cache', 'apt-get', 'dpkg', 'dpkg-query', 'curl', 'ghostty-panvk-dmabuf'):
                path = binary / name
                path.write_text('#!' + sys.executable + '\n' + STUB)
                path.chmod(0o755)
            recipe = root / 'packages/ghostty-panvk-dmabuf'
            recipe.mkdir(parents=True)
            (recipe / 'release.lock.json').write_text(json.dumps({
                'version': '1.0-2', 'release': 'https://example.invalid/pinned',
                'file': 'stack.deb', 'sha256': hashlib.sha256(b'stack').hexdigest(),
                'controller_file': 'livecd-desktop.deb',
                'controller_sha256': hashlib.sha256(b'controller').hexdigest()}))
            calls = root / 'calls'
            result = subprocess.run(['bash', '-c', 'set -euo pipefail\n'
                'repo="$FIXTURE"; state="$FIXTURE/state"; offline="${OFFLINE:-}"; apt=(apt-get)\n' + BLOCK],
                env={**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
                     'PREFIX': str(root), 'FIXTURE': str(root), 'CALLS': str(calls),
                     'COMPATIBLE': '1', 'CURRENT_CONTROLLER': '1', **settings},
                text=True, capture_output=True)
            return result, [json.loads(s) for s in calls.read_text().splitlines()]

    def test_incompatible_hardware_never_installs_or_downloads(self):
        result, calls = self.exercise(COMPATIBLE='0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c[0] in ('apt-get', 'curl') for c in calls))

    def test_repository_package_and_offline_path_need_no_network(self):
        result, calls = self.exercise(REPO_PACKAGE='1', OFFLINE='/offline')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['apt-get', 'install', 'ghostty-panvk-dmabuf=1.0-2'], calls)
        self.assertFalse(any(c[0] == 'curl' for c in calls))

    def test_old_online_release_gets_both_pinned_packages(self):
        result, calls = self.exercise(CURRENT_CONTROLLER='0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len([c for c in calls if c[0] == 'apt-get']), 2)
        self.assertEqual(len([c for c in calls if c[0] == 'curl']), 2)

    def test_corrupt_download_stops_before_apt_install(self):
        result, calls = self.exercise(CORRUPT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c[0] == 'apt-get' for c in calls))

    def test_old_offline_release_fails_without_downloading(self):
        result, calls = self.exercise(OFFLINE='/offline')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('newer offline tarball', result.stderr)
        self.assertFalse(any(c[0] in ('apt-get', 'curl') for c in calls))


if __name__ == '__main__':
    unittest.main()
