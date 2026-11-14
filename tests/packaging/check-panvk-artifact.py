#!/usr/bin/env python3
"""Verify both ABIs and provenance in the side-by-side source-built PanVK package."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile

NAME = 'mesa-vulkan-icd-panvk-kbase-source'
PREFIX = Path('data/data/com.termux/files/usr')
LOCK = Path(__file__).resolve().parents[2] / 'packages' / NAME / 'source.lock.json'


def check_tree(root, expected, name=NAME):
    stacks = {
        NAME: ('panvk-kbase-source', 'baseline'),
        'mesa-vulkan-icd-panvk-kbase-sync-fd': ('panvk-kbase-sync-fd', 'sync-fd'),
    }
    stack_name, variant = stacks[name]
    manifest = json.loads((root / PREFIX / 'share/doc' / name / 'SOURCE.json').read_text())
    if manifest != expected or manifest['variant'] != variant:
        raise RuntimeError('Unreviewed source provenance or incorrect driver variant')
    stack = root / PREFIX / 'lib' / stack_name
    for abi in ('bionic', 'glibc'):
        driver = stack / abi / 'libvulkan_panfrost.so'
        if hashlib.sha256(driver.read_bytes()).hexdigest() != manifest[abi + '_sha256']:
            raise RuntimeError('Packaged driver differs from pinned CI output: ' + abi)
        header = subprocess.check_output(['readelf', '-h', str(driver)], text=True)
        if 'AArch64' not in header or 'ELF64' not in header or 'DYN' not in header:
            raise RuntimeError('Not an ARM64 shared object: ' + abi)
        dynamic = subprocess.check_output(['readelf', '-d', str(driver)], text=True)
        search_paths = re.findall(r'Library (?:runpath|rpath): \[(.*?)\]', dynamic)
        # The Android build retains this relative linker-stub path. Preserve
        # baseline bytes, but reject every absolute CI path or other override.
        allowed = (['$ORIGIN/../../android_stub'] if abi == 'bionic' else
                   ['$ORIGIN'] if variant == 'sync-fd' else [])
        if search_paths and search_paths != allowed:
            raise RuntimeError('Unexpected driver runtime search path: ' + abi)
        if (root / PREFIX / 'lib/android_stub').exists():
            raise RuntimeError('Link-time Android stubs must not be packaged')
        libc = '[libc.so]' if abi == 'bionic' else '[libc.so.6]'
        if libc not in dynamic:
            raise RuntimeError('Wrong libc ABI: ' + abi)
        symbols = subprocess.check_output(['readelf', '--dyn-syms', '--wide', str(driver)], text=True)
        if 'vk_icdGetInstanceProcAddr' not in symbols:
            raise RuntimeError('Missing Vulkan loader entry point: ' + abi)
        icd = json.loads((stack / abi / 'panfrost_icd.json').read_text())
        if icd['ICD'] != {'library_path': '/' + str(PREFIX / 'lib' / stack_name / abi / driver.name),
                          'api_version': '1.3.363'}:
            raise RuntimeError('ICD selects another driver or raises the API version: ' + abi)
    for path in (stack / 'glibc/lib').iterdir():
        if path.name in ('libc.so', 'libc.so.6', 'libdl.so', 'libm.so', 'libstdc++.so.6'):
            raise RuntimeError('Forbidden bundled library: ' + path.name)
    if (root / PREFIX / 'lib/panvk-kbase').exists():
        raise RuntimeError('Candidate overwrites the installed release stack')


def check(directory, name=NAME):
    packages = [path for path in Path(directory).glob('*.deb')
                if subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip() == name]
    if len(packages) != 1:
        raise RuntimeError('Expected exactly one ' + name + ' package')
    with tempfile.TemporaryDirectory() as temporary:
        subprocess.run(['dpkg-deb', '-x', str(packages[0]), temporary], check=True)
        lock = LOCK.parent.parent / name / 'source.lock.json'
        check_tree(Path(temporary), json.loads(lock.read_text()), name)
    print('PASS: pinned source provenance, ARM64 Bionic/glibc drivers, private ICD paths, no absolute CI RUNPATH')


if __name__ == '__main__':
    check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else NAME)
