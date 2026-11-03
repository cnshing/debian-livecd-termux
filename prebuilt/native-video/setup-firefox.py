#!/data/data/com.termux/files/usr/bin/python
"""Build the Firefox graphics probe's KGSL port in a private application copy."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
PREFIX = Path('/data/data/com.termux/files/usr')
ROOT = Path.home() / '.local/opt/livecd-native/acceleration'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if os.environ.get('PREFIX') != str(PREFIX):
        raise SystemExit('Run in native Termux')
    original = (PREFIX / 'bin/firefox').resolve().parent
    stack = (ROOT / 'bionic').resolve()
    pins = json.loads((HERE / 'firefox-probe.lock.json').read_text())
    inputs = {'binary': sha(original / 'firefox'), 'application_ini': sha(original / 'application.ini'),
              'gbm': sha(PREFIX / 'lib/libgbm.so'), 'drm': sha(PREFIX / 'lib/libdrm.so'),
              'builder': sha(Path(__file__).resolve()), 'probe': pins}
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
    destination = ROOT / ('firefox-' + digest)
    if not (destination / 'manifest.json').is_file():
        cache = Path.home() / '.cache/livecd-native-video/firefox-probe'
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='build-', dir=cache) as temporary:
            work = Path(temporary)
            source = work / 'src'
            (source / 'mozilla').mkdir(parents=True)
            for item in pins['files']:
                data = urllib.request.urlopen('https://raw.githubusercontent.com/mozilla-firefox/firefox/' +
                    pins['commit'] + '/' + item['path']).read()
                if hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise RuntimeError('Firefox probe source checksum mismatch: ' + item['path'])
                path = source / ('mozilla/GfxInfoUtils.h' if item['path'].endswith('GfxInfoUtils.h')
                                 else Path(item['path']).name)
                path.write_bytes(data)
            # A small standalone RAII guard supplies the only mfbt dependency.
            # The probe remains Mozilla's real GL/VA capability implementation.
            (source / 'mozilla/ScopeExit.h').write_text('''#pragma once
#include <utility>
namespace mozilla {
template<class F> class ExitGuard {
  F f;
public:
  explicit ExitGuard(F fn) : f(std::move(fn)) {}
  ExitGuard(const ExitGuard&) = delete;
  ~ExitGuard() { f(); }
};
template<class F> auto MakeScopeExit(F f) { return ExitGuard<F>(std::move(f)); }
}
''')
            # EGL labels the software X11 platform as a software device even
            # when its Zink renderer is backed by hardware Turnip. Only adapt
            # that exact renderer on an explicitly selected, accessible KGSL fd.
            path = source / 'glxtest.cpp'
            text = path.read_text()
            anchor = '''    if (deviceExtensions &&
        strstr(deviceExtensions, "EGL_MESA_device_software")) {'''
            replacement = '''    const char* kgsl = getenv("MOZ_DRM_DEVICE");
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
            if text.count(anchor) != 1:
                raise RuntimeError('Pinned Firefox GL probe changed')
            path.write_text(text.replace(anchor, replacement))
            runtime = work / 'runtime'
            application = runtime / 'application'
            # Keep a private package copy: Android denies application hard links.
            # Nothing in the installed package is modified in place.
            shutil.copytree(original, application, symlinks=True)
            (application / 'gfxtest').unlink()
            library = runtime / 'lib'
            library.mkdir()
            shutil.copy2(PREFIX / 'lib/libgbm.so', library / 'libgbm.so.1')
            shutil.copy2(PREFIX / 'lib/libdrm.so', library / 'libdrm.so.2')
            command = ['clang++', '--target=aarch64-linux-android29', '-std=c++17', '-O2',
                '-DMOZ_X11', '-DMOZ_ENABLE_VAAPI', '-I' + str(source),
                '-I' + str(stack / 'include'), '-I' + str(PREFIX / 'include/nspr'),
                str(source / 'gfxtest.cpp'), str(source / 'glxtest.cpp'), str(source / 'vaapitest.cpp'),
                '-L' + str(stack / 'lib/va-client'), '-Wl,-rpath,' + str(stack / 'lib/va-client'),
                '-lva', '-lX11', '-lXrandr', '-ldl', '-o', str(application / 'gfxtest')]
            subprocess.run(command, check=True, env={k:v for k,v in os.environ.items()
                if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')})
            (runtime / 'manifest.json').write_text(json.dumps({'format': 1, 'abi': 'bionic',
                'inputs': inputs, 'probe_sha256': sha(application / 'gfxtest'),
                'runtime_verified': False}, indent=2) + '\n')
            runtime.rename(destination)
    selector = ROOT / 'firefox.next'
    selector.unlink(missing_ok=True)
    selector.symlink_to(destination.name)
    selector.replace(ROOT / 'firefox')
    print('Selected private Firefox KGSL port:', destination, flush=True)


if __name__ == '__main__':
    main()
