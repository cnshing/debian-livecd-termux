#!/usr/bin/env python3
"""Pin the Debian arm64 libraries Google Chrome needs, from signed Debian indexes.

Run on a Debian PC when those libraries need security updates. Each entry also gets a
snapshot.debian.org URL, because the mirror drops superseded versions. Termux's glibc
repository has no NSS, ATK, CUPS, udev or GTK3, so Chrome takes its whole library
set from one coherent source: Debian trixie, the live CD's base.
"""
import hashlib
import json
import lzma
import time
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request

MIRROR = 'https://deb.debian.org/'
SNAPSHOT = 'https://snapshot.debian.org/file/'
KEYRING = '/usr/share/keyrings/debian-archive-keyring.gpg'
SUITES = (('debian', 'trixie'), ('debian', 'trixie-updates'), ('debian-security', 'trixie-security'))
# Chrome's DT_NEEDED entries, then what it loads with dlopen: GTK3 for its file
# dialogs and libpulse for audio.
ROOTS = ('libasound2t64 libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 libcairo2 libcups2t64 '
    'libdbus-1-3 libexpat1 libgbm1 libgcc-s1 libglib2.0-0t64 libnspr4 libnss3 libpango-1.0-0 libudev1 '
    'libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 '
    'libgtk-3-0t64 libpulse0 zlib1g').split()
# What Mesa's glibc Turnip and VA driver need beyond Chrome's own libraries, for the optional
# GPU stack. Nothing here may pull in libpci: on Android it exits the process that loads it.
GPU_ROOTS = ('libllvm19 libsensors5 libva2 libva-drm2 libva-x11-2 libva-wayland2 libx11-xcb1 libxcb-dri3-0 '
    'libxcb-present0 libxcb-randr0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxshmfence1 libzstd1').split()
# Termux's glibc supplies libc itself; the others install data, not libraries.
SKIP = re.compile(r'^(libc6|libc-.*|.*-(common|data|bin|l10n))$')


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def verified_index(area, suite):
    release = fetch(f'{MIRROR}{area}/dists/{suite}/InRelease')
    with tempfile.NamedTemporaryFile() as signed:
        signed.write(release)
        signed.flush()
        subprocess.run(['gpgv', '--keyring', KEYRING, signed.name], check=True, capture_output=True)
    wanted = re.search(r'^ ([0-9a-f]{64}) +\d+ main/binary-arm64/Packages\.xz$', release.decode(), re.M).group(1)
    data = fetch(f'{MIRROR}{area}/dists/{suite}/main/binary-arm64/Packages.xz')
    if hashlib.sha256(data).hexdigest() != wanted:
        raise RuntimeError(f'Index hash mismatch for {suite}')
    return lzma.decompress(data).decode()


def main():
    packages = {}
    # Later suites override earlier ones, so security fixes win.
    for area, suite in SUITES:
        for stanza in verified_index(area, suite).split('\n\n'):
            fields = dict(re.findall(r'^([A-Za-z0-9-]+): (.*)$', stanza, re.M))
            if 'Package' in fields:
                packages[fields['Package']] = {**fields, 'area': area}
    provides = {}
    for name, fields in packages.items():
        for entry in fields.get('Provides', '').split(','):
            if entry.strip():
                provides.setdefault(entry.split()[0], name)
    browsers = Path(__file__).resolve().parents[1] / 'overlays/Browser+Chromium/browsers'
    chrome = closure(packages, provides, ROOTS, {})
    write_lock(browsers / 'chrome-libs.lock.json', chrome)
    write_lock(browsers / 'chrome-gpu-libs.lock.json', closure(packages, provides, GPU_ROOTS, chrome))


def closure(packages, provides, roots, already):
    seen = {}
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in seen or name in already or SKIP.match(name):
            continue
        fields = packages[name]
        seen[name] = fields
        for dependency in re.split(r',\s*', fields.get('Depends', '') + ',' + fields.get('Pre-Depends', '')):
            if not dependency.strip():
                continue
            # Alternatives: the first one Debian actually carries.
            choice = next((option.split()[0] for option in dependency.split('|')
                if option.split()[0].split(':')[0] in packages or option.split()[0] in provides), None)
            if choice is None:
                raise RuntimeError(f'{name} needs unknown {dependency}')
            choice = provides.get(choice, choice) if choice not in packages else choice
            if choice.startswith('lib'):
                queue.append(choice.split(':')[0])
    return seen


def snapshot(url, sha256):
    """The by-hash snapshot.debian.org URL of a mirror file. It never moves, and it is
    cheap for the server, unlike a dated archive path."""
    data = fetch(url)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise RuntimeError('Hash mismatch: ' + url)
    permanent = f'{SNAPSHOT}{hashlib.sha1(data).hexdigest()}/{url.rsplit("/", 1)[-1]}'
    # snapshot.debian.org answers 503 or 504 now and then, and imports new files a few times a day.
    for attempt in range(5):
        try:
            urllib.request.urlopen(urllib.request.Request(permanent, method='HEAD'), timeout=120).close()
            return permanent
        except urllib.error.HTTPError as error:
            if attempt == 4:
                raise RuntimeError(f'{error.code} from {permanent}; rerun once snapshot.debian.org has it') from error
            time.sleep(15 * (attempt + 1))


def write_lock(target, seen):
    lock = [{'package': name, 'version': fields['Version'], 'url': MIRROR + fields['area'] + '/' + fields['Filename'],
             'sha256': fields['SHA256'], 'size': int(fields['Size'])} for name, fields in sorted(seen.items())]
    for item in lock:
        item['snapshot'] = snapshot(item['url'], item['sha256'])
    target.write_text(json.dumps(lock, indent=1) + '\n')
    print(f'{len(lock)} packages, {sum(item["size"] for item in lock) / 1e6:.1f} MB compressed: {target}')


if __name__ == '__main__':
    main()
