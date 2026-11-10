#!/usr/bin/env python3
"""Check the packaged Firefox decoder ABI and Chromium's dlopen library names."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

PREFIX = Path('data/data/com.termux/files/usr')


def check(directory):
    wanted = {'android-firefox-video', 'android-vaapi', 'libva'}
    packages = {}
    for path in Path(directory).glob('*.deb'):
        name = subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip()
        if name in wanted:
            previous = packages.get(name)
            if previous is None or subprocess.run([
                    'dpkg', '--compare-versions',
                    subprocess.check_output(['dpkg-deb', '-f', str(path), 'Version'], text=True).strip(), 'gt',
                    subprocess.check_output(['dpkg-deb', '-f', str(previous), 'Version'], text=True).strip(),
                    ]).returncode == 0:
                packages[name] = path
    if set(packages) != wanted:
        raise RuntimeError('Missing browser video package artifacts: ' + ', '.join(wanted - packages.keys()))
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, package in packages.items():
            architecture = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Architecture'], text=True).strip()
            if architecture != 'aarch64':
                raise RuntimeError(name + ' is not aarch64')
            subprocess.run(['dpkg-deb', '-x', str(package), str(root)], check=True)
        prefix = root / PREFIX
        vaapi = prefix / 'lib/android-vaapi'
        manifest = json.loads((vaapi / 'manifest.json').read_text())
        if 'lib/va-client' not in manifest['libraries']:
            raise RuntimeError('Chromium cannot search the private libva ABI aliases')
        if not any(b'TERMUX_VA_SYNC_END_PICTURE' in library.read_bytes()
                   for library in vaapi.glob('libgallium*.so*') if library.is_file()):
            raise RuntimeError('Native VA-API driver lacks implicit-sync decode completion support')
        for name in ('libva', 'libva-drm', 'libva-x11'):
            alias = vaapi / 'lib/va-client' / (name + '.so.2')
            if not alias.is_symlink() or alias.resolve() != (prefix / 'lib' / (name + '.so')).resolve():
                raise RuntimeError('Missing or incorrect Chromium dlopen alias: ' + name + '.so.2')
            if not alias.is_file():
                raise RuntimeError('Broken libva ABI alias: ' + str(alias))
        firefox = prefix / 'lib/android-firefox-video'
        receipt = json.loads((firefox / 'manifest.json').read_text())
        if not all(key in receipt['inputs'] for key in ('binary', 'application_ini')):
            raise RuntimeError('Firefox package is missing its version guard')
        for name in ('firefox', 'gfxtest'):
            executable = firefox / 'application' / name
            if not executable.is_file() or executable.is_symlink():
                raise RuntimeError('Missing private Firefox executable: ' + name)
            headers = subprocess.check_output(['readelf', '-hl', str(executable)], text=True)
            if 'AArch64' not in headers or '/system/bin/linker64' not in headers:
                raise RuntimeError('Firefox helper is not a native aarch64 executable: ' + name)
        for name in ('libavcodec.so.63', 'libavutil.so.61'):
            library = firefox / 'ffmpeg/lib' / name
            if not library.is_file():
                raise RuntimeError('Missing Firefox decoder ABI: ' + name)
            dynamic = subprocess.check_output(['readelf', '-d', str(library)], text=True)
            if '(SONAME)' not in dynamic or '[' + name + ']' not in dynamic:
                raise RuntimeError('Incorrect Firefox decoder SONAME: ' + name)
        codec = subprocess.check_output(['readelf', '-d', str(firefox / 'ffmpeg/lib/libavcodec.so.63')], text=True)
        if '[libva.so]' not in codec:
            raise RuntimeError('Firefox decoder library is not linked to native VA-API')
    print('PASS: native Firefox helpers, decoder ABI and Chromium libva dlopen aliases')


if __name__ == '__main__':
    check(sys.argv[1])
