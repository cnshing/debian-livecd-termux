#!/data/data/com.termux/files/usr/bin/python
"""Install Google's own arm64 Chrome on Termux's glibc loader, without PRoot.

The deb is checked through Google's signed repository index, using the key the live
CD trusts. Its libraries come from chrome-libs.lock.json. A failed start leaves any
previous installation in place.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
REPO_KEY = HERE.parents[2] / 'overlays/Browser/repos/google-chrome.yaml'
INDEX = 'https://dl.google.com/linux/chrome/deb/'
PREFIX = Path(os.environ['PREFIX'])
TARGET = PREFIX / 'opt/google/chrome'
LOADER = PREFIX / 'glibc/lib/ld-linux-aarch64.so.1'
CACHE = Path.home() / '.cache/livecd-browsers'
# Parts of the deb that need root, Qt, or Google's enterprise management.
UNUSED = ('chrome-sandbox', 'chrome-management-service', 'google-chrome', 'default-app-block',
    'libqt5_shim.so', 'libqt6_shim.so', 'apparmor.d', 'cron')


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def cached(url, sha256, fallback=None):
    """Return a verified download, reusing the cache only when its hash still matches.

    Debian's mirror drops superseded versions, so a lock's snapshot.debian.org copy is the fallback.
    """
    path = CACHE / url.rsplit('/', 1)[-1]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        try:
            data = fetch(url)
        except urllib.error.HTTPError as error:
            if error.code != 404 or not fallback:
                raise
            data = fetch(fallback)
        if hashlib.sha256(data).hexdigest() != sha256:
            raise RuntimeError('Hash mismatch: ' + url)
        path.write_bytes(data)
    return path


def latest_stable(work):
    armored = '\n'.join(line.strip() for line in REPO_KEY.read_text().splitlines())
    armored = armored[armored.index('-----BEGIN PGP'):armored.index('-----END PGP PUBLIC KEY BLOCK-----') + 34] + '\n'
    keyring = work / 'google.gpg'
    subprocess.run(['gpg', '--batch', '--yes', '--dearmor', '--homedir', str(work), '-o', str(keyring)],
        input=armored.encode(), check=True, capture_output=True)
    release = work / 'Release'
    signature = work / 'Release.gpg'
    release.write_bytes(fetch(INDEX + 'dists/stable/Release'))
    signature.write_bytes(fetch(INDEX + 'dists/stable/Release.gpg'))
    subprocess.run(['gpgv', '--keyring', str(keyring), str(signature), str(release)], check=True, capture_output=True)
    sums = release.read_text().split('SHA256:', 1)[1]
    wanted = re.search(r'^ ([0-9a-f]{64}) +\d+ main/binary-arm64/Packages$', sums, re.M).group(1)
    index = fetch(INDEX + 'dists/stable/main/binary-arm64/Packages')
    if hashlib.sha256(index).hexdigest() != wanted:
        raise RuntimeError('Google index hash mismatch')
    for stanza in index.decode().split('\n\n'):
        fields = dict(re.findall(r'^([A-Za-z0-9-]+): (.*)$', stanza, re.M))
        if fields.get('Package') == 'google-chrome-stable':
            return fields
    raise RuntimeError('google-chrome-stable is not in the arm64 index')


def is_elf(path):
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as stream:
        return stream.read(4) == b'\x7fELF'


def patch(*args):
    subprocess.run(['patchelf', *map(str, args)], check=True)


def install_libraries(stage, work):
    libraries = stage / 'lib'
    libraries.mkdir()
    for item in json.loads((HERE / 'chrome-libs.lock.json').read_text()):
        unpacked = work / ('deb-' + item['package'])
        subprocess.run(['dpkg-deb', '-x', str(cached(item['url'], item['sha256'], item.get('snapshot'))), str(unpacked)], check=True)
        multiarch = unpacked / 'usr/lib/aarch64-linux-gnu'
        # libpulse keeps one private library in this subdirectory.
        for folder in (multiarch, multiarch / 'pulseaudio'):
            for path in folder.glob('*.so*') if folder.is_dir() else ():
                if path.is_symlink() or path.is_file():
                    shutil.move(str(path), libraries / path.name)
        shutil.rmtree(unpacked)
    for path in libraries.iterdir():
        if is_elf(path):
            # DT_RUNPATH, not LD_LIBRARY_PATH: an environment variable would reach
            # Termux's Bionic programs when Chrome starts them.
            patch('--set-rpath', '$ORIGIN', path)


def configure_glibc():
    # Android has no /etc/resolv.conf, and glibc cannot ask Android's resolver as Bionic
    # does. Share the files Termux keeps for programs in the same position.
    etc = PREFIX / 'glibc/etc'
    for name in ('resolv.conf', 'hosts'):
        if not (etc / name).exists():
            (etc / name).symlink_to(PREFIX / 'etc' / name)
    if not (etc / 'nsswitch.conf').exists():
        (etc / 'nsswitch.conf').write_text('hosts: files dns\n')


def install_integration(deb_root, version):
    bin_dir = PREFIX / 'bin'
    shutil.copy2(HERE / 'google-chrome', bin_dir / 'google-chrome')
    (bin_dir / 'google-chrome').chmod(0o755)
    (bin_dir / 'google-chrome-stable').unlink(missing_ok=True)
    (bin_dir / 'google-chrome-stable').symlink_to('google-chrome')
    entry = (deb_root / 'usr/share/applications/google-chrome.desktop').read_text()
    applications = PREFIX / 'share/applications'
    applications.mkdir(parents=True, exist_ok=True)
    (applications / 'google-chrome.desktop').write_text(entry.replace('/usr/bin/', str(bin_dir) + '/'))
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon = PREFIX / f'share/icons/hicolor/{size}x{size}/apps/google-chrome.png'
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TARGET / f'product_logo_{size}.png', icon)
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(applications)], check=True)
    if shutil.which('gtk-update-icon-cache'):
        subprocess.run(['gtk-update-icon-cache', '-q', '-f', str(PREFIX / 'share/icons/hicolor')], check=False)
    (TARGET / 'INSTALLED_VERSION').write_text(version + '\n')


def main():
    if not LOADER.is_file():
        sys.exit('Install glibc first: apt-get install glibc-repo && apt-get update && apt-get install glibc')
    CACHE.mkdir(parents=True, exist_ok=True)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=TARGET.parent, prefix='.chrome-work-'))
    try:
        work.chmod(0o700)
        fields = latest_stable(work)
        print('[Google Chrome] ==> Latest stable for arm64:', fields['Version'], flush=True)
        deb = cached(INDEX + fields['Filename'], fields['SHA256'])
        unpacked = work / 'deb'
        subprocess.run(['dpkg-deb', '-x', str(deb), str(unpacked)], check=True)
        stage = unpacked / 'opt/google/chrome'
        for name in UNUSED:
            path = stage / name
            shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
        install_libraries(stage, work)
        patch('--set-interpreter', LOADER, '--set-rpath', '$ORIGIN/lib', stage / 'chrome')
        patch('--set-interpreter', LOADER, '--set-rpath', '$ORIGIN/lib', stage / 'chrome_crashpad_handler')
        for path in stage.glob('*.so*'):
            if is_elf(path):
                patch('--set-rpath', '$ORIGIN/lib', path)
        # Prove this stage starts before it replaces what is installed.
        clean = {k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')}
        reported = subprocess.run([str(stage / 'chrome'), '--version'], env=clean, check=True,
            capture_output=True, text=True, timeout=60).stdout.strip()
        print('[Google Chrome] ==> Stage reports:', reported, flush=True)
        if TARGET.is_dir():
            for kept in ('extensions', 'gpu'):
                if (TARGET / kept).is_dir():
                    shutil.move(str(TARGET / kept), stage / kept)
            TARGET.rename(work / 'previous')
        stage.rename(TARGET)
        configure_glibc()
        install_integration(unpacked, fields['Version'])
    finally:
        shutil.rmtree(work)
    print('[Google Chrome] ==> Installed to', TARGET)


if __name__ == '__main__':
    main()
