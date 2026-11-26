"""Explicit native renderer selection, independent of the Debian GPU wrapper."""
import json
import os
from pathlib import Path

from panvk_device import qualified as qualified_mali

PREFIX = Path('/data/data/com.termux/files/usr')
GPU = Path.home() / '.local/opt/livecd-native/gpu'
ICD = GPU / 'share/vulkan/icd.d/freedreno_icd.aarch64.json'
# mesa-vulkan-icd-panvk-kbase: PanVK on Android's own Mali kernel driver, per ABI.
PANVK = PREFIX / 'lib/panvk-kbase'
# mesa-vulkan-icd-freedreno-android: Turnip built for Android and X11, for the Adreno desktop
# session on Termux:X11 only (TU_KGSL_DRI3=ahb). Everything else keeps the Termux Turnip.
TURNIP_AHB = PREFIX / 'lib/freedreno-android'
# Qualified Android Turnip builds by Mesa content tree (docs/native/handoff/note10-turnip-ahb-present.md).
QUALIFIED_TURNIP_TREES = {'432f482ad4a49e5f3f8378fe10efa6eca0437fdc'}


def mali_usable():
    return os.access('/dev/mali0', os.R_OK | os.W_OK)


def panvk(abi):
    """The packaged PanVK ICD for a Bionic or glibc process, if this phone's Mali GPU is usable."""
    icd = PANVK / abi / 'panfrost_icd.json'
    return icd if icd.is_file() and mali_usable() else None


# Qualified PanVK desktop builds by Mesa content tree, and whether each presents through
# Android hardware buffers (PANVK_KBASE_DRI3=ahb) rather than MIT-SHM.
QUALIFIED_TREES = {
    'b28956ffc095bda26bf8241badba014be178536b': False,
    '7c6284194b4a6a5df1575848aeeb7ec771fc82f7': True,
}


def desktop_tree():
    if not qualified_mali():
        return None
    try:
        manifest = json.loads((PREFIX / 'share/doc/mesa-vulkan-icd-panvk-kbase/SOURCE.json').read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get('variant') != 'combined-ahb':
        return None
    tree = manifest.get('mesa_tree')
    return tree if tree in QUALIFIED_TREES else None


def qualified_desktop_stack():
    return desktop_tree() is not None


def config():
    path = Path.home() / '.local/lib/livecd/config.json'
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def ahb_presentation():
    """Whether the installed Bionic PanVK presents through AHBs, unless the user chose MIT-SHM."""
    tree = desktop_tree()
    if not tree or not QUALIFIED_TREES[tree]:
        return False
    return config().get('panvk_presentation', 'ahb') != 'shm'


def turnip_ahb():
    """The qualified Android Turnip ICD, unless the user chose the Termux Turnip's raw DRI3."""
    icd = TURNIP_AHB / 'freedreno_icd.json'
    if not icd.is_file() or not os.access('/dev/kgsl-3d0', os.R_OK | os.W_OK):
        return None
    try:
        manifest = json.loads((PREFIX / 'share/doc/mesa-vulkan-icd-freedreno-android/SOURCE.json').read_text())
    except (OSError, ValueError):
        return None
    if (not isinstance(manifest, dict) or manifest.get('variant') != 'turnip-ahb' or
            manifest.get('mesa_tree') not in QUALIFIED_TURNIP_TREES):
        return None
    return icd if config().get('turnip_presentation', 'ahb') != 'raw' else None


def session_presentation(env):
    """AHB presentation needs Termux:X11's socket import, so only the session on its display gets it.
    Launchers that call apply_renderer again (browsers, mpv) drop it."""
    driver = env.get('LIVECD_NATIVE_VULKAN_DRIVER')
    if driver == 'panvk' and ahb_presentation():
        env['PANVK_KBASE_DRI3'] = 'ahb'
    elif driver == 'turnip' and (icd := turnip_ahb()):
        icd_library(icd, TURNIP_AHB)
        env.update(VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd), TU_KGSL_DRI3='ahb')
        android_libraries(env, TURNIP_AHB / 'x11')
    return env


def use_panvk(env, abi):
    """Make PanVK the only Vulkan driver a process sees, with the libraries it loads."""
    icd = panvk(abi)
    if icd is None:
        raise RuntimeError('Install mesa-vulkan-icd-panvk-kbase and check access to /dev/mali0')
    icd_library(icd, PANVK / abi)
    env.update(VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd))
    # Browsers keep their qualified MIT-SHM presentation, and the glibc build has no
    # Android WSI at all; session_presentation opts the desktop session in afterwards.
    env.pop('PANVK_KBASE_DRI3', None)
    if qualified_desktop_stack():
        env.setdefault('PANVK_G77_LWG', '1')
        env.setdefault('PANVK_G77_NESTED', env['PANVK_G77_LWG'])
    # Bionic: versioned names for Termux's X11 libraries. glibc: newer xcb/Wayland
    # than Chrome bundles, so they must come first.
    if abi == 'bionic':
        android_libraries(env, icd.parent / 'x11')
    else:
        inherited = env.get('BIONILUX_LIBRARY_PATH', '').split(':')
        env['BIONILUX_LIBRARY_PATH'] = ':'.join(filter(None, [str(icd.parent / 'lib'), *inherited]))


