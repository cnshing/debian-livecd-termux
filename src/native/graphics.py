"""Explicit native renderer selection, independent of the Debian GPU wrapper."""
import json
import os
from pathlib import Path

PREFIX = Path('/data/data/com.termux/files/usr')
GPU = Path.home() / '.local/opt/livecd-native/gpu'
ICD = GPU / 'share/vulkan/icd.d/freedreno_icd.aarch64.json'
# mesa-vulkan-icd-panvk-kbase: PanVK on Android's own Mali kernel driver, per ABI.
PANVK = PREFIX / 'lib/panvk-kbase'


def mali_usable():
    return os.access('/dev/mali0', os.R_OK | os.W_OK)


def panvk(abi):
    """The packaged PanVK ICD for a Bionic or glibc process, if this phone's Mali GPU is usable."""
    icd = PANVK / abi / 'panfrost_icd.json'
    return icd if icd.is_file() and mali_usable() else None


def use_panvk(env, abi):
    """Make PanVK the only Vulkan driver a process sees, with the libraries it loads."""
    icd = panvk(abi)
    env.update(VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd))
    # Bionic: versioned names for Termux's X11 libraries. glibc: newer xcb/Wayland
    # than Chrome bundles, so they must come first.
    key, directory = (('LD_LIBRARY_PATH', icd.parent / 'x11') if abi == 'bionic'
                      else ('BIONILUX_LIBRARY_PATH', icd.parent / 'lib'))
    inherited = env.get(key, '').split(':')
    if abi == 'bionic':
        # The desktop session names $PREFIX/lib, where libandroid-stub's libbinder_ndk.so
        # would shadow Android's: the driver's libnativewindow -> /system/lib64/libui.so then
        # fails to load. Termux programs find $PREFIX/lib through their RUNPATH anyway.
        inherited = [p for p in inherited if p and Path(p).resolve() != (PREFIX / 'lib').resolve()]
    env[key] = ':'.join(filter(None, [str(directory), *inherited]))


def process_gpu(pid):
    """Inspect the actual process, rather than inferring GPU use from its launcher."""
    proc = Path('/proc') / str(pid)
    drivers = sorted({line.split()[-1] for line in (proc / 'maps').read_text().splitlines()
                      if 'libvulkan_freedreno.so' in line})
    devices = []
    for path in (proc / 'fd').iterdir():
        try:
            target = os.readlink(path)
            if target == '/dev/kgsl-3d0':
                devices.append({'fd': int(path.name), 'path': target})
        except OSError:
            pass
    return {'pid': pid, 'turnip_libraries': drivers, 'kgsl_devices': devices}


def preferred_renderer():
    path = Path.home() / '.local/lib/livecd/config.json'
    renderer = json.loads(path.read_text()).get('native_renderer', 'software') if path.exists() else 'software'
    if renderer not in ('software', 'zink'):
        raise ValueError('Unknown saved native renderer: ' + str(renderer))
    return renderer


def apply_renderer(env, renderer):
    if renderer not in ('software', 'zink'):
        raise ValueError('Unknown native renderer: ' + str(renderer))
    # Prevent an inherited desktop/experiment from changing the selected mode.
    for key in ('LIBGL_ALWAYS_SOFTWARE', 'LIBGL_ALWAYS_INDIRECT', 'GALLIUM_DRIVER',
                'MESA_LOADER_DRIVER_OVERRIDE', 'VK_DRIVER_FILES', 'VK_ICD_FILENAMES',
                'LIBGL_KOPPER_DISABLE', 'LIBGL_KOPPER_DRI2', 'ZINK_DEBUG',
                'ZINK_DESCRIPTORS', 'TU_DEBUG', 'DRI_PRIME', 'MESA_VK_DEVICE_SELECT',
                'vblank_mode', 'MESA_VK_WSI_PRESENT_MODE', 'MESA_VK_WSI_DEBUG', 'COGL_DRIVER'):
        env.pop(key, None)
    env['LIVECD_NATIVE_RENDERER'] = renderer
    if renderer == 'software':
        env.update(LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe',
                   MESA_LOADER_DRIVER_OVERRIDE='swrast', GSK_RENDERER='cairo')
        software_icd = PREFIX / 'share/vulkan/icd.d/lvp_icd.aarch64.json'
        if software_icd.is_file():
            env['VK_DRIVER_FILES'] = str(software_icd)
    else:
        if not ICD.is_file():
            raise RuntimeError('Install the native GPU profile with python prebuilt/turnip/gpu-setup.py first')
        driver = Path(json.loads(ICD.read_text())['ICD']['library_path'])
        if not driver.is_file() or not driver.is_relative_to(GPU.resolve()):
            raise RuntimeError('Invalid private native Turnip driver path')
        env.update(GALLIUM_DRIVER='zink', MESA_LOADER_DRIVER_OVERRIDE='zink',
                   VK_DRIVER_FILES=str(ICD), VK_ICD_FILENAMES=str(ICD), GSK_RENDERER='gl',
                   COGL_DRIVER='gles2')
    return env
