#!/data/data/com.termux/files/usr/bin/python
"""Device acceptance checks for the native profile, run on its session bus."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop import DATA, ROOT, PREFIX, SESSION_LOG_START, STATE, bus_call, process_identity, shell_pid
from graphics import process_gpu, zink_driver
from gi.repository import Gio


def main():
    checks = {}

    def check(name, result, detail=None):
        checks[name] = {'ok': bool(result), 'detail': detail}

    check('native_linker', '/system/bin/linker64' in subprocess.check_output([shutil.which('readelf') or 'greadelf', '-l', str(ROOT / 'bin/gnome-shell')], text=True))
    check('shell_48', subprocess.check_output([str(ROOT / 'bin/gnome-shell'), '--version'], text=True).strip().startswith('GNOME Shell 48.'))
    check('private_home_config', os.environ.get('XDG_CONFIG_HOME') == str(Path.home() / '.config/livecd-native'))
    sinks = subprocess.check_output(['pactl', 'list', 'short', 'sinks'], text=True)
    check('native_audio', os.environ.get('PULSE_SERVER', '').startswith('unix:') and 'OpenSL_ES_sink' in sinks, sinks.strip())
    wm = subprocess.check_output(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK'], text=True)
    check('window_manager', 'window id #' in wm, wm.strip())
    renderer = os.environ.get('LIVECD_NATIVE_RENDERER', 'software')
    glx = subprocess.check_output(['glxinfo', '-B'], text=True, timeout=20)
    if renderer == 'zink':
        expected_driver = zink_driver()
        device_name = 'Mali' if expected_driver == 'panvk' else 'Turnip Adreno'
        check('renderer_zink', 'Accelerated: yes' in glx and 'zink' in glx and device_name in glx, glx.strip())
    else:
        check('renderer_software', 'llvmpipe' in glx and 'Accelerated: no' in glx, glx.strip())
    shell_graphics = process_gpu(shell_pid(os.environ))
    if renderer == 'zink':
        raw_env = (Path('/proc') / str(shell_graphics['pid']) / 'environ').read_bytes().split(b'\0')
        compositor_env = {key: next((v.decode().split('=', 1)[1] for v in raw_env if v.startswith((key + '=').encode())), None)
                          for key in ('LIVECD_NATIVE_RENDERER', 'COGL_DRIVER', 'GALLIUM_DRIVER', 'VK_DRIVER_FILES')}
        check('shell_egl_gles', compositor_env['COGL_DRIVER'] == 'gles2' and compositor_env['GALLIUM_DRIVER'] == 'zink', compositor_env)
        check('shell_vulkan_driver', shell_graphics['driver'] == expected_driver, shell_graphics)
        library_key, device_key = (('panvk_libraries', 'mali_devices') if expected_driver == 'panvk'
                                   else ('turnip_libraries', 'kgsl_devices'))
        check('shell_' + expected_driver + '_library', bool(shell_graphics[library_key]), shell_graphics[library_key])
        check('shell_gpu_device', bool(shell_graphics[device_key]), shell_graphics[device_key])
    else:
        check('shell_software', not shell_graphics['libraries'] and not shell_graphics['devices'], shell_graphics)
    extensions = bus_call(os.environ, 'org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions',
        'org.gnome.Shell.Extensions', 'ListExtensions')[0]
    settings = Gio.Settings.new('org.gnome.shell')
    expected = settings.get_strv('enabled-extensions')
    states = {uuid: extensions.get(uuid, {}).get('state') for uuid in expected}
    safe = settings.get_boolean('disable-user-extensions')
    check('extensions', safe or all(state == 1 for state in states.values()), states)
    # An extension stays active when its worker crashes, and Shell carries on without failed indicators.
    log = (STATE / 'session.log').read_bytes().rsplit(SESSION_LOG_START, 1)[-1].decode(errors='replace')
    failures = [line for line in log.splitlines() if 'JS ERROR' in line or 'Failed to setup' in line]
    check('session_log', not failures, failures[:5])
    grids = subprocess.run(['xdotool', 'search', '--name', '^@!'], capture_output=True, text=True).stdout.split()
    check('desktop_icons', safe or bool(grids), grids)
    check('lock_disabled', Gio.Settings.new('org.gnome.desktop.lockdown').get_boolean('disable-lock-screen'))
    for schema, key in [('org.gnome.desktop.lockdown', 'disable-lock-screen'),
                        ('org.gnome.desktop.screensaver', 'lock-enabled'),
                        ('org.gnome.desktop.session', 'idle-delay')]:
        check('read_only_' + key, not Gio.Settings.new(schema).is_writable(key))
    commands = ['ghostty', 'nautilus', 'code-oss', 'io.elementary.code', 'firefox', 'libreoffice', 'mpv', 'missioncenter']
    for name in commands:
        path = shutil.which(name)
        check('application_' + name, path is not None and str(path).startswith((str(PREFIX), str(ROOT), str(Path.home() / '.local/lib/livecd-native/bin'))), path)
    for code in ('20000', '2a700'):
        output = subprocess.check_output(['fc-list', ':charset=' + code, 'family'], text=True)
        check('font_U+' + code, bool(output.strip()), output.strip().splitlines()[:5])
    fixture = subprocess.Popen([sys.executable, '-c', 'while True: pass'])
    try:
        time.sleep(0.25)
        fixture.send_signal(signal.SIGSTOP)
        time.sleep(0.15)
        state = process_identity(fixture.pid)[0]
        check('native_SIGSTOP', state == 'T', state)
        fixture.send_signal(signal.SIGCONT)
        time.sleep(0.15)
        check('native_SIGCONT', process_identity(fixture.pid)[0] != 'T')
    finally:
        fixture.terminate()
        fixture.wait(timeout=5)
    processes = []
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            if path.parent.stat().st_uid != os.getuid():
                continue
            args = path.read_bytes().split(b'\0')
            if args and Path(os.fsdecode(args[0])).name in ('proot', 'proot-distro'):
                processes.append({'pid': int(path.parent.name), 'args': [os.fsdecode(v) for v in args if v]})
        except OSError:
            pass
    check('no_proot_processes', not processes, processes)
    result = {'ok': all(v['ok'] for v in checks.values()), 'backend': 'native', 'renderer': renderer, 'safe': safe, 'checks': checks}
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
