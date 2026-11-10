#!/usr/bin/env python3
"""Stage the existing Mozilla probe port and its package-version guard."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def patch(source):
    path = source / 'glxtest.cpp'
    text = path.read_text()
    before = '''    if (deviceExtensions &&
        strstr(deviceExtensions, "EGL_MESA_device_software")) {'''
    after = '''    const char* kgsl = getenv("MOZ_DRM_DEVICE");
    int kgslFd = kgsl && !strcmp(kgsl, "/dev/kgsl-3d0") &&
        strstr((const char*)rendererString, "zink") &&
        strstr((const char*)rendererString, "Turnip Adreno")
        ? open(kgsl, O_RDWR | O_CLOEXEC) : -1;
    if (kgslFd >= 0) {
      close(kgslFd);
      record_value("MESA_ACCELERATED\\nTRUE\\nDRI_DRIVER\\nzink\\n");
      set_render_device_path(kgsl);
    } else if (deviceExtensions &&
        strstr(deviceExtensions, "EGL_MESA_device_software")) {'''
    if text.count(before) != 1:
        raise RuntimeError('Pinned Firefox GL probe changed')
    path.write_text(text.replace(before, after))


def install(prefix, destination):
    original = (prefix / 'bin/firefox').resolve().parent
    application = destination / 'application'
    application.mkdir(parents=True, exist_ok=True)
    # Copy only the small loader: /proc/self/exe must name this application
    # directory so Firefox finds the patched gfxtest. All other package assets
    # remain owned by Firefox and are shared through absolute symlinks.
    for path in original.iterdir():
        if path.name == 'gfxtest':
            continue
        target = application / path.name
        target.unlink(missing_ok=True)
        if path.name == 'firefox':
            shutil.copy2(path, target)
        else:
            target.symlink_to(path, target_is_directory=path.is_dir())
    library = destination / 'lib'
    library.mkdir(exist_ok=True)
    for name, alias in (('libgbm.so', 'libgbm.so.1'), ('libdrm.so', 'libdrm.so.2')):
        if not (prefix / 'lib' / name).is_file():
            raise RuntimeError('Missing probe dependency: ' + name)
        (library / alias).unlink(missing_ok=True)
        (library / alias).symlink_to(prefix / 'lib' / name)
    inputs = {key: hashlib.sha256((original / name).read_bytes()).hexdigest()
              for key, name in (('binary', 'firefox'), ('application_ini', 'application.ini'))}
    (destination / 'manifest.json').write_text(json.dumps({
        'format': 1, 'abi': 'bionic', 'inputs': inputs, 'runtime_verified': False,
    }, indent=2) + '\n')
    (destination / 'ffmpeg/manifest.json').write_text(json.dumps({
        'format': 1, 'abi': 'bionic', 'runtime_verified': False,
    }, indent=2) + '\n')


if __name__ == '__main__':
    if sys.argv[1] == 'patch':
        patch(Path(sys.argv[2]))
    elif sys.argv[1] == 'install':
        install(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit('Expected patch or install')
