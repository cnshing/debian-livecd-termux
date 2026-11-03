#!/data/data/com.termux/files/usr/bin/python
"""Install GPU rendering and hardware video for Google Chrome, without PRoot.

Bionilux and Termux:VA are built here from pinned commits, and Mesa and its libraries
come from hash-pinned archives. See docs/browsers/native-gpu-and-video.md.
Nothing changes for Chrome until its launcher finds all of this and the Mutter fix.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PREFIX = Path(os.environ['PREFIX'])
CHROME = PREFIX / 'opt/google/chrome'
GPU = CHROME / 'gpu'
BIONILUX = ('https://github.com/theonuverse/bionilux', '4152b476db31ffa8e2bb50b060292a59e15d0031')
TERMUX_VA = ('https://github.com/lfdevs/termux-va', 'ae14813d77dbf107273b410a32f4ade34ba56313')
MESA_VERSION = '27.0.0-devel-20261025'
MESA_SHA256 = 'b711d1d9ab5537ee9085da8896dfe2115e791b33aa317fe37538f276c967d687'
MESA_URL = ('https://github.com/lfdevs/mesa-for-android-container/releases/download/'
    f'mesa-{MESA_VERSION}/mesa-for-android-container_{MESA_VERSION}_debian_trixie_arm64.tar.gz')
# A Bionic launcher must never find these, and libpci exits the process that loads it on Android.
FORBIDDEN = ('libc.so', 'libc.so.6', 'libdl.so', 'libm.so', 'libpci.so.3')

spec = importlib.util.spec_from_file_location('install_chrome', HERE / 'install-chrome.py')
install_chrome = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install_chrome)


def run(*command, **options):
    subprocess.run([str(part) for part in command], check=True, **options)


def checkout(repository, commit, directory):
    # Fetching by commit makes git verify the content against the pin.
    directory.mkdir()
    run('git', 'init', '-q', cwd=directory)
    run('git', 'fetch', '-q', '--depth', '1', repository, commit, cwd=directory)
    run('git', 'checkout', '-q', 'FETCH_HEAD', cwd=directory)


def install_bionilux(work):
    source = work / 'bionilux'
    checkout(*BIONILUX, source)
    run('patch', '--batch', '-p1', '-i', HERE / 'bionilux-0.5.0-browser.patch', cwd=source)
    run('bash', 'scripts/build-preload.sh', cwd=source)
    run('cargo', 'build', '--release', '--locked', cwd=source, env={**os.environ, 'CARGO_TARGET_DIR': str(work / 'target')})
    shutil.copy2(source / 'libbionilux_preload.so', PREFIX / 'glibc/lib/libbionilux_preload.so')
    shutil.copy2(work / 'target/release/bionilux', PREFIX / 'bin/bionilux')


def install_termux_va(work):
    source = work / 'termux-va'
    checkout(*TERMUX_VA, source)
    # API 29 is the release build's level, and exposes the MediaCodec calls it needs.
    compiler = ['clang', '--target=aarch64-linux-android29', '-O2', '-std=c11', '-Icommon']
    run(*compiler, 'daemon/termux-va.c', '-o', 'termux-va', '-lmediandk', '-llog', '-landroid', cwd=source)
    run(*compiler, 'tools/tva-probe.c', '-o', 'tva-probe', cwd=source)
    for name in ('termux-va', 'tva-probe'):
        shutil.copy2(source / name, PREFIX / 'bin' / name)
    for name in ('termux-va-start', 'termux-va-stop'):
        shutil.copy2(source / 'scripts' / (name + '.sh'), PREFIX / 'bin' / name)
        (PREFIX / 'bin' / name).chmod(0o755)


def libraries_needed(path):
    text = subprocess.run(['readelf', '-d', str(path)], capture_output=True, text=True, check=True).stdout
    return [line.split('[')[1].split(']')[0] for line in text.splitlines() if '(NEEDED)' in line]


def check_forbidden_libraries(*folders):
    for name in FORBIDDEN:
        for folder in folders:
            path = folder / name
            if path.exists() or path.is_symlink():
                raise RuntimeError(f'{name} must not be in the GPU library path: {folder}')


def stage_gpu(work):
    stage = work / 'gpu'
    (stage / 'mesa').mkdir(parents=True)
    (stage / 'lib').mkdir()
    archive = install_chrome.cached(MESA_URL, MESA_SHA256)
    run('tar', '-xzf', archive, '-C', stage / 'mesa')
    for item in json.loads((HERE / 'chrome-gpu-libs.lock.json').read_text()):
        unpacked = work / ('deb-' + item['package'])
        run('dpkg-deb', '-x', install_chrome.cached(item['url'], item['sha256']), unpacked)
        folder = unpacked / 'usr/lib/aarch64-linux-gnu'
        for path in folder.glob('*.so*') if folder.is_dir() else ():
            if path.is_symlink() or path.is_file():
                shutil.move(str(path), stage / 'lib' / path.name)
        shutil.rmtree(unpacked)
    mesa = stage / 'mesa/usr/lib/aarch64-linux-gnu'
    check_forbidden_libraries(mesa, stage / 'lib')
    # Prove the closure here: a missing library would otherwise only show as software video.
    found = {path.name for folder in (mesa, stage / 'lib', CHROME / 'lib', PREFIX / 'glibc/lib') for path in folder.glob('*.so*')}
    for root in ('libvulkan_freedreno.so', 'libgallium-27.0.0-devel.so', 'libgbm.so.1', 'libtva_drm_shim_wayland.so'):
        missing = sorted(set(libraries_needed(mesa / root)) - found)
        if missing:
            raise RuntimeError(f'{root} needs {missing}')
    for name in ('libva.so.2', 'libva-drm.so.2'):
        if name not in found:
            raise RuntimeError('Missing ' + name)
    # Upstream's manifest has an absolute /usr path. Its final location goes in here.
    icd = json.loads((stage / 'mesa/usr/share/vulkan/icd.d/freedreno_icd.aarch64.json').read_text())
    icd['ICD']['library_path'] = str(GPU / 'mesa/usr/lib/aarch64-linux-gnu/libvulkan_freedreno.so')
    (stage / 'freedreno_icd.json').write_text(json.dumps(icd, indent=2) + '\n')
    return stage


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
    work = Path(tempfile.mkdtemp(dir=CHROME.parent, prefix='.gpu-work-'))
    try:
        work.chmod(0o700)
        install_bionilux(work)
        install_termux_va(work)
        stage = stage_gpu(work)
        install_extension(work)
        if GPU.exists():
            GPU.rename(work / 'previous')
        stage.rename(GPU)
        # Bionilux itself would answer a --version that comes straight after the program.
        report = subprocess.run([PREFIX / 'bin/bionilux', CHROME / 'chrome', '--no-sandbox', '--version'],
            capture_output=True, text=True, check=True, timeout=60,
            env={**{k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')},
                'BIONILUX_LIBRARY_PATH': f'{GPU}/mesa/usr/lib/aarch64-linux-gnu:{GPU}/lib:{CHROME}/lib'}).stdout.strip()
        if 'Chrome' not in report:
            raise RuntimeError('Chrome did not start through Bionilux: ' + report)
        print('[Native video] ==> Chrome through Bionilux reports:', report, flush=True)
    finally:
        shutil.rmtree(work)
    common = HERE.parents[2] / 'prebuilt/native-video/setup.py'
    # General installs need a built adapter before selecting shared hardware
    # video. A manually applied pinned adapter can be migrated immediately.
    adapter = PREFIX / 'libexec/livecd-browser/liblivecd_tva_ion-bf39f8bd.so'
    if common.is_file() and adapter.is_file():
        # --glibc-compat adds the VA completion wait that hardware video needs to
        # present current frames; without it Chrome shows stale video after seeks.
        run('python', common, '--migrate-glibc', '--glibc-compat')
    print('[Native video] ==> Installed to', GPU)


if __name__ == '__main__':
    main()
