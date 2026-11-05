#!/data/data/com.termux/files/usr/bin/python
"""Connect the desktop profile to APT-owned runtime files and portable assets."""
import datetime
from pathlib import Path
import os
import subprocess

PREFIX = Path('/data/data/com.termux/files/usr')
ROOT = Path.home() / '.local/opt/livecd-native/gnome-48'
DATA = Path.home() / '.local/share/livecd-native'
STATE = Path.home() / '.local/state/livecd-native'


def connect(source, destination, backup):
    if destination.is_symlink() and destination.resolve() == source.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        saved = backup / destination.relative_to(Path.home())
        saved.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() and not destination.readlink().is_absolute():
            # Keep a relative link's original referent after moving its backup.
            saved.symlink_to(destination.resolve(), target_is_directory=destination.is_dir())
            destination.unlink()
        else:
            destination.rename(saved)
    destination.symlink_to(source, target_is_directory=source.is_dir())


def main():
    if os.environ.get('PREFIX') != str(PREFIX):
        raise RuntimeError('Run in native Termux')
    runtime = PREFIX / 'opt/gnome-48'
    if not (runtime / 'bin/gnome-shell').is_file():
        raise RuntimeError('Install gnome-48-runtime first')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = STATE / 'runtime-backups' / stamp
    connect(runtime, ROOT, backup)
    # Compatibility paths used by the existing session owner and profile wrappers.
    for source in (PREFIX / 'libexec/livecd-native').glob('*.py'):
        connect(source, Path.home() / '.local/lib/livecd-native' / source.name, backup)
    for name in ('livecd', 'livecd-native'):
        connect(PREFIX / 'bin' / name, Path.home() / '.local/bin' / name, backup)
    for name in ('fonts', 'icons', 'gnome-shell/extensions'):
        directory = PREFIX / 'share/livecd-native' / name
        for source in directory.iterdir():
            connect(source, DATA / name / source.name, backup)
    subprocess.run([str(PREFIX / 'bin/glib-compile-schemas'), '--strict',
                    str(runtime / 'share/glib-2.0/schemas')], check=True)
    print('Using packaged GNOME runtime:', runtime)


if __name__ == '__main__':
    main()
