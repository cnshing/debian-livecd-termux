#!/data/data/com.termux/files/usr/bin/python
"""Assemble a pinned, private Android runtime; never run an upstream installer."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get('LIVECD_NATIVE_CACHE', str(Path.home() / '.cache/livecd-native')))
ROOT = Path.home() / '.local/opt/livecd-native/gnome-48'
DATA = Path.home() / '.local/share/livecd-native'


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


def fetch(item, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / name
    if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() != item['sha256']:
        part = dest.with_suffix(dest.suffix + '.part')
        print('Downloading', item['url'], flush=True)
        subprocess.run(['curl', '--fail', '--location', '--retry', '3', item['url'], '-o', str(part)], check=True)
        if hashlib.sha256(part.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('SHA-256 mismatch: ' + name)
        part.replace(dest)
    return dest


def apply_patches(package, directory):
    """Apply a package's patches, filling in the same placeholders as termux-packages."""
    for patch in sorted((HERE / 'patches' / package).glob('*.patch')):
        text = patch.read_text().replace('@TERMUX_HOME@', str(Path.home())).replace('@TERMUX_PREFIX@', os.environ['PREFIX'])
        subprocess.run(['patch', '--batch', '--silent', '-p1', '-d', str(directory)], input=text, text=True, check=True)