def android_libraries(env, directory):
    """Libraries for a driver built for Android: versioned X11 sonames first, and no $PREFIX/lib.
    The desktop session names $PREFIX/lib, where libandroid-stub's libbinder_ndk.so would shadow
    Android's: the driver's libnativewindow -> /system/lib64/libui.so then fails to load. Termux
    programs find $PREFIX/lib through their RUNPATH anyway."""
    inherited = [p for p in env.get('LD_LIBRARY_PATH', '').split(':')
                 if p and Path(p).resolve() != (PREFIX / 'lib').resolve()]
    env['LD_LIBRARY_PATH'] = ':'.join([str(directory), *inherited])


def icd_library(icd, root):
    try:
        library = Path(json.loads(icd.read_text())['ICD']['library_path'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Invalid native Vulkan ICD: ' + str(icd)) from error
    library = (library if library.is_absolute() else icd.parent / library).resolve()
    if not library.is_file() or not library.is_relative_to(root.resolve()):
        raise RuntimeError('Invalid native Vulkan driver path: ' + str(library))
    return library


def zink_driver():
    # Preserve the Turnip path on Qualcomm; Mali uses the packaged kbase ICD.
    if mali_usable() and not os.access('/dev/kgsl-3d0', os.R_OK | os.W_OK):
        return 'panvk'
    return 'turnip'


def legacy_drawing(renderer):
    # Termux:X11 still samples flipped AHB frames on the GPU in legacy drawing; only the
    # fd-backed root is uploaded. PanVK uses MIT-SHM or AHB presentation, never raw DRI3.
    return renderer == 'software' or zink_driver() == 'panvk'


def process_gpu(pid):
    """Inspect the actual process, rather than inferring GPU use from its launcher."""
    proc = Path('/proc') / str(pid)
    maps = (proc / 'maps').read_text(errors='replace').splitlines()
    turnip = sorted({line.split()[-1] for line in maps if 'libvulkan_freedreno.so' in line})
    panfrost = sorted({line.split()[-1] for line in maps if 'libvulkan_panfrost.so' in line})
    devices = []
    for path in (proc / 'fd').iterdir():
        try:
            target = os.readlink(path)
            if target in ('/dev/kgsl-3d0', '/dev/mali0'):
                devices.append({'fd': int(path.name), 'path': target})
        except OSError:
            pass
    kgsl = [fd for fd in devices if fd['path'] == '/dev/kgsl-3d0']
    mali = [fd for fd in devices if fd['path'] == '/dev/mali0']
    driver = 'panvk' if panfrost and mali else 'turnip' if turnip and kgsl else None
    return {'pid': pid, 'driver': driver, 'libraries': sorted(turnip + panfrost),
            'devices': devices, 'turnip_libraries': turnip, 'kgsl_devices': kgsl,
            'panvk_libraries': panfrost, 'mali_devices': mali}


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
                'vblank_mode', 'MESA_VK_WSI_PRESENT_MODE', 'MESA_VK_WSI_DEBUG', 'COGL_DRIVER',
                'PANVK_KBASE_DRI3', 'TU_KGSL_DRI3', 'LIVECD_NATIVE_VULKAN_DRIVER'):
        env.pop(key, None)
    env['LIVECD_NATIVE_RENDERER'] = renderer
    if renderer == 'software':
        env.update(LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe',
                   MESA_LOADER_DRIVER_OVERRIDE='swrast', GSK_RENDERER='cairo')
        software_icd = PREFIX / 'share/vulkan/icd.d/lvp_icd.aarch64.json'
        if software_icd.is_file():
            env['VK_DRIVER_FILES'] = str(software_icd)
    else:
        driver = zink_driver()
        if driver == 'panvk':
            use_panvk(env, 'bionic')
        else:
            if not ICD.is_file():
                raise RuntimeError('Install the native GPU profile with python prebuilt/turnip/gpu-setup.py first')
            icd_library(ICD, GPU)
            env.update(VK_DRIVER_FILES=str(ICD), VK_ICD_FILENAMES=str(ICD))
        env.update(GALLIUM_DRIVER='zink', MESA_LOADER_DRIVER_OVERRIDE='zink',
                   LIVECD_NATIVE_VULKAN_DRIVER=driver, GSK_RENDERER='gl',
                   COGL_DRIVER='gles2')
    return env
