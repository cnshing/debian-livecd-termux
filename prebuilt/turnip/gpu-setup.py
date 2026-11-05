#!/data/data/com.termux/files/usr/bin/python
"""Stage official Bionic Turnip/tools privately; leave shared Mesa under APT.

Turnip is taken at the installed Mesa's version, and vulkan-tools at its current version, from
Termux's signed APT index. Termux keeps only each package's newest release, so a fixed list of
versions stops downloading as soon as Termux moves on.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / 'src/native'), str(HERE.parent / 'gnome-runtime')]
from graphics import GPU, PREFIX


def main():
    if os.environ.get('PREFIX') != str(PREFIX) or subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip() != 'aarch64':
        raise RuntimeError('Run in native aarch64 com.termux')
    common = Path.home() / '.local/state/livecd'
    common.mkdir(parents=True, exist_ok=True)
    with (common / 'session.lock').open('a') as lock:
        try:
            # install.sh already holds the lock when it runs this.
            if not os.environ.get('LIVECD_SETUP_LOCKED'):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Stop the managed desktop before installing the GPU profile')
        dependencies = ['libandroid-shmem', 'libc++', 'libdrm', 'libx11', 'libxcb',
                        'libxshmfence', 'libwayland', 'vulkan-loader-generic', 'zlib', 'zstd']
        missing = []
        for name in dependencies:
            result = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}', name], capture_output=True, text=True)
            if result.returncode or result.stdout != 'installed':
                missing.append(name)
        if missing:
            raise RuntimeError('Install native dependencies first: pkg install ' + ' '.join(missing))
        if not (PREFIX / 'lib/dri/zink_dri.so').is_file():
            raise RuntimeError('The installed native Mesa must supply zink_dri.so')
        mesa = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'mesa'], text=True).strip()
        destination = GPU.with_name('gpu-' + mesa)
        if GPU.exists() and not GPU.is_symlink():
            raise RuntimeError('The private GPU selector is an unexpected directory')
        GPU.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='gpu-staging-', dir=GPU.parent) as temporary:
            staging = Path(temporary)
            downloads = staging / 'downloads'
            downloads.mkdir()
            # apt checks each file against the signed index. A missing Turnip build means Mesa
            # itself is older than Termux's current release.
            if subprocess.run(['apt-get', 'download', 'mesa-vulkan-icd-freedreno=' + mesa, 'vulkan-tools'],
                              cwd=downloads).returncode:
                raise RuntimeError('No Turnip build matches Mesa ' + mesa + '. Run pkg upgrade, then this again.')
            sources = {'format': 2, 'architecture': 'aarch64', 'mesa_version': mesa, 'packages': []}
            for archive in sorted(downloads.glob('*.deb')):
                fields = subprocess.check_output(['dpkg-deb', '-f', str(archive), 'Package', 'Version'], text=True)
                package, version = (line.split(': ', 1)[1] for line in fields.splitlines())
                sources['packages'].append({'package': package, 'version': version, 'file': archive.name,
                                            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})
                subprocess.run(['dpkg-deb', '-x', str(archive), str(staging / 'root')], check=True)
            staging = staging / 'root'
            prefix = staging / str(PREFIX).lstrip('/')
            icd = prefix / 'share/vulkan/icd.d/freedreno_icd.aarch64.json'
            data = json.loads(icd.read_text())
            data['ICD']['library_path'] = str(destination / 'lib/libvulkan_freedreno.so')
            icd.write_text(json.dumps(data, indent=2) + '\n')
            (prefix / 'sources.lock.json').write_text(json.dumps(sources, indent=2) + '\n')
            if destination.exists():
                shutil.rmtree(destination)
            prefix.replace(destination)
        selector = GPU.with_name('gpu.next')
        selector.unlink(missing_ok=True)
        selector.symlink_to(destination.name)
        selector.replace(GPU)
        print(json.dumps({'ok': True, 'driver': str(destination), 'sources': sources}, indent=2))


if __name__ == '__main__':
    main()
