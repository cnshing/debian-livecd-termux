#!/data/data/com.termux/files/usr/bin/python
"""Finish GPU rendering and hardware video for Google Chrome, without PRoot.

Bionilux and the glibc GPU and video stack come from the bionilux and android-vaapi-glibc
packages. This adds the extension that steers YouTube to hardware codecs and checks that
Chrome starts through Bionilux. See docs/browsers/native-gpu-and-video.md.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PREFIX = Path(os.environ['PREFIX'])
CHROME = PREFIX / 'opt/google/chrome'
STACK = PREFIX / 'lib/android-vaapi-glibc'
# A Bionic launcher must never find these, and libpci exits the process that loads it on Android.
FORBIDDEN = ('libc.so', 'libc.so.6', 'libdl.so', 'libm.so', 'libpci.so.3')


def run(*command, **options):
    subprocess.run([str(part) for part in command], check=True, **options)


def check_forbidden_libraries(*folders):
    for name in FORBIDDEN:
        for folder in folders:
            path = folder / name
            if path.exists() or path.is_symlink():
                raise RuntimeError(f'{name} must not be in the GPU library path: {folder}')


def libraries_needed(path):
    """DT_NEEDED of a 64-bit little-endian ELF; Chrome's installation brings no readelf."""
    data = path.read_bytes()
    shoff, = struct.unpack_from('<Q', data, 0x28)
    shentsize, shnum = struct.unpack_from('<HH', data, 0x3a)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shentsize) for i in range(shnum)]
    needed = []
    for _, kind, _, _, offset, size, link, _, _, _ in sections:
        if kind != 6:  # SHT_DYNAMIC
            continue
        strings = sections[link][4]
        for tag, value in struct.iter_unpack('<qQ', data[offset:offset + size]):
            if tag == 0:
                break
            if tag == 1:  # DT_NEEDED
                needed.append(data[strings + value:data.index(b'\0', strings + value)].decode())
    return needed


def check_stack(libraries):
    """A missing library would otherwise only show as software video."""
    check_forbidden_libraries(*libraries)
    found = {path.name for folder in (*libraries, CHROME / 'lib', PREFIX / 'glibc/lib') for path in folder.glob('*.so*')}
    mesa = libraries[0]
    for root in ('libvulkan_freedreno.so', 'libgallium-27.0.0-devel.so', 'libgbm.so.1', 'libtva_drm_shim_wayland.so'):
        missing = sorted(set(libraries_needed(mesa / root)) - found)
        if missing:
            raise RuntimeError(f'{root} needs {missing}')
    for name in ('libva.so.2', 'libva-drm.so.2'):
        if name not in found:
            raise RuntimeError('Missing ' + name)


def install_extension(work):
    """Steer YouTube away from AV1, which this phone can only decode in software."""
    key = Path.home() / '.local/lib/livecd/hardware-video.pem'
    source = work / 'hardware-video'
    shutil.copytree(HERE / 'hardware-video', source)
    clean = {k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'DISPLAY')}
    command = [CHROME / 'chrome', '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
               f'--user-data-dir={work / "pack"}', f'--pack-extension={source}']
    if key.is_file():
        command.append(f'--pack-extension-key={key}')
    run(*command, env=clean, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    packed = work / 'hardware-video.crx'
    if not key.is_file():
        key.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(work / 'hardware-video.pem'), key)
        key.chmod(0o600)
    public = subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout', '-outform', 'DER'],
        capture_output=True, check=True).stdout
    identifier = hashlib.sha256(public).hexdigest()[:32].translate(str.maketrans('0123456789abcdef', 'abcdefghijklmnop'))
    extensions = CHROME / 'extensions'
    extensions.mkdir(exist_ok=True)
    shutil.copy2(packed, extensions / (identifier + '.crx'))
    (extensions / (identifier + '.json')).write_text(json.dumps(
        {'external_crx': str(extensions / (identifier + '.crx')), 'external_version': '1.0'}) + '\n')


def main():
    if not (CHROME / 'chrome').is_file():
        raise SystemExit('Install Google Chrome first: bash install.sh chrome')
    manifest = json.loads((STACK / 'manifest.json').read_text())
    check_stack([STACK / path for path in manifest['libraries']])
    work = Path(tempfile.mkdtemp(dir=CHROME.parent, prefix='.gpu-work-'))
    try:
        work.chmod(0o700)
        install_extension(work)
    finally:
        shutil.rmtree(work)
    # Bionilux itself would answer a --version that comes straight after the program.
    libraries = [str(STACK / path) for path in manifest['libraries']] + [str(CHROME / 'lib')]
    report = subprocess.run([PREFIX / 'bin/bionilux', CHROME / 'chrome', '--no-sandbox', '--version'],
        capture_output=True, text=True, check=True, timeout=60,
        env={**{k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')},
            'BIONILUX_LIBRARY_PATH': ':'.join(libraries)}).stdout.strip()
    if 'Chrome' not in report:
        raise RuntimeError('Chrome did not start through Bionilux: ' + report)
    print('[Native video] ==> Chrome through Bionilux reports:', report, flush=True)


if __name__ == '__main__':
    main()
