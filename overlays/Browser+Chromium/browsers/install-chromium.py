#!/data/data/com.termux/files/usr/bin/python
"""Install pinned upstream ARM64 Chromium binaries on Termux's glibc loader."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
PREFIX = Path('/data/data/com.termux/files/usr')
ROOT = PREFIX / 'opt/livecd-browsers'
BASE = Path.home() / '.local/lib/livecd-native'
CACHE = Path.home() / '.cache/livecd-browsers'
LOADER = PREFIX / 'glibc/lib/ld-linux-aarch64.so.1'
spec = importlib.util.spec_from_file_location('chrome_install', HERE / 'install-chrome.py')
chrome = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chrome)


def download(item):
    path = CACHE / item['url'].rsplit('/', 1)[-1]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        temporary = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(item['url'], timeout=120) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source, output)
        if (temporary.stat().st_size != item['size'] or
                hashlib.sha256(temporary.read_bytes()).hexdigest() != item['sha256']):
            temporary.unlink()
            raise RuntimeError('Download size/hash mismatch: ' + item['url'])
        temporary.replace(path)
    return path


def integration(name, activate):
    command = 'chromium-vaapi' if name == 'chromium' else name
    launcher = PREFIX / 'bin' / command
    shutil.copy2(HERE / 'chromium-prebuilt', launcher)
    launcher.chmod(0o755)
    if not activate:
        return
    if name == 'chromium':
        # The native desktop resolves its private bin before Termux's package bin.
        # Keep the Bionic package's command untouched for explicit comparisons.
        alias = BASE / 'bin/chromium-browser'
        alias.parent.mkdir(parents=True, exist_ok=True)
        alias.write_text(f'#!{PREFIX}/bin/bash\nexec {launcher} "$@"\n')
        alias.chmod(0o700)
    title = 'Chromium' if name == 'chromium' else 'Ungoogled Chromium'
    for folder in (Path.home() / '.local/share/applications',
                   Path.home() / '.local/share/livecd-native/applications'):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name + '.desktop')).write_text(
            '[Desktop Entry]\nType=Application\nName=' + title + '\n'
            f'Exec={launcher} %U\nIcon=chromium\nTerminal=false\n'
            'Categories=Network;WebBrowser;\nMimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;\n'
            'StartupWMClass=chromium\n')


def install(name, lock, libraries, activate):
    item = lock['browsers'][name]
    fingerprint = hashlib.sha256(json.dumps({'browser': item, 'libraries': libraries,
        'compatibility': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ('bionilux-fortify.c', 'va-completion.c')},
        'installer': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, sort_keys=True).encode()).hexdigest()[:16]
    destination = ROOT / (name + '-' + fingerprint)
    if not (destination / 'livecd-vaapi.json').is_file():
        with tempfile.TemporaryDirectory(prefix='.' + name + '-', dir=ROOT) as temporary:
            work = Path(temporary)
            unpacked = work / 'unpacked'
            unpacked.mkdir()
            for archive in item['archives']:
                path = download(archive)
                if archive['kind'] == 'deb':
                    subprocess.run(['dpkg-deb', '-x', str(path), str(unpacked)], check=True)
                else:
                    with tarfile.open(path) as contents:
                        contents.extractall(unpacked, filter='data')
            stage = unpacked / item['directory']
            # Root-only helpers, packaging metadata and unused Qt integration.
            for pattern in ('chrome-sandbox', 'libqt*_shim.so', '*.TOC'):
                for path in stage.glob(pattern):
                    path.unlink()
            library_dir = stage / 'lib'
            library_dir.mkdir(exist_ok=True)
            for library in libraries:
                extracted = work / 'library'
                subprocess.run(['dpkg-deb', '-x', str(download(library)), str(extracted)], check=True)
                multiarch = extracted / 'usr/lib/aarch64-linux-gnu'
                for folder in (multiarch, multiarch / 'pulseaudio'):
                    for path in folder.glob('*.so*') if folder.is_dir() else ():
                        shutil.move(str(path), library_dir / path.name)
                shutil.rmtree(extracted)
            for path in library_dir.iterdir():
                if chrome.is_elf(path):
                    chrome.patch('--set-rpath', '$ORIGIN', path)
            for source in ('bionilux-fortify', 'va-completion'):
                subprocess.run(['clang', '--target=aarch64-linux-gnu', '--sysroot=' + str(PREFIX / 'glibc'),
                    '-isystem', str(PREFIX / 'glibc/include'), '-idirafter', str(PREFIX / 'include'),
                    '-fuse-ld=lld', '-nostdlib', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(HERE / (source + '.c')), '-o', str(library_dir / ('liblivecd-' + source + '.so'))], check=True)
            for path in stage.iterdir():
                if not chrome.is_elf(path):
                    continue
                with path.open('rb') as stream:
                    header = stream.read(20)
                if int.from_bytes(header[18:20], 'little') != 183:
                    raise RuntimeError('Not an ARM64 ELF: ' + str(path))
                chrome.patch('--set-rpath', '$ORIGIN/lib', path)
                if path.name in (item['binary'], 'chrome_crashpad_handler', 'chromedriver'):
                    chrome.patch('--set-interpreter', LOADER, path)
            # Chromium reads preinstalled extensions from beside its binary. They live
            # outside this immutable root, so a new root keeps them.
            (stage / 'extensions').symlink_to('../' + name + '-extensions')
            clean ={k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')}
            reported = subprocess.check_output([str(stage / item['binary']), '--version'], env=clean,
                                               text=True, timeout=60).strip()
            if item['version'].split('-')[0] not in reported:
                raise RuntimeError('Unexpected browser version: ' + reported)
            receipt = {'format': 1, 'abi': 'glibc', 'browser': name, 'version': item['version'],
                'binary': item['binary'], 'binary_sha256': hashlib.sha256((stage / item['binary']).read_bytes()).hexdigest(),
                'vaapi': item['vaapi'], 'upstream': item, 'libraries': libraries,
                'reported_version': reported, 'runtime_verified': False}
            (stage / 'livecd-vaapi.json').write_text(json.dumps(receipt, indent=2) + '\n')
            if destination.exists():
                raise RuntimeError('Incomplete destination exists: ' + str(destination))
            stage.rename(destination)
    receipt = json.loads((destination / 'livecd-vaapi.json').read_text())
    (ROOT / (name + '-extensions')).mkdir(exist_ok=True)
    selector = ROOT / name
    if selector.exists() and not selector.is_symlink():
        raise RuntimeError('Refusing to replace unmanaged directory: ' + str(selector))
    next_selector = ROOT / (name + '.next')
    next_selector.unlink(missing_ok=True)
    next_selector.symlink_to(destination.name)
    next_selector.replace(selector)
    integration(name, activate)
    print(name, receipt['reported_version'], 'installed:', destination, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('browsers', nargs='+', choices=('chromium', 'ungoogled-chromium'))
    p.add_argument('--activate', action='store_true', help='Add menu entries and select Chromium in the native desktop')
    args = p.parse_args()
    if os.environ.get('PREFIX') != str(PREFIX) or not LOADER.is_file():
        p.error('Run in native ARM64 Termux with glibc installed')
    CACHE.mkdir(parents=True, exist_ok=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = json.loads((HERE / 'chromium-prebuilt.lock.json').read_text())
    if lock['format'] != 1 or lock['architecture'] != 'arm64' or lock['abi'] != 'glibc':
        raise RuntimeError('Unsupported browser lock')
    libraries = json.loads((HERE / 'chromium-libs.lock.json').read_text())
    for name in args.browsers:
        install(name, lock, libraries, args.activate)
    chrome.configure_glibc()


if __name__ == '__main__':
    main()
