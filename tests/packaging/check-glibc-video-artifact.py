#!/usr/bin/env python3
"""Reject glibc video packages with an incomplete or wrong-ABI Mali driver."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

PREFIX = Path('data/data/com.termux/files/usr')


def check(directory):
    packages = [path for path in Path(directory).glob('*.deb')
                if subprocess.check_output(['dpkg-deb', '-f', str(path), 'Package'], text=True).strip()
                == 'android-vaapi-glibc']
    if len(packages) != 1:
        raise RuntimeError('Expected exactly one android-vaapi-glibc package')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        subprocess.run(['dpkg-deb', '-x', str(packages[0]), str(root)], check=True)
        private = root / PREFIX / 'lib/android-vaapi-glibc'
        manifest = json.loads((private / 'manifest.json').read_text())
        if manifest['abi'] != 'glibc' or manifest['format'] != 1:
            raise RuntimeError('Wrong video stack ABI or manifest format')
        mali = manifest['mali']
        for value in [*manifest['libraries'], *manifest['preloads'],
                      *mali['libraries'], mali['driver_directory'], manifest['driver_directory']]:
            path = private / value
            if not path.exists() or not path.resolve().is_relative_to(private.resolve()):
                raise RuntimeError('Missing or external video stack path: ' + value)
        for folder in (manifest['driver_directory'], mali['driver_directory']):
            driver = private / folder / 'termuxva_drv_video.so'
            if not driver.is_file() or not driver.resolve().is_relative_to(private.resolve()):
                raise RuntimeError('Missing or external VA driver: ' + folder)
            header = subprocess.check_output(['readelf', '-h', str(driver)], text=True)
            if 'AArch64' not in header or 'ELF64' not in header:
                raise RuntimeError('VA driver is not ARM64: ' + folder)
            symbols = subprocess.check_output(['readelf', '-Ws', str(driver)], text=True)
            if '__vaDriverInit_' not in symbols:
                raise RuntimeError('Missing VA driver entry point: ' + folder)
        driver = private / mali['driver_directory'] / 'termuxva_drv_video.so'
        data = driver.read_bytes()
        for marker in (b'software backend on dma-buf surfaces', b'TERMUX_VA_SYNC_END_PICTURE',
                       b'TERMUX_VA_GALLIUM_DRIVER', b'TERMUX_VA_HEVC_REORDER_PICS'):
            if marker not in data:
                raise RuntimeError('Mali driver lacks ' + marker.decode())
        needed = subprocess.check_output(['readelf', '-d', str(driver)], text=True)
        if 'libc.so.6' not in needed or 'libc++_shared.so' in needed:
            raise RuntimeError('Mali driver does not target Debian glibc')
        for path in private.rglob('*'):
            if path.name in ('libc.so', 'libc.so.6', 'libdl.so', 'libm.so', 'libpci.so.3'):
                raise RuntimeError('Forbidden runtime library: ' + str(path))
    print('PASS: ARM64 glibc video drivers, Mali dma-buf winsys and completion support')


if __name__ == '__main__':
    check(sys.argv[1])
