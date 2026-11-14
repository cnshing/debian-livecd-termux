#!/data/data/com.termux/files/usr/bin/python
"""Run the privately packaged, qualified Ghostty DMA-BUF stack."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys

PREFIX = Path('/data/data/com.termux/files/usr')
ROOT = Path(__file__).resolve().parents[1] / 'lib/ghostty-panvk-dmabuf'
CLEAR = ('LIBGL_ALWAYS_SOFTWARE', 'LIBGL_ALWAYS_INDIRECT', 'LIBGL_KOPPER_DISABLE',
         'ZINK_DEBUG', 'ZINK_DESCRIPTORS', 'TU_DEBUG', 'DRI_PRIME',
         'MESA_VK_DEVICE_SELECT', 'MESA_VK_WSI_PRESENT_MODE', 'MESA_VK_WSI_DEBUG',
         'MESA_GL_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE',
         'PANVK_KBASE_DRI3', 'PANVK_G77_NESTED', 'PAN_DEBUG', 'GDK_DEBUG',
         'COGL_DRIVER', 'LIVECD_NATIVE_VULKAN_DRIVER')


def verify(root=ROOT):
    manifest = json.loads((root / 'MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        path = root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Package file changed: ' + str(path))
    for name, target in manifest['links'].items():
        if os.readlink(root / name) != target:
            raise RuntimeError('Package link changed: ' + str(root / name))
        (root / name).resolve(strict=True)
    if (root / 'android_stub').exists():
        raise RuntimeError('Android link-time stubs must not be installed')
    return manifest


def check_device():
    device = subprocess.check_output(['/system/bin/getprop', 'ro.product.device'], text=True).strip()
    if platform.machine() != 'aarch64' or device != 'x1s' or not platform.release().startswith('4.19.87'):
        raise RuntimeError('This package is qualified only for x1s/aarch64/Linux 4.19.87')
    fd = os.open('/dev/mali0', os.O_RDWR | os.O_CLOEXEC)
    try:
        version = bytearray(4)
        fcntl.ioctl(fd, (3 << 30) | (4 << 16) | 0x8000, version, True)
        if struct.unpack('HH', version) != (11, 35):
            raise RuntimeError('This package requires the tested kbase JM 11.35 ABI')
    finally:
        os.close(fd)


def environment(original, root=ROOT, prefix=PREFIX):
    env = original.copy()
    for key in CLEAR:
        env.pop(key, None)
    private_paths = [str(root / p) for p in ('gtk', 'mesa', 'driver/bionic', 'x11')]
    inherited = [p for p in original.get('LD_LIBRARY_PATH', '').split(':')
                 if p and Path(p).resolve() != (prefix / 'lib').resolve()
                 and p not in private_paths]
    env.update(
        LD_LIBRARY_PATH=':'.join(private_paths + inherited),
        GALLIUM_DRIVER='zink', MESA_LOADER_DRIVER_OVERRIDE='zink',
        VK_DRIVER_FILES=str(root / 'icd.json'), VK_ICD_FILENAMES=str(root / 'icd.json'),
        LIBGL_DRIVERS_PATH=str(root / 'mesa/dri'),
        __EGL_VENDOR_LIBRARY_FILENAMES=str(root / 'egl-vendor.json'),
        __GLX_VENDOR_LIBRARY_NAME='mesa', GSK_RENDERER='gl', GDK_BACKEND='x11',
        PANVK_G77_LWG='1', ZINK_LINEAR_DMABUF_EXPORT='1',
        MESA_SHADER_CACHE_DISABLE='true',
        LIVECD_NATIVE_RENDERER='panvk-dmabuf')
    # Ghostty's --env affects terminal children, not Ghostty itself. Restore the
    # caller's environment there so an opt-in terminal does not opt in every app.
    changed = sorted(k for k in env.keys() | original.keys() if env.get(k) != original.get(k))
    child_args = ['--env=' + k + '=' + original.get(k, '') for k in changed]
    return env, child_args


def main():
    try:
        manifest = verify()
        check_device()
        if sys.argv[1:] == ['--check']:
            print(json.dumps({'ok': True, 'version': manifest['version'], 'root': str(ROOT)}))
            return
        if not os.environ.get('DISPLAY'):
            raise RuntimeError('Start an X11 desktop first and supply its DISPLAY/XAUTHORITY environment')
        env, child_args = environment(os.environ)
        binary = str(PREFIX / 'bin/ghostty')
        # Prepend options so -e and everything after it retain normal semantics.
        # Do not pass --gtk-single-instance=true: it can reuse a stock instance.
        options = sys.argv[1:sys.argv.index('-e') if '-e' in sys.argv else len(sys.argv)]
        if any(a.startswith('--gtk-single-instance') and a != '--gtk-single-instance=false' for a in options):
            raise RuntimeError('The opt-in launcher owns --gtk-single-instance=false')
        os.execve(binary, [binary, '--gtk-single-instance=false', *child_args, *sys.argv[1:]], env)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print('ghostty-panvk-dmabuf: ' + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
