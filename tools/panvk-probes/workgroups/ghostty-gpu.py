#!/usr/bin/env python3
"""Launch the qualified experimental G77 Ghostty path without changing defaults."""
import hashlib
import json
import os
from pathlib import Path
import sys

HOME = Path.home()
STAGE = HOME / 'gpu-x1s/panvk/workgroups'
PREFIX = Path('/data/data/com.termux/files/usr')
sys.path.insert(0, str(HOME / '.local/lib/livecd-native'))


def environment():
    driver = STAGE / 'patched/libvulkan_panfrost.so'
    libraries = STAGE / 'mesa-102/lib'
    for path, expected in (
        (driver, '98658abb95344b8729645cc5b494b4cd59f0c1cad86226c6a0990aaee569c709'),
        (libraries / 'libgallium-26.2.6.so',
         'ac1c4b03ebc4c890689cf19ca1acefad504a91cd088d9a99ad620280ee1178b7'),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Unqualified experimental library: ' + str(path))
    # The private acceptance harness supplies its own session. Ordinary use
    # joins the controller's live session, including its actual D-Bus address.
    if os.environ.get('LIVECD_FULLSCREEN_TEST'):
        display = os.environ.get('DISPLAY', '')
        if not display.startswith(':') or not display[1:].isdigit() or not 74 <= int(display[1:]) < 100:
            raise RuntimeError('Invalid private test display')
        env = os.environ.copy()
    else:
        from desktop import session_environment
        env = session_environment('software')
    from graphics import apply_renderer
    env = apply_renderer(env, 'software')
    for key in ('LIBGL_ALWAYS_SOFTWARE', 'MESA_GL_VERSION_OVERRIDE',
                'MESA_GLSL_VERSION_OVERRIDE', 'PANVK_KBASE_DRI3'):
        env.pop(key, None)
    icd = STAGE / 'ghostty-icd.json'
    data = {'file_format_version': '1.0.0',
            'ICD': {'library_path': str(driver), 'api_version': '1.3.0'}}
    temporary = icd.with_suffix('.tmp-' + str(os.getpid()))
    temporary.write_text(json.dumps(data) + '\n')
    temporary.replace(icd)
    xlibs = STAGE.parent / 'android/xlibs'
    paths = [str(libraries), *([str(xlibs)] if xlibs.is_dir() else []),
             *(p for p in env.get('LD_LIBRARY_PATH', '').split(':')
               if p and p != str(PREFIX / 'lib') and p != str(libraries) and p != str(xlibs))]
    env.update(GALLIUM_DRIVER='zink', MESA_LOADER_DRIVER_OVERRIDE='zink',
        VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd),
        LIBGL_DRIVERS_PATH=str(libraries / 'dri'), LD_LIBRARY_PATH=':'.join(paths),
        PANVK_G77_LWG='1', MESA_SHADER_CACHE_DISABLE='true', GSK_RENDERER='cairo',
        LIVECD_NATIVE_RENDERER='panvk-experiment')
    return env


if __name__ == '__main__':
    binary = str(PREFIX / 'bin/ghostty')
    os.execve(binary, [binary, '--gtk-single-instance=false', *sys.argv[1:]], environment())
