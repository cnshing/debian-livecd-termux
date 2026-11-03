#!/data/data/com.termux/files/usr/bin/python
"""Build a private Bionic VA-API stack. Never replace the desktop's Mesa.

No browser, decoder, display or built executable is run. Meson uses a cross file
with needs_exe_wrapper=true, including when compiling on the target phone.

The stack also carries the render-node preload, which presents KGSL as
/dev/dri/renderD128 so programs find the encoder without settings, and the
sysfs folder it serves.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent
PREFIX = Path('/data/data/com.termux/files/usr')
BASE = Path.home() / '.local/opt/livecd-native/acceleration'
CACHE = Path.home() / '.cache/livecd-native-video'


def run(command, **kwargs):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def fetch(item, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        temporary = path.with_suffix('.download')
        with urllib.request.urlopen(item['url']) as source, temporary.open('wb') as out:
            shutil.copyfileobj(source, out)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('Archive checksum mismatch: ' + item['url'])
        temporary.replace(path)
    return path


def extract(archive, destination):
    destination.mkdir()
    with tarfile.open(archive) as contents:
        for member in contents.getmembers():
            parts = member.name.split('/', 1)
            if len(parts) == 2 and parts[1]:
                member.name = parts[1]
                contents.extract(member, destination, filter='data')


def replace(path, before, after):
    text = path.read_text()
    if text.count(before) != 1:
        raise RuntimeError('Pinned source context changed: ' + str(path))
    path.write_text(text.replace(before, after))


def write_render_node_sys(root):
    """The sysfs view of renderD128 that liblivecd-render-node.so serves for
    /sys/class/drm and /sys/dev/char/226:128: a platform device with its
    device-tree identity, as libdrm's drmGetDevice2 reads it on Arm SoCs.
    Plain directories, and only absolute links to readable real sysfs, so the
    C library's realpath() and programs that follow links themselves agree."""
    uevent = ('DRIVER=kgsl-3d0\nOF_NAME=qcom,kgsl-3d0\nOF_FULLNAME=/soc/qcom,kgsl-3d0@2c00000\n'
              'OF_COMPATIBLE_0=qcom,kgsl-3d0\nOF_COMPATIBLE_N=1\nMODALIAS=of:Nqcom,kgsl-3d0T(null)Cqcom,kgsl-3d0\n')
    for node in (root / 'class/drm/renderD128', root / 'dev/char/226:128'):
        (node / 'device/drm/renderD128').mkdir(parents=True)
        (node / 'dev').write_text('226:128\n')
        (node / 'uevent').write_text('MAJOR=226\nMINOR=128\nDEVNAME=dri/renderD128\nDEVTYPE=drm_minor\n')
        (node / 'device/uevent').write_text(uevent)
        (node / 'device/subsystem').symlink_to('/sys/bus/platform')
        (node / 'device/drm/renderD128/dev').write_text('226:128\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jobs', type=int, default=2)
    args = p.parse_args()
    if os.environ.get('PREFIX') != str(PREFIX) or os.uname().machine != 'aarch64':
        p.error('Build in native aarch64 Termux')
    if args.jobs < 1:
        p.error('--jobs must be positive')
    for name in ('clang', 'clang++', 'ninja', 'pkg-config', 'patch', 'bison', 'flex', 'patchelf'):
        if not shutil.which(name):
            raise RuntimeError('Missing build tool: ' + name)
    pins = json.loads((HERE / 'sources.lock.json').read_text())
    inputs = [Path(__file__), HERE / 'sources.lock.json', HERE / 'tva_ion.h', HERE / 'livecd-render-node.c',
              *sorted((HERE / 'mesa-patches').glob('*.patch'))]
    fingerprint = hashlib.sha256(b''.join(p.read_bytes() for p in inputs)).hexdigest()[:16]
    destination = BASE / ('bionic-' + fingerprint)
    if (destination / 'manifest.json').is_file():
        print('Already built:', destination)
        return
    # A failed/incomplete build is never a selectable runtime.
    if destination.exists():
        raise RuntimeError('Incomplete destination exists: ' + str(destination))
    work = CACHE / ('build-' + fingerprint)
    work.mkdir(parents=True, exist_ok=True)
    stage = work / 'root'
    stage.mkdir(exist_ok=True)
    python = work / 'venv/bin/python'
    if not python.exists():
        run([sys.executable, '-m', 'venv', work / 'venv'])
        run([python, '-m', 'pip', 'install', *pins['build_python']])
    meson = [python, '-m', 'mesonbuild.mesonmain']
    cross = work / 'termux.ini'
    cross.write_text("""[binaries]
c = ['clang', '--target=aarch64-linux-android29']
cpp = ['clang++', '--target=aarch64-linux-android29']
ar = 'llvm-ar'
strip = 'llvm-strip'
pkg-config = 'pkg-config'
[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'
[properties]
needs_exe_wrapper = true
[built-in options]
c_args = ['-D__TERMUX__', '-D__USE_GNU']
cpp_args = ['-D__TERMUX__', '-D__USE_GNU']
c_link_args = ['-landroid-shmem']
cpp_link_args = ['-landroid-shmem']
""")
    env = {k: v for k, v in os.environ.items() if k not in (
        'LD_LIBRARY_PATH', 'LD_PRELOAD', 'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS',
        'PKG_CONFIG_PATH', 'PKG_CONFIG_LIBDIR', 'PKG_CONFIG_SYSROOT_DIR')}
    env['PATH'] = str(python.parent) + ':' + env['PATH']
    # Source generators use /usr/bin/env shebangs. Keep only Termux's path
    # compatibility preload, never the desktop's resource or video preloads.
    termux_exec = PREFIX / 'lib/libtermux-exec.so'
    if termux_exec.is_file():
        env['LD_PRELOAD'] = str(termux_exec)
    env['PYTHONUNBUFFERED'] = '1'
    for name in ('libva', 'mesa'):
        source = work / name
        if not source.exists():
            extract(fetch(pins[name], name + '-' + pins[name]['sha256'][:16] + '.tar.gz'), source)
        if name == 'mesa' and not (source / '.livecd-prepared').exists():
            for patch in sorted((HERE / 'mesa-patches').glob('*.patch')):
                text = patch.read_text().replace('@TERMUX_PREFIX@', str(PREFIX))
                subprocess.run(['patch', '--batch', '-p1'], cwd=source, input=text, text=True, check=True)
            bridge = source / 'src/gallium/frontends/va/tva_bridge.c'
            shutil.copy2(HERE / 'tva_ion.h', bridge.with_name('tva_ion.h'))
            replace(bridge, '#include <linux/dma-heap.h>', '#include <linux/dma-heap.h>\n#include "tva_ion.h"')
            replace(bridge, 'if (heap_fd < 0)\n      return -1;',
                    'if (heap_fd < 0)\n      return errno == ENOENT ? livecd_tva_alloc_ion(size) : -1;')
            (source / '.livecd-prepared').touch()
        build = work / (name + '-build')
        options = ['-Dwith_x11=yes', '-Dwith_wayland=no', '-Dwith_glx=no', '-Denable_docs=false',
                   '-Ddriverdir=' + str(destination / 'lib/dri')] if name == 'libva' else [
            '-Dauto_features=disabled', '-Dplatforms=x11,wayland',
            '-Dgallium-drivers=freedreno,zink,softpipe', '-Dvulkan-drivers=', '-Dfreedreno-kmds=msm,kgsl',
            '-Dgallium-va=enabled', '-Dtermux-va-bridge=enabled', '-Dtermux-va-wayland-shim=enabled',
            '-Dvideo-codecs=h264dec,h265dec,vp9dec,av1dec,h264enc,h265enc', '-Dllvm=disabled',
            '-Ddraw-use-llvm=false',
            '-Dgallium-rusticl=false', '-Dglx=disabled', '-Degl=enabled', '-Dgles1=disabled',
            '-Dgles2=enabled', '-Dopengl=true', '-Dgbm=enabled', '-Dglvnd=disabled',
            '-Dxmlconfig=disabled', '-Dbuild-tests=false', '-Denable-glcpp-tests=false',
            '-Dtools=', '-Dprecomp-compiler=auto', '-Dmesa-clc=auto', '-Dspirv-tools=disabled']
        env['PKG_CONFIG_PATH'] = str(stage / 'lib/pkgconfig')
        if not (build / 'build.ninja').exists():
            run([*meson, 'setup', build, source, '--cross-file', cross, '--prefix', stage,
                 '--libdir=lib', '--buildtype=release', '--wrap-mode=nodownload', *options], env=env)
        run([*meson, 'compile', '-C', build, '-j', args.jobs], env=env)
        run([*meson, 'install', '-C', build, '--no-rebuild'], env=env)
    # Only these client libraries are added to an application's library search path.
    # Core GL/EGL/GBM remain under the existing native GPU profile.
    client = stage / 'lib/va-client'
    client.mkdir(exist_ok=True)
    for path in sorted((stage / 'lib').glob('libva*.so*')):
        path.rename(client / path.name)
    # Bionic looks up a library's dependencies only through that library's own
    # run path, so Termux's library directory must stay on it.
    for path in (stage / 'lib').rglob('*.so*'):
        if path.is_file() and not path.is_symlink():
            run(['patchelf', '--set-rpath', '$ORIGIN:$ORIGIN/..:' + str(PREFIX / 'lib'), path])
    # libva names a driver after the DRM device; the render node reports "kgsl".
    (stage / 'lib/dri/kgsl_drv_video.so').unlink(missing_ok=True)
    (stage / 'lib/dri/kgsl_drv_video.so').symlink_to('termuxva_drv_video.so')
    clean = {k: v for k, v in env.items() if k != 'LD_PRELOAD'}
    run(['clang', '--target=aarch64-linux-android29', '-O2', '-Wall', '-shared', '-fPIC', '-U_FORTIFY_SOURCE',
         '-o', stage / 'lib/liblivecd-render-node.so', HERE / 'livecd-render-node.c'], env=clean)
    shutil.rmtree(stage / 'lib/render-node-sys', ignore_errors=True)
    write_render_node_sys(stage / 'lib/render-node-sys')
    for path in (stage / 'lib/pkgconfig').glob('libva*.pc'):
        text = path.read_text().replace(str(stage), str(destination))
        path.write_text(re.sub(r'^libdir=.*$', 'libdir=' + str(destination / 'lib/va-client'), text, flags=re.M))
    required = ['lib/va-client/libva.so.2', 'lib/va-client/libva-drm.so.2',
                'lib/dri/termuxva_drv_video.so', 'lib/dri/kgsl_drv_video.so', 'lib/libtva_drm_shim_wayland.so',
                'lib/liblivecd-render-node.so']
    for name in required:
        if not (stage / name).is_file():
            raise RuntimeError('Build did not install ' + name)
    manifest = {'format': 1, 'abi': 'bionic', 'build': fingerprint, 'sources': pins,
                'libraries': ['lib/va-client'], 'driver_directory': 'lib/dri',
                'preloads': ['lib/libtva_drm_shim_wayland.so'], 'ion_fallback': 'built-in',
                'session_preload': 'lib/liblivecd-render-node.so', 'encoders': ['h264', 'hevc'],
                'runtime_verified': False, 'tests_run': False}
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    BASE.mkdir(parents=True, exist_ok=True)
    stage.rename(destination)
    print('Built, not activated:', destination, flush=True)


if __name__ == '__main__':
    main()
