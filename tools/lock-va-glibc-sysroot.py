#!/usr/bin/env python3
"""Pin the ARM64 Debian trixie sysroot for the private Mali VA driver.

Uses signed Debian indexes, then checks each downloaded package against their
SHA-256. Only the build sysroot receives libc and compiler development files;
none of these files is installed into Termux's runtime library search path.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location('chrome_locks', Path(__file__).with_name('lock-chrome-libs.py'))
locks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locks)

ROOTS = '''libc6-dev linux-libc-dev libstdc++-14-dev libgcc-14-dev
libdrm-dev libva-dev zlib1g-dev libzstd-dev libexpat1-dev libx11-dev
libx11-xcb-dev libxext-dev libxfixes-dev libxcb1-dev libxcb-dri3-dev
libxcb-present-dev libxcb-randr0-dev libxcb-sync-dev libxcb-xfixes0-dev
libxcb-shm0-dev libxcb-glx0-dev libxshmfence-dev libxrandr-dev
libwayland-dev libwayland-egl-backend-dev wayland-protocols x11proto-dev
xorg-sgml-doctools xtrans-dev'''.split()


def main():
    packages = {}
    for area, suite in locks.SUITES:
        for stanza in locks.verified_index(area, suite).split('\n\n'):
            fields = dict(re.findall(r'^([A-Za-z0-9-]+): (.*)$', stanza, re.M))
            if 'Package' in fields:
                packages[fields['Package']] = {**fields, 'area': area}
    selected, queue = {}, list(ROOTS)
    while queue:
        name = queue.pop()
        if name in selected:
            continue
        fields = packages[name]
        selected[name] = fields
        for entry in re.split(r',\s*', fields.get('Depends', '') + ',' + fields.get('Pre-Depends', '')):
            choices = [option.strip().split()[0].split(':')[0] for option in entry.split('|') if option.strip()]
            choice = next((name for name in choices if name in packages), None)
            if choice and (choice.startswith('lib') or choice in ROOTS or choice == 'zlib1g'):
                queue.append(choice)
    result = []
    for name, fields in sorted(selected.items()):
        url = locks.MIRROR + fields['area'] + '/' + fields['Filename']
        data = locks.fetch(url)
        if hashlib.sha256(data).hexdigest() != fields['SHA256']:
            raise RuntimeError('Hash mismatch: ' + url)
        result.append({'package': name, 'version': fields['Version'], 'url': url,
                       'sha256': fields['SHA256'], 'snapshot': locks.SNAPSHOT + hashlib.sha1(data).hexdigest() + '/' + url.rsplit('/', 1)[-1]})
    target = Path(__file__).resolve().parents[1] / 'packages/android-vaapi-glibc/sysroot.lock.json'
    target.write_text(json.dumps(result, indent=1) + '\n')
    print(f'{len(result)} build-only packages: {target}')


if __name__ == '__main__':
    main()