def main():
    lock = json.loads((HERE / 'sources.lock.json').read_text())
    archive = fetch(lock['runtime'], 'gnome-termux-' + lock['runtime']['revision'] + '.tar.gz')
    ROOT.parent.mkdir(parents=True, exist_ok=True)
    # Recreate only the profile-owned runtime, never the shared Termux prefix.
    with tempfile.TemporaryDirectory(dir=CACHE) as temp:
        with tarfile.open(archive) as source:
            source.extractall(temp, filter='data')
        src = Path(temp) / lock['runtime']['subdirectory']
        staged = ROOT.with_name('gnome-48.staging')
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(src, staged, symlinks=True)
        # Archive-generated entry points contain author-local paths and GPU policy.
        for path in (staged / 'bin').iterdir():
            if path.name not in ('gnome-shell', 'gjs-console'):
                path.unlink()
        (staged / 'bin/gjs').symlink_to('gjs-console')
        (staged / 'gnome-termux-env.sh').unlink(missing_ok=True)
        for path in (staged / 'bin').iterdir():
            path.chmod(0o755)
        if ROOT.exists():
            shutil.rmtree(ROOT)
        staged.replace(ROOT)
    DATA.mkdir(parents=True, exist_ok=True)
    for item in lock['data']:
        archive = fetch(item, item['url'].rsplit('/', 1)[-1])
        with tempfile.TemporaryDirectory(dir=CACHE) as temp:
            subprocess.run(['dpkg-deb', '-x', str(archive), temp], check=True)
            apply_patches(item['package'], temp)
            share = Path(temp) / 'usr/share'
            # Only architecture-independent fonts, JS, schemas and attribution.
            # Debian executables, native libraries and package scripts are excluded.
            for name in ('fonts', 'gnome-shell/extensions', 'icons/Adwaita/cursors', 'doc/' + item['package']):
                src = share / name
                if src.is_dir():
                    merge_assets(src, DATA / name)
            for path in (share / 'glib-2.0/schemas').glob('*.gschema.xml'):
                shutil.copy2(path, ROOT / 'share/glib-2.0/schemas' / path.name)
    extensions = DATA / 'gnome-shell/extensions'
    for path in extensions.rglob('*'):
        if path.is_file() and path.open('rb').read(4) == b'\x7fELF':
            raise RuntimeError('Unexpected native binary in data assets: ' + str(path))
        if path.suffix == '.gschema.xml':
            dest = ROOT / 'share/glib-2.0/schemas' / path.name
            shutil.copy2(path, dest)
    arc = extensions / 'arcmenu@arcmenu.com/stylesheet.css'
    if not arc.exists():
        repo = HERE.parents[1]
        shutil.copy2(repo / 'overlays/Desktop Environment+Shell/filesystem/live_installed/usr/share/gnome-shell/extensions/arcmenu@arcmenu.com/stylesheet.css', arc)
    # Debian's package also omits the icons ArcMenu loads from its own directory.
    arc_source = fetch({'url': 'https://deb.debian.org/debian/pool/main/g/gnome-shell-extension-arc-menu/gnome-shell-extension-arc-menu_65.orig.tar.gz',
        'sha256': 'e38aba4038540cc9153f9d10d9742f8f403aeaeec7990dfdd6a2d0476c6a0a23'}, 'gnome-shell-extension-arc-menu_65.orig.tar.gz')
    with tempfile.TemporaryDirectory(dir=CACHE) as temp:
        with tarfile.open(arc_source) as source:
            source.extractall(temp, members=[m for m in source.getmembers() if m.name.startswith('ArcMenu-v65/icons/')], filter='data')
        merge_assets(Path(temp) / 'ArcMenu-v65/icons', extensions / 'arcmenu@arcmenu.com/icons')
    gsd = fetch({'url': 'https://download.gnome.org/sources/gnome-settings-daemon/48/gnome-settings-daemon-48.1.tar.xz',
        'sha256': '3860a2ea214dcbcb6600ae7a1e3358a5389215087bc3e4a47cee3f87baee062e'}, 'gnome-settings-daemon-48.1.tar.xz')
    with tarfile.open(gsd) as source:
        text = source.extractfile('gnome-settings-daemon-48.1/data/org.gnome.settings-daemon.plugins.color.gschema.xml.in').read().decode()
        peripherals = source.extractfile('gnome-settings-daemon-48.1/data/org.gnome.settings-daemon.peripherals.gschema.xml.in').read().decode()
    (ROOT / 'share/glib-2.0/schemas/org.gnome.settings-daemon.plugins.color.gschema.xml').write_text(text.replace('@GETTEXT_PACKAGE@', 'gnome-settings-daemon'))
    # Shell's indicators need only this schema from the file; the others need generated enums.
    touchscreen = re.search(r'<schema [^>]*id="org\.gnome\.settings-daemon\.peripherals\.touchscreen".*?</schema>', peripherals, re.DOTALL).group()
    (ROOT / 'share/glib-2.0/schemas/org.gnome.settings-daemon.peripherals.touchscreen.gschema.xml').write_text(
        '<schemalist>' + touchscreen.replace('@GETTEXT_PACKAGE@', 'gnome-settings-daemon') + '</schemalist>\n')
    search = fetch({'url': 'https://github.com/GNOME/localsearch/archive/refs/tags/3.9.0.tar.gz',
        'sha256': '6d8d5ff2a2320632e2cd14ef5a9c6a57d67430ac71d36428a257404a81dcf943'}, 'localsearch-3.9.0.tar.gz')
    with tarfile.open(search) as source:
        text = source.extractfile('localsearch-3.9.0/data/org.freedesktop.Tracker.Miner.Files.gschema.xml').read().decode()
    text = text.replace('@INDEX_RECURSIVE_DIRS@', '').replace('@INDEX_SINGLE_DIRS@', '')
    (ROOT / 'share/glib-2.0/schemas/org.freedesktop.Tracker3.Miner.Files.gschema.xml').write_text(text)
    subprocess.run(['glib-compile-schemas', '--strict', str(ROOT / 'share/glib-2.0/schemas')], check=True)
    # The livecd-gi-paths package supplies the adapter this replaces libgirepository with.
    subprocess.run(['patchelf', '--replace-needed', 'libgirepository-1.0.so',
        'liblivecd-gi-paths.so', str(ROOT / 'bin/gnome-shell')], check=True)
    # The bundle omits Mutter's GTK frame client. The mutter-x11-frames package installs it at
    # the path this libmutter runs it from, so neither the library nor the prefix needs relocating.
    # The tracked GIR was updated for GioUnix.DesktopAppInfo, but the bundled
    # Shell typelib was not regenerated. Use the matching published GIR.
    gir = ROOT / 'share/gnome-shell/Shell-16.gir'
    text = gir.read_text()
    if '<include name="GioUnix"' not in text:
        text = text.replace('<include name="Gio" version="2.0"/>',
            '<include name="Gio" version="2.0"/>\n  <include name="GioUnix" version="2.0"/>')
    gir.write_text(text)
    subprocess.run(['g-ir-compiler', str(gir),
        '--includedir=' + str(ROOT / 'lib/mutter-16'),
        '--includedir=' + str(ROOT / 'share/gnome-shell'),
        '--output=' + str(ROOT / 'lib/gnome-shell/Shell-16.typelib')], check=True)
    # The binary bundle contains the JS entry points but omits D-Bus activation
    # files and hardcodes its build prefix in each package initializer.
    services = DATA / 'dbus-1/services'
    services.mkdir(parents=True, exist_ok=True)
    for name in ('org.gnome.Shell.Extensions', 'org.gnome.Shell.Notifications', 'org.gnome.Extensions', 'org.gnome.ScreenSaver'):
        entry = ROOT / 'share/gnome-shell' / name
        if not entry.is_file():
            continue
        entry.write_text(entry.read_text().replace("prefix: '/data/data/com.termux/files/usr'", 'prefix: ' + repr(str(ROOT)))
            .replace("libdir: '/data/data/com.termux/files/usr/lib'", 'libdir: ' + repr(str(ROOT / 'lib'))))
        (services / (name + '.service')).write_text('[D-BUS Service]\nName=' + name + '\nExec='
            + str(ROOT / 'bin/gjs') + ' -m ' + str(entry) + '\n')
    (ROOT / 'sources.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    print('Private runtime prepared:', ROOT)


if __name__ == '__main__':
    main()
