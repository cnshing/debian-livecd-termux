#!/data/data/com.termux/files/usr/bin/python
"""Connect the desktop profile to APT-owned runtime files and portable assets."""
import datetime
import hashlib
from pathlib import Path
import os
import subprocess

PREFIX = Path('/data/data/com.termux/files/usr')
ROOT = Path.home() / '.local/opt/livecd-native/gnome-48'
DATA = Path.home() / '.local/share/livecd-native'
STATE = Path.home() / '.local/state/livecd-native'
FIREFOX_UBLOCK_BOOTSTRAP_SHA256 = 'b83c6ec49f817a8d05d288b53dbc7005cceccf82e9490d8683b3120aab3c133a'


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


def migrate_firefox_ublock(backup):
    # Only the original hook's unchanged bootstrap is ours to move. Keep browser updates
    # and user-installed add-ons; Firefox may already have updated this profile's copy.
    addon = Path.home() / '.config/livecd-native/firefox/extensions/uBlock0@raymondhill.net.xpi'
    if addon.is_file() and not addon.is_symlink() and hashlib.sha256(addon.read_bytes()).hexdigest() == \
            FIREFOX_UBLOCK_BOOTSTRAP_SHA256:
        saved = backup / addon.relative_to(Path.home())
        saved.parent.mkdir(parents=True, exist_ok=True)
        addon.rename(saved)


def main():
    if os.environ.get('PREFIX') != str(PREFIX):
        raise RuntimeError('Run in native Termux')
    runtime = PREFIX / 'opt/gnome-48'
    if not (runtime / 'bin/gnome-shell').is_file():
        raise RuntimeError('Install gnome-48-runtime first')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = STATE / 'runtime-backups' / stamp
    migrate_firefox_ublock(backup)
    connect(runtime, ROOT, backup)
    # Compatibility paths used by the existing session owner and profile wrappers.
    for source in (PREFIX / 'libexec/livecd-native').glob('*.py'):
        connect(source, Path.home() / '.local/lib/livecd-native' / source.name, backup)
    for name in ('livecd', 'livecd-native'):
        connect(PREFIX / 'bin' / name, Path.home() / '.local/bin' / name, backup)
    for name in ('fonts', 'icons', 'gnome-shell/extensions'):
        directory = PREFIX / 'share/livecd-native' / name
        # Fonts, icons and extensions now come from ordinary packages in Termux's own directories.
        # Drop the links earlier installations made to the old bundle once it is gone.
        for link in (DATA / name).glob('*') if (DATA / name).is_dir() else ():
            if link.is_symlink() and not link.exists() and str(link.readlink()).startswith(str(directory)):
                link.unlink()
        for source in directory.iterdir() if directory.is_dir() else ():
            connect(source, DATA / name / source.name, backup)
    subprocess.run([str(PREFIX / 'bin/glib-compile-schemas'), '--strict',
                    str(runtime / 'share/glib-2.0/schemas')], check=True)
    print('Using packaged GNOME runtime:', runtime)


if __name__ == '__main__':
    main()
