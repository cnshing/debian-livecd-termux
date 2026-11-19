"""Adreno (KGSL) upkeep at desktop start: the private Turnip copy and OpenCL through clvk.

install.sh stages the desktop's Turnip (prebuilt/turnip/gpu-setup.py) and installs clvk on
Adreno only. A phone that later upgrades Mesa, or the desktop controller, needs the same; the
desktop calls refresh() while it holds the session lock, before any session program starts.
Mali phones, and phones without /dev/kgsl-3d0, are never touched.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from graphics import GPU, PREFIX

KGSL = Path('/dev/kgsl-3d0')
OPENCL = ['ocl-icd', 'clvk', 'clinfo']
# Written once OpenCL was installed here, so a later removal by hand is respected.
OPENCL_DONE = Path.home() / '.local/state/livecd/opencl-installed'


def installed_version(package):
    result = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', package],
                            capture_output=True, text=True)
    status, _, version = result.stdout.partition(' ')
    return version if not result.returncode and status == 'installed' else None


def newer(version, than):
    return subprocess.run(['dpkg', '--compare-versions', version, 'gt', than]).returncode == 0


def staged_mesa():
    try:
        return json.loads((GPU / 'sources.lock.json').read_text())['mesa_version']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def stage_turnip(mesa):
    """Stage Turnip at Mesa's exact version, then switch the selector atomically. A copy of an
    older Mesa stays on disk for programs that still have it loaded."""
    destination = GPU.with_name('gpu-' + mesa)
    if GPU.exists() and not GPU.is_symlink():
        raise RuntimeError('The private GPU selector is an unexpected directory')
    GPU.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gpu-staging-', dir=GPU.parent) as temporary:
        staging = Path(temporary)
        downloads = staging / 'downloads'
        downloads.mkdir()
        # apt checks each file against the signed index. A missing Turnip build means Mesa
        # itself is older than the repository's current release.
        if subprocess.run(['apt-get', 'download', 'mesa-vulkan-icd-freedreno=' + mesa],
                          cwd=downloads).returncode:
            raise RuntimeError('No Turnip build matches Mesa ' + mesa + '. Run pkg upgrade, then this again.')
        # vulkan-tools (vulkaninfo, vkcube for the GPU checks) is fetched on its own: when the
        # installed version is no longer offered by any source, a failure here must not keep
        # the old Turnip selected. The previous copy's tools are carried over instead.
        tools = subprocess.run(['apt-get', 'download', 'vulkan-tools'], cwd=downloads).returncode == 0
        sources = {'format': 2, 'architecture': 'aarch64', 'mesa_version': mesa, 'packages': []}
        for archive in sorted(downloads.glob('*.deb')):
            fields = subprocess.check_output(['dpkg-deb', '-f', str(archive), 'Package', 'Version'], text=True)
            package, version = (line.split(': ', 1)[1] for line in fields.splitlines())
            sources['packages'].append({'package': package, 'version': version, 'file': archive.name,
                                        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})
            subprocess.run(['dpkg-deb', '-x', str(archive), str(staging / 'root')], check=True)
        prefix = staging / 'root' / str(PREFIX).lstrip('/')
        if not tools and (GPU / 'bin').is_dir():
            shutil.copytree(GPU / 'bin', prefix / 'bin', symlinks=True, dirs_exist_ok=True)
            sources['carried_over'] = ['vulkan-tools']
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
    return destination, sources


def refresh_turnip():
    """Re-stage Turnip when the installed Mesa is newer than the staged copy (Mesa upgraded
    after install.sh). Only a copy install.sh made is refreshed; failures keep the old one."""
    if not GPU.is_symlink():
        return None
    staged, mesa = staged_mesa(), installed_version('mesa')
    if not staged or not mesa or not newer(mesa, staged):
        return None
    destination, _ = stage_turnip(mesa)
    return destination


def install_opencl():
    """clvk runs OpenCL on Turnip. install.sh adds it on Adreno; phones set up before that get
    it once here. A failure (no network) is retried at the next start."""
    if OPENCL_DONE.exists():
        return False
    if all(installed_version(name) for name in OPENCL):
        OPENCL_DONE.parent.mkdir(parents=True, exist_ok=True)
        OPENCL_DONE.touch()
        return False
    result = subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', *OPENCL],
                            stdin=subprocess.DEVNULL, timeout=600,
                            # This process holds the session lock and no desktop runs yet.
                            env=dict(os.environ, LIVECD_SETUP_LOCKED='1'))
    if result.returncode:
        raise RuntimeError('apt-get could not install ' + ' '.join(OPENCL))
    OPENCL_DONE.parent.mkdir(parents=True, exist_ok=True)
    OPENCL_DONE.touch()
    return True


def refresh():
    if not KGSL.exists() or os.access('/dev/mali0', os.F_OK):
        return
    for step in (refresh_turnip, install_opencl):
        try:
            step()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            print('Adreno setup: ' + str(error), file=sys.stderr)
