#!/usr/bin/env python3
"""Verify the Actions output contains native SMB and DNS-SD backends."""
from pathlib import Path
import subprocess
import sys
import tempfile


def main(directory):
    packages = {}
    for path in Path(directory).glob('*.deb'):
        name = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip()
        if name in ('gvfs', 'avahi'):
            packages[name] = path
    assert set(packages) == {'gvfs', 'avahi'}, 'Missing network package artifact'
    prefix = Path('data/data/com.termux/files/usr')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, path in packages.items():
            architecture = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Architecture'], text=True).strip()
            assert architecture == 'aarch64', (name, architecture)
            subprocess.run(['dpkg-deb', '-x', str(path), str(root)], check=True)
        checks = {'libexec/gvfsd-smb': 'libsmbclient.so',
                  'libexec/gvfsd-smb-browse': 'libsmbclient.so',
                  'libexec/gvfsd-dnssd': 'libavahi-client.so',
                  'bin/avahi-daemon': 'libdbus-1.so'}
        for relative, library in checks.items():
            binary = root / prefix / relative
            assert binary.is_file(), relative
            dynamic = subprocess.check_output(['readelf', '-d', str(binary)], text=True)
            assert library in dynamic, (relative, library)
            headers = subprocess.check_output(['readelf', '-l', str(binary)], text=True)
            assert '/system/bin/linker64' in headers, relative
        for name in ('smb.mount', 'smb-browse.mount', 'dns-sd.mount'):
            assert (root / prefix / 'share/gvfs/mounts' / name).is_file(), name
        assert (root / prefix / 'bin/avahi-network-discovery').is_file()
    print('PASS: aarch64 Android backends, linked dependencies and mount definitions')


if __name__ == '__main__':
    main(sys.argv[1])
