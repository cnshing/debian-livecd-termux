#!/data/data/com.termux/files/usr/bin/python
"""Install shared acceleration profiles and activate immutable driver directories.

Only new private driver files and launchers are installed. No browser, decoder,
desktop or GPU probe is launched. Existing application processes keep their files.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PREFIX = Path('/data/data/com.termux/files/usr')
BASE = Path.home() / '.local/lib/livecd-native'
ROOT = (Path.home() / '.local/opt/livecd-native/acceleration').resolve()
CONFIG = Path.home() / '.config/livecd-native/acceleration.json'
ION_SHA256 = 'bf39f8bd5a0e3f9abfa6453f2878abdd96693d4005fb7d1caf5c2998e902ac2d'


def atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def select(abi, destination, selector_name=None):
    manifest = json.loads((destination / 'manifest.json').read_text())
    if manifest['abi'] != abi or manifest['format'] != 1 or destination.parent != ROOT:
        raise RuntimeError('Invalid private driver manifest: ' + str(destination))
    selector_name = selector_name or abi
    selector = ROOT / selector_name
    if selector.exists() and not selector.is_symlink():
        raise RuntimeError('Refusing to replace an unmanaged directory: ' + str(selector))
    temporary = ROOT / (selector_name + '.next')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(destination.name)
    temporary.replace(selector)


def build_glibc_compat():
    sources = REPO / 'overlays/Browser+Chromium/browsers'
    names = ('bionilux-fortify', 'va-completion')
    hashes = {name: hashlib.sha256((sources / (name + '.c')).read_bytes()).hexdigest() for name in names}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    destination = ROOT / ('glibc-compat-' + fingerprint)
    if not (destination / 'manifest.json').is_file():
        with tempfile.TemporaryDirectory(prefix='.glibc-compat-', dir=ROOT) as temporary:
            stage = Path(temporary) / 'root'
            stage.mkdir()
            for name in names:
                subprocess.run(['clang', '--target=aarch64-linux-gnu', '--sysroot=' + str(PREFIX / 'glibc'),
                    '-isystem', str(PREFIX / 'glibc/include'), '-fuse-ld=lld', '-nostdlib',
                    '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(sources / (name + '.c')), '-o', str(stage / ('liblivecd-' + name + '.so'))], check=True)
                shutil.copy2(sources / (name + '.c'), stage / (name + '.c'))
            (stage / 'manifest.json').write_text(json.dumps({'format': 1, 'abi': 'glibc',
                'sources': hashes, 'tests_run': False, 'runtime_verified': False}, indent=2) + '\n')
            stage.rename(destination)
    return destination


def migrate_glibc():
    legacy = PREFIX / 'opt/google/chrome/gpu'
    support = PREFIX / 'opt/google/chrome/lib'
    adapter = PREFIX / 'libexec/livecd-browser/liblivecd_tva_ion-bf39f8bd.so'
    if not legacy.is_dir() or not support.is_dir() or not adapter.is_file():
        raise RuntimeError('Install the existing Chrome GPU stack and ION adapter before migrating glibc')
    if hashlib.sha256(adapter.read_bytes()).hexdigest() != ION_SHA256:
        raise RuntimeError('The ION adapter differs from the pinned applied binary')
    digest = hashlib.sha256()
    for directory in (legacy, support):
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                digest.update(str(path.relative_to(directory)).encode() + b'\0')
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(adapter.read_bytes())
    destination = ROOT / ('glibc-' + digest.hexdigest()[:16])
    if not (destination / 'manifest.json').is_file():
        with tempfile.TemporaryDirectory(prefix='.glibc-', dir=ROOT) as temporary:
            staging = Path(temporary) / 'root'
            shutil.copytree(legacy, staging / 'gpu', symlinks=True)
            shutil.copytree(support, staging / 'support-lib', symlinks=True)
            (staging / 'lib').mkdir()
            shutil.copy2(adapter, staging / 'lib' / adapter.name)
            mesa = 'gpu/mesa/usr/lib/aarch64-linux-gnu'
            for folder in (staging / mesa, staging / 'gpu/lib', staging / 'support-lib'):
                for name in ('libc.so', 'libc.so.6', 'libdl.so', 'libm.so', 'libpci.so.3'):
                    if (folder / name).exists() or (folder / name).is_symlink():
                        raise RuntimeError('Forbidden glibc stack library: ' + str(folder / name))
            icd = json.loads((staging / 'gpu/freedreno_icd.json').read_text())
            icd['ICD']['library_path'] = str(destination / mesa / 'libvulkan_freedreno.so')
            (staging / 'gpu/freedreno_icd.json').write_text(json.dumps(icd, indent=2) + '\n')
            manifest = {'format': 1, 'abi': 'glibc', 'source': 'immutable copy of applied Chrome stack',
                'libraries': [mesa, 'gpu/lib', 'support-lib'], 'driver_directory': mesa + '/dri',
                'mesa_library_directory': mesa, 'vulkan_icd': 'gpu/freedreno_icd.json',
                'preloads': [mesa + '/libtva_drm_shim_wayland.so', 'lib/' + adapter.name],
                'ion_fallback': 'preload', 'ion_sha256': ION_SHA256,
                'runtime_verified': False, 'tests_run': False}
            (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            if destination.exists():
                raise RuntimeError('Incomplete glibc destination exists: ' + str(destination))
            staging.rename(destination)
    return destination


def build_service():
    pins = json.loads((HERE / 'daemon.lock.json').read_text())
    patches = sorted((HERE / 'daemon-patches').glob('*.patch'))
    digest = hashlib.sha256(json.dumps(pins, sort_keys=True).encode() +
                            b''.join(patch.read_bytes() for patch in patches)).hexdigest()
    # Keep the unpatched daemon's historical directory name.
    destination = ROOT / ('service-' + (pins['sha256'][:16] if not patches else digest[:16]))
    if (destination / 'manifest.json').is_file():
        return destination
    if destination.exists():
        raise RuntimeError('Incomplete service destination exists: ' + str(destination))
    cache = Path.home() / '.cache/livecd-native-video'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / ('daemon-' + pins['sha256'][:16] + '.tar.gz')
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != pins['sha256']:
        with urllib.request.urlopen(pins['url']) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != pins['sha256']:
            raise RuntimeError('Daemon source checksum mismatch')
        atomic(archive, data)
    with tempfile.TemporaryDirectory(prefix='service-build-', dir=cache) as temporary:
        source = Path(temporary) / 'source'
        source.mkdir()
        with tarfile.open(archive) as contents:
            for member in contents.getmembers():
                parts = member.name.split('/', 1)
                if len(parts) == 2 and parts[1]:
                    member.name = parts[1]
                    contents.extract(member, source, filter='data')
        for patch in patches:
            subprocess.run(['patch', '--batch', '-p1'], cwd=source, input=patch.read_bytes(), check=True)
        output = Path(temporary) / 'runtime'
        (output / 'bin').mkdir(parents=True)
        command = ['clang', '--target=aarch64-linux-android29', '-O2', '-std=c11',
                   '-I' + str(source / 'common'), str(source / 'daemon/termux-va.c'),
                   '-o', str(output / 'bin/termux-va'), '-lmediandk', '-llog', '-landroid']
        clean = {k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')}
        subprocess.run(command, env=clean, check=True)
        shutil.copy2(source / 'LICENSE', output / 'LICENSE')
        (output / 'manifest.json').write_text(json.dumps({'format': 1, 'abi': 'bionic',
            'sources': pins, 'patches': {patch.name: hashlib.sha256(patch.read_bytes()).hexdigest()
                                         for patch in patches},
            'tests_run': False, 'runtime_verified': False}, indent=2) + '\n')
        output.rename(destination)
    return destination


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--migrate-glibc', action='store_true')
    p.add_argument('--glibc-compat', action='store_true', help='Build/select the small glibc browser synchronization and loader adapters')
    p.add_argument('--build-native', action='store_true')
    p.add_argument('--native-stack', type=Path)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--firefox-kgsl', action='store_true', help='Build/select the private native Firefox KGSL graphics probe port')
    p.add_argument('--firefox-ffmpeg', action='store_true', help='Build/select Firefox FFmpeg libraries with VA-API enabled')
    p.add_argument('--enable', action='store_true', help='Save hardware-video enablement for supported applications')
    p.add_argument('--native-encode', choices=('on', 'off'),
                   help='Offer the hardware encoder to every desktop program as /dev/dri/renderD128 from the next session')
    args = p.parse_args()
    if os.environ.get('PREFIX') != str(PREFIX):
        p.error('Run in native Termux')
    ROOT.mkdir(parents=True, exist_ok=True)
    if args.build_native:
        subprocess.run([sys.executable, str(HERE / 'build-native.py'), '--jobs', str(args.jobs)], check=True)
    native = args.native_stack
    if args.build_native and native is None:
        candidates = sorted(ROOT.glob('bionic-*/manifest.json'), key=lambda path: path.stat().st_mtime)
        if not candidates:
            raise RuntimeError('No complete native driver build')
        native = candidates[-1].parent
    selected = {}
    if args.migrate_glibc:
        selected['glibc'] = migrate_glibc()
    glibc_compat = build_glibc_compat() if args.glibc_compat else None
    if native:
        native = native.resolve()
        if native.parent != ROOT or not (native / 'manifest.json').is_file():
            raise RuntimeError('Native stack is not a complete private build')
        selected['bionic'] = native
    service = build_service()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path.home() / '.local/state/livecd-native/acceleration-backups' / stamp
    changes = {}
    def install(path, data, mode=0o600):
        if path.exists():
            original = path.read_bytes()
            if original == data:
                return
            old = backup / str(path).lstrip('/')
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, old)
        atomic(path, data, mode)
        changes[str(path)] = hashlib.sha256(data).hexdigest()
    install(BASE / 'acceleration.py', (REPO / 'src/native/acceleration.py').read_bytes())
    # Keep the native renderer implementation already supplied by setup.
    if not (BASE / 'graphics.py').is_file():
        install(BASE / 'graphics.py', (REPO / 'src/native/graphics.py').read_bytes())
    install(PREFIX / 'bin/livecd-accelerate', (f'#!{PREFIX}/bin/bash\nexec {PREFIX}/bin/python '
        '"$HOME/.local/lib/livecd-native/acceleration.py" "$@"\n').encode(), 0o755)
    for application in ('firefox', 'mpv'):
        if (PREFIX / 'bin' / application).is_file():
            install(BASE / 'bin' / application, (f'#!{PREFIX}/bin/bash\nexec {PREFIX}/bin/python '
                f'"$HOME/.local/lib/livecd-native/acceleration.py" run --profile {application} -- '
                f'{PREFIX}/bin/{application} "$@"\n').encode(), 0o700)
    if (PREFIX / 'opt/google/chrome/chrome').is_file():
        install(PREFIX / 'bin/google-chrome',
                (REPO / 'overlays/Browser+Chromium/browsers/google-chrome').read_bytes(), 0o755)
    if (PREFIX / 'bin/chromium-browser').is_file():
        install(PREFIX / 'etc/chromium/livecd-gpu.conf',
                (REPO / 'overlays/Browser+Chromium/browsers/chromium-gpu.conf').read_bytes(), 0o644)
    config = json.loads(CONFIG.read_text()) if CONFIG.is_file() else {}
    config.setdefault('format', 1)
    config.setdefault('hardware_video', False)
    config.setdefault('disabled_va_codecs', ['h264', 'av1'])
    if args.enable:
        config['hardware_video'] = True
    if args.native_encode:
        stack_manifest = json.loads(((selected.get('bionic') or ROOT / 'bionic').resolve() / 'manifest.json').read_text())
        if args.native_encode == 'on' and not stack_manifest.get('session_preload'):
            raise RuntimeError('The selected Bionic stack has no encoders; rebuild it with --build-native')
        config['native_encode'] = args.native_encode == 'on'
    config.setdefault('native_encode', False)
    # Desktop programs that find the device may also decode with it; that
    # stays a separate choice, as hardware decoding is opt-in.
    config.setdefault('native_decode', False)
    for abi, destination in selected.items():
        select(abi, destination)
    if glibc_compat:
        select('glibc', glibc_compat, 'glibc-compat')
    if args.firefox_kgsl:
        subprocess.run([sys.executable, str(HERE / 'setup-firefox.py')], check=True)
    if args.firefox_ffmpeg:
        subprocess.run([sys.executable, str(HERE / 'build-firefox-ffmpeg.py'), '--jobs', str(args.jobs)], check=True)
    service_next = ROOT / 'service.next'
    service_next.unlink(missing_ok=True)
    service_next.symlink_to(service.name)
    service_next.replace(ROOT / 'service')
    install(CONFIG, (json.dumps(config, indent=2) + '\n').encode())
    receipt = {'format': 1, 'files': changes, 'stacks': {k: str(v) for k, v in selected.items()},
               'service': str(service),
               'glibc_compat': str((ROOT / 'glibc-compat').resolve()) if (ROOT / 'glibc-compat').is_symlink() else None,
               'firefox_kgsl': str((ROOT / 'firefox').resolve()) if (ROOT / 'firefox').is_symlink() else None,
               'firefox_ffmpeg': str((ROOT / 'firefox-ffmpeg').resolve()) if (ROOT / 'firefox-ffmpeg').is_symlink() else None,
               'backup': str(backup), 'configuration': config, 'desktop_restarted': False,
               'applications_launched': False, 'tests_run': False}
    receipt_path = Path.home() / '.local/state/livecd-native/acceleration-install.json'
    atomic(receipt_path, (json.dumps(receipt, indent=2) + '\n').encode())
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
