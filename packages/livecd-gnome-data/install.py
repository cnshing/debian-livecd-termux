#!/usr/bin/env python3
"""Install only portable data from verified archives into the package prefix."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile


def merge_assets(source, destination):
    """Replace profile-owned assets without following existing symlinks."""
    if source.is_symlink():
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        destination.symlink_to(source.readlink())
    elif source.is_dir():
        if destination.is_symlink():
            raise RuntimeError('Asset directory is an unexpected symlink: ' + str(destination))
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            merge_assets(child, destination / child.name)
    else:
        if destination.is_symlink():
            destination.unlink()
        shutil.copy2(source, destination)

def main():
    source, prefix, cache, builder = map(Path, sys.argv[1:])
    data = prefix / 'share/livecd-native'
    data.mkdir(parents=True, exist_ok=True)
    for name in ('fonts', 'gnome-shell/extensions', 'icons/Adwaita/cursors'):
        path = source / 'usr/share' / name
        if path.is_dir():
            merge_assets(path, data / name)
    extensions = data / 'gnome-shell/extensions'
    arc = extensions / 'arcmenu@arcmenu.com'
    shutil.copy2(builder / 'arcmenu.css', arc / 'stylesheet.css')
    icons = next(item for item in json.loads((builder / 'sources.json').read_text())
                 if item['package'] == 'arcmenu-icons')
    archive = cache / icons['url'].rsplit('/', 1)[-1]
    with tempfile.TemporaryDirectory() as temporary:
        with tarfile.open(archive) as tar:
            tar.extractall(temporary, members=[member for member in tar.getmembers()
                           if member.name.startswith('ArcMenu-v65/icons/')], filter='data')
        merge_assets(Path(temporary) / 'ArcMenu-v65/icons', arc / 'icons')
    schemas = prefix / 'opt/gnome-48/share/glib-2.0/schemas'
    schemas.mkdir(parents=True, exist_ok=True)
    for directory in (source / 'usr/share/glib-2.0/schemas', extensions):
        for path in directory.rglob('*.gschema.xml'):
            shutil.copy2(path, schemas / path.name)
    manifest = json.loads((builder / 'profile-schemas/manifest.json').read_text())
    for name, expected in manifest['files'].items():
        path = builder / 'profile-schemas' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Profile schema checksum mismatch: ' + name)
        shutil.copy2(path, schemas / name)
    font_licenses = prefix / 'share/doc/livecd-gnome-extra-fonts'
    font_licenses.mkdir(parents=True, exist_ok=True)
    for path in (source / 'licenses').glob('fonts-noto*.copyright'):
        shutil.copy2(path, font_licenses / path.name)
    for path in data.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                if stream.read(4) == b'\x7fELF':
                    raise RuntimeError('Executable in portable data package: ' + str(path))


if __name__ == '__main__':
    main()
