#!/usr/bin/env python3
"""Reject Nautilus artifacts whose ICU ABI is unavailable on a fresh install.

Run during assembly too: cached artifacts can outlive the mirror's ICU version.
Use --libicu-deb for an offline check against a previously downloaded package.
"""
import argparse
import gzip
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

MIRROR = 'https://packages.termux.dev/apt/termux-main/'
PREFIX = Path('data/data/com.termux/files/usr')


def field(package, name):
    return subprocess.check_output(['dpkg-deb', '-f', str(package), name], text=True).strip()


def download_icu(directory):
    url = MIRROR + 'dists/stable/main/binary-aarch64/Packages.gz'
    with urllib.request.urlopen(url, timeout=60) as response:
        index = gzip.decompress(response.read()).decode()
    for paragraph in index.split('\n\n'):
        metadata = dict(line.split(': ', 1) for line in paragraph.splitlines() if ': ' in line)
        if metadata.get('Package') == 'libicu' and metadata.get('Architecture') == 'aarch64':
            with urllib.request.urlopen(MIRROR + metadata['Filename'], timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != metadata['SHA256']:
                raise RuntimeError('Mirror libicu SHA256 mismatch')
            package = directory / 'libicu.deb'
            package.write_bytes(data)
            return package
    raise RuntimeError('libicu missing from the current Termux mirror')


def check(nautilus, libicu, directory):
    app, libraries = directory / 'nautilus', directory / 'icu'
    for package, root in ((nautilus, app), (libicu, libraries)):
        subprocess.run(['dpkg-deb', '-x', str(package), str(root)], check=True)
    binary = app / PREFIX / 'bin/nautilus'
    dynamic = subprocess.check_output(['readelf', '-d', str(binary)], text=True)
    needed = set(re.findall(r'\(NEEDED\).*\[(libicu[^\]]+)\]', dynamic))
    if not needed:
        raise RuntimeError('Nautilus has no ICU DT_NEEDED entries')
    available = {path.name for path in (libraries / PREFIX / 'lib').glob('libicu*.so*')}
    missing = needed - available
    if missing:
        raise RuntimeError('Nautilus needs ICU libraries absent from the mirror: ' + ', '.join(sorted(missing)))
    depends = field(nautilus, 'Depends')
    major = re.fullmatch(r'libicuuc\.so\.(\d+)', next(name for name in needed if name.startswith('libicuuc.')))[1]
    for bound in (f'libicu (>= {major})', f'libicu (<< {int(major) + 1})'):
        if bound not in [part.strip() for part in depends.split(',')]:
            raise RuntimeError('Nautilus must declare ' + bound)
    print('PASS: Nautilus ICU ABI matches the mirror and its declared dependency bounds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--libicu-deb', type=Path)
    args = parser.parse_args()
    packages = [path for path in args.directory.glob('*.deb') if field(path, 'Package') == 'nautilus']
    if len(packages) != 1:
        raise RuntimeError('Expected exactly one Nautilus package artifact')
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        check(packages[0], args.libicu_deb or download_icu(directory), directory)


if __name__ == '__main__':
    main()
