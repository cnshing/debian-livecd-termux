#!/usr/bin/env python3
"""Pin ARM64 VA-API browser binaries and libraries from their upstream publishers.

Run on Debian to refresh the lock, then reinstall the browsers on Termux.
Debian binaries follow signed archive indexes; ungoogled Chromium follows its
project's release API and published asset digest. Neither browser is compiled.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent
DEST = HERE.parent / 'overlays/Browser+Chromium/browsers'
spec = importlib.util.spec_from_file_location('debian_libraries', HERE / 'lock-chrome-libs.py')
debian = importlib.util.module_from_spec(spec)
spec.loader.exec_module(debian)
UPSTREAM = 'https://github.com/ungoogled-software/ungoogled-chromium-portablelinux'
EXTRA = ('libdav1d7 libdouble-conversion3 libharfbuzz-subset0 libminizip1t64 libopenh264-8 '
         'libopenjp2-7 libxnvctrl0').split()


def main():
    packages = {}
    for area, suite in debian.SUITES:
        for stanza in debian.verified_index(area, suite).split('\n\n'):
            fields = dict(re.findall(r'^([A-Za-z0-9-]+): (.*)$', stanza, re.M))
            if 'Package' in fields:
                packages[fields['Package']] = {**fields, 'area': area}
    provides = {}
    for name, fields in packages.items():
        for entry in fields.get('Provides', '').split(','):
            if entry.strip():
                provides.setdefault(entry.split()[0], name)
    libraries = debian.closure(packages, provides, [*debian.ROOTS, *EXTRA], {})
    debian.write_lock(DEST / 'chromium-libs.lock.json', libraries)
    archives = []
    version = packages['chromium']['Version']
    for name in ('chromium', 'chromium-common'):
        p = packages[name]
        if p['Version'] != version or p['Architecture'] != 'arm64':
            raise RuntimeError('Debian browser/resources architecture or version mismatch')
        archives.append({'url': debian.MIRROR + p['area'] + '/' + p['Filename'],
                         'sha256': p['SHA256'], 'size': int(p['Size']), 'kind': 'deb'})
    source_url = archives[0]['url'].rsplit('/', 1)[0] + '/chromium_' + version + '.debian.tar.xz'
    source = debian.fetch(source_url)
    with tarfile.open(fileobj=io.BytesIO(source)) as contents:
        rules = contents.extractfile('debian/rules').read().decode()
    arm = rules.split('ifeq (arm64,$(DEB_HOST_ARCH))', 1)[1].split('endif', 1)[0]
    if 'use_vaapi=true' not in arm:
        raise RuntimeError('Debian no longer enables VA-API for ARM64')
    release = json.loads(debian.fetch('https://api.github.com/repos/ungoogled-software/ungoogled-chromium-portablelinux/releases/latest'))
    asset = next(a for a in release['assets'] if a['name'].endswith('-arm64_linux.tar.xz'))
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise RuntimeError('Upstream did not publish an asset SHA256')
    flags_url = UPSTREAM.replace('github.com', 'raw.githubusercontent.com') + '/' + release['tag_name'] + '/flags.linux.gn'
    flags = debian.fetch(flags_url)
    if not re.search(rb'^use_vaapi\s*=\s*true\s*$', flags, re.M):
        raise RuntimeError('Ungoogled Chromium no longer enables VA-API')
    lock = {'format': 1, 'abi': 'glibc', 'architecture': 'arm64', 'browsers': {
        'chromium': {'version': version, 'publisher': 'Debian', 'vaapi': True,
            'archives': archives, 'directory': 'usr/lib/chromium', 'binary': 'chromium',
            'source': {'url': source_url, 'sha256': hashlib.sha256(source).hexdigest()}},
        'ungoogled-chromium': {'version': release['tag_name'], 'publisher': 'ungoogled-software', 'vaapi': True,
            'archives': [{'url': asset['browser_download_url'], 'sha256': digest[7:],
                          'size': asset['size'], 'kind': 'tar'}],
            'directory': asset['name'].removesuffix('.tar.xz'), 'binary': 'chrome',
            'source': {'url': flags_url, 'sha256': hashlib.sha256(flags).hexdigest()}}
    }}
    (DEST / 'chromium-prebuilt.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    print('Pinned Debian Chromium', version, 'and ungoogled Chromium', release['tag_name'])


if __name__ == '__main__':
    main()
