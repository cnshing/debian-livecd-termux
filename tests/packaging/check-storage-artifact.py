#!/usr/bin/env python3
"""Check the platform-independent Android storage provider package."""
from pathlib import Path
import subprocess
import sys
import tempfile


def main(directory):
    matches = [path for path in Path(directory).glob('*.deb')
               if subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip() == 'livecd-storage']
    assert len(matches) == 1, 'Expected one Android storage package'
    package = matches[0]
    assert subprocess.check_output(['dpkg-deb', '-f', str(package), 'Architecture'], text=True).strip() == 'all'
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(['dpkg-deb', '-x', str(package), directory], check=True)
        prefix = Path(directory) / 'data/data/com.termux/files/usr'
        for name in ('monitor.py', 'storage.py', 'migrate.py', 'protocol.xml'):
            assert (prefix / 'libexec/livecd-storage' / name).is_file(), name
        assert (prefix / 'share/gvfs/remote-volume-monitors/livecd-storage.monitor').is_file()
        service = prefix / 'share/dbus-1/services/org.gtk.vfs.LivecdStorageVolumeMonitor.service'
        assert 'Exec=/data/data/com.termux/files/usr/bin/python ' in service.read_text()
    print('PASS: storage monitor, migration, GIO registration and D-Bus activation packaged')


if __name__ == '__main__':
    main(sys.argv[1])
