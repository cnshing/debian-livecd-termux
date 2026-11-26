#!/usr/bin/env python3
"""Verify the Android Turnip package: the pinned CI binary, a private ICD and its X11 sonames."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

NAME = 'mesa-vulkan-icd-freedreno-android'
PREFIX = Path('data/data/com.termux/files/usr')
LOCK = Path(__file__).resolve().parents[2] / 'packages' / NAME / 'source.lock.json'


def check_tree(root, expected):
    manifest = json.loads((root / PREFIX / 'share/doc' / NAME / 'SOURCE.json').read_text())
    if manifest != expected or manifest['variant'] != 'turnip-ahb':
        raise RuntimeError('Unreviewed source provenance or incorrect driver variant')
    stack = root / PREFIX / 'lib/freedreno-android'
    driver = stack / 'libvulkan_freedreno.so'
    if hashlib.sha256(driver.read_bytes()).hexdigest() != manifest['android_sha256']:
        raise RuntimeError('Packaged driver differs from pinned CI output')
    dynamic = subprocess.check_output(['readelf', '-h', '-d', str(driver)], text=True)
    if 'AArch64' not in dynamic or '[libc.so]' not in dynamic or '[libnativewindow.so]' not in dynamic:
        raise RuntimeError('Not an ARM64 Android (Bionic) driver')
    if 'vk_icdGetInstanceProcAddr' not in subprocess.check_output(
            ['readelf', '--dyn-syms', '--wide', str(driver)], text=True):
        raise RuntimeError('Missing Vulkan loader entry point')
    icd = json.loads((stack / 'freedreno_icd.json').read_text())
    if icd['ICD']['library_path'] != '/' + str(PREFIX / 'lib/freedreno-android' / driver.name):
        raise RuntimeError('ICD selects another driver')
    links = {path.name: str(path.readlink()) for path in (stack / 'x11').iterdir()}
    if links.get('libxcb.so.1') != '../../libxcb.so' or not all(
            target.startswith('../../lib') and '/' not in target[6:] for target in links.values()):
        raise RuntimeError('X11 soname links leave $PREFIX/lib: ' + repr(links))
    if (root / PREFIX / 'share/vulkan').exists():
        raise RuntimeError('The Vulkan loader must not offer this driver to every program')


def check(directory):
    packages = [path for path in Path(directory).glob('*.deb')
                if subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip() == NAME]
    if len(packages) != 1:
        raise RuntimeError('Expected exactly one ' + NAME + ' package')
    with tempfile.TemporaryDirectory() as temporary:
        subprocess.run(['dpkg-deb', '-x', str(packages[0]), temporary], check=True)
        check_tree(Path(temporary), json.loads(LOCK.read_text()))
    print('PASS: pinned Android Turnip, private ICD, X11 sonames inside $PREFIX/lib')


if __name__ == '__main__':
    check(sys.argv[1])
