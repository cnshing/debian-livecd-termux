#!/usr/bin/env python3
"""Private PanVK GNOME/GTK4 presentation experiment; no installed settings change."""
import argparse
import ctypes
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import time
import traceback

HOME = Path.home()
PAN = HOME / 'gpu-x1s/panvk'
ROOT = HOME / '.local/opt/livecd-native/gnome-48'
sys.path.insert(0, str(HOME / '.local/lib/livecd-native'))
sys.path.insert(0, str(HOME / 'gpu-x1s/browser-tests/browsers'))


def run(command, **kwargs):
    kwargs.setdefault('check', True)
    return subprocess.run(command, timeout=25, **kwargs)


def wait(check, seconds=40):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(.2)
    raise RuntimeError('Timed out waiting for private test state')


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def cleanup_tagged(tag):
    """D-Bus services can double-fork out of the session process group."""
    marker = ('LIVECD_FULLSCREEN_TEST=' + str(tag)).encode()
    owned = {}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if marker in (proc / 'environ').read_bytes().split(b'\0'):
                owned[int(proc.name)] = (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        except OSError:
            pass
    def same(pid, birth):
        try:
            fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
            return fields[19] == birth and fields[0] != 'Z'
        except OSError:
            return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, birth in owned.items():
            if same(pid, birth):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        if sig == signal.SIGTERM:
            until = time.monotonic() + 3
            while time.monotonic() < until and any(same(pid, birth) for pid, birth in owned.items()):
                time.sleep(.1)
    return list(owned)


def audit(pid):
    proc = Path('/proc') / str(pid)
    maps = (proc / 'maps').read_text()
    devices = []
    for fd in (proc / 'fd').iterdir():
        try:
            target = os.readlink(fd)
            if target in ('/dev/mali0', '/dev/ion') or 'dmabuf' in target:
                devices.append({'fd': int(fd.name), 'target': target})
        except OSError:
            pass
    return {'pid': pid, 'libraries': sorted({s.split()[-1] for s in maps.splitlines()
            if any(k in s for k in ('panfrost', 'gallium', 'EGL', 'GLES', 'mutter-cogl',
                                   'angle', 'libgtk-4', 'libX11', 'libxcb', 'libxshmfence'))}),
            'devices': devices, 'fd_count': len(list((proc / 'fd').iterdir())),
            'status': (proc / 'status').read_text()}


def gtk(out):
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk, GLib
    # GLArea makes an actual GLES context and renders a quadrant oracle. The
    # layout changes on resize and its top-left color alternates on each command.
    gl = ctypes.CDLL('libGLESv2.so')
    gl.glGetString.restype = ctypes.c_char_p
    gl.glClearColor.argtypes = [ctypes.c_float] * 4
    gl.glClear.argtypes = [ctypes.c_uint]
    app = Gtk.Application(application_id='org.livecd.PanvkPrivate')
    state = {'frame': 0, 'phase': 0}
    colors = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.), (1., 1., 1.))

    def activate(app):
        win = Gtk.ApplicationWindow(application=app, title='PanVK GTK4 oracle')
        win.set_decorated(False)
        win.set_default_size(640, 360)
        area = Gtk.GLArea()
        area.set_use_es(True)
        area.set_required_version(3, 0)
        win.set_child(area)

        def render(area, context):
            if area.get_error():
                raise RuntimeError(str(area.get_error()))
            width, height = area.get_width(), area.get_height()
            scale = area.get_scale_factor()
            width, height = width * scale, height * scale
            gl.glViewport(0, 0, width, height)
            gl.glEnable(0x0C11)  # GL_SCISSOR_TEST
            for i, rgb in enumerate(colors):
                # GL coordinates start at the bottom; the screenshot starts at top.
                x = width // 2 if i % 2 else 0
                y = height // 2 if i < 2 else 0
                w = width - x if i % 2 else width // 2
                h = height - y if i < 2 else height // 2
                rgb = (1., 1., 0.) if i == 0 and state['phase'] % 2 else rgb
                gl.glScissor(x, y, w, h)
                gl.glClearColor(*rgb, 1.)
                gl.glClear(0x4000)
            gl.glDisable(0x0C11)
            state.update(frame=state['frame'] + 1, width=width, height=height,
                         renderer=gl.glGetString(0x1F01).decode(),
                         version=gl.glGetString(0x1F02).decode(),
                         gsk=os.environ.get('GSK_RENDERER'))
            tmp = out / 'gtk-state.tmp'
            tmp.write_text(json.dumps(state))
            tmp.replace(out / 'gtk-state.json')
            return True

        area.connect('render', render)

        def command():
            path = out / 'command.json'
            if path.exists():
                value = json.loads(path.read_text())
                path.unlink()
                state['phase'] = value['phase']
                if value.get('fullscreen'):
                    win.fullscreen()
                else:
                    win.unfullscreen()
                area.queue_render()
            return True

        GLib.timeout_add(50, command)
        win.present()

    app.connect('activate', activate)
    return app.run([])


def worker(args):
    assert os.environ.get('LIVECD_FULLSCREEN_TEST') == str(args.out)
    assert os.environ['DISPLAY'].startswith(':') and 74 <= int(os.environ['DISPLAY'][1:]) < 100
    from capture import screenshot
    os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = os.environ['DBUS_SESSION_BUS_ADDRESS']
    out = args.out
    children, logs = [], []
    terminal = None
    result = {'mode': args.mode, 'display': os.environ['DISPLAY'], 'captures': []}
    def check_displays():
        displays = {p.name for p in (Path(os.environ['TMPDIR']) / '.X11-unix').glob('X*')}
        expected = {'X0', 'X' + os.environ['DISPLAY'][1:]}
        if displays - expected:
            result['foreign_displays'] = sorted(set(result.get('foreign_displays', [])) | (displays - expected))
            if not args.allow_other_displays:
                raise RuntimeError('Another private display appeared: ' + repr(result['foreign_displays']))
    def start(command, name, env=None):
        log = (out / (name + '.log')).open('w')
        logs.append(log)
        p = subprocess.Popen(command, stdout=log, stderr=log, env=env)
        children.append(p)
        return p
    try:
        run(['gsettings', 'set', 'org.gnome.desktop.interface', 'enable-animations', 'false'])
        extension = Path(os.environ['XDG_DATA_HOME']) / 'gnome-shell/extensions/panvk-capture@livecd'
        extension.mkdir(parents=True)
        (extension / 'metadata.json').write_text(json.dumps({'uuid': 'panvk-capture@livecd',
            'name': 'Private PanVK capture', 'description': 'Composited fullscreen capture', 'shell-version': ['48']}))
        (extension / 'extension.js').write_text("""import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
export default class Capture extends Extension {
enable() { global.compositor.disable_unredirect(); console.log('PANVK_CAPTURE_READY'); }
disable() { global.compositor.enable_unredirect(); }
}
""")
        run(['gsettings', 'set', 'org.gnome.shell', 'disable-user-extensions', 'false'])
        run(['gsettings', 'set', 'org.gnome.shell', 'enabled-extensions', "['panvk-capture@livecd']"])
        shell = start([str(ROOT / 'bin/gnome-shell'), '--x11', '--sm-disable'], 'shell')
        def ready():
            if shell.poll() is not None:
                raise RuntimeError('Private shell exited: ' + str(shell.returncode))
            return 'WINDOW' in run(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK'], capture_output=True, text=True).stdout
        wait(ready, 60)
        wait(lambda: 'PANVK_CAPTURE_READY' in (out / 'shell.log').read_text(), 25)
        time.sleep(2)
        run(['xdotool', 'key', 'Escape'])
        time.sleep(1)
        screenshot(out / 'shell.png')
        result['shell'] = audit(shell.pid)
        result['glxinfo'] = run(['glxinfo', '-B'], capture_output=True, text=True).stdout
        if args.ghostty_probe:
            # Direct binary: exercise GPU rendering, bypassing the installed
            # software compatibility wrapper. Only this private display is used.
            ready = out / 'ghostty-shell-ready'
            shell_script = out / 'ghostty-shell.sh'
            shell_script.write_text("printf '\\033[32mG77 port terminal ready\\033[0m\\n'\n"
                + 'touch ' + shlex.quote(str(ready)) + '\n'
                + "export PS1='g77-port$ '\nexec bash --noprofile --norc -i\n")
            terminal_env = os.environ.copy()
            terminal_env['GSK_RENDERER'] = args.ghostty_gsk
            if args.ghostty_software:
                from graphics import apply_renderer
                terminal_env = apply_renderer(terminal_env, 'software')
            executable = ([sys.executable, str(args.ghostty_launcher)] if args.ghostty_launcher
                          else [str(Path(os.environ['PREFIX']) / 'bin/ghostty')])
            terminal = start([*executable,
                '--gtk-single-instance=false', '--title=PanVK G77 Ghostty',
                '--working-directory=' + str(out), '-e', 'bash', '--noprofile', '--norc',
                str(shell_script)], 'ghostty', env=terminal_env)
            def terminal_ready():
                code = terminal.poll()
                if code is not None:
                    raise RuntimeError('Private Ghostty exited before shell readiness: ' + str(code))
                return ready.exists()
            wait(terminal_ready)
            def terminal_window():
                if terminal.poll() is not None:
                    raise RuntimeError('Private Ghostty exited: ' + str(terminal.returncode))
                return run(['xdotool', 'search', '--onlyvisible', '--name', '^PanVK G77 Ghostty$'],
                    check=False, capture_output=True, text=True).stdout.strip().splitlines()
            wid = wait(terminal_window)[-1]
            run(['xdotool', 'windowactivate', '--sync', wid])
            time.sleep(2)
            try:
                gpu = audit(terminal.pid)
            except OSError as error:
                result['ghostty_audit_error'] = repr(error)
                gpu = {'pid': terminal.pid}
            result['ghostty'] = dict(gpu, software_control=args.ghostty_software, window=wid)
            result['ghostty']['geometry'] = run(['xdotool', 'getwindowgeometry', '--shell', wid], capture_output=True, text=True).stdout
            result['ghostty']['active'] = run(['xdotool', 'getactivewindow'], capture_output=True, text=True).stdout.strip()
            screenshot(out / 'ghostty-before-input.png')
            identity = out / 'ghostty-identity.json'
            code = ('import os,json,sys; from pathlib import Path; '
                'print("\\033[32mPANVK G77 GHOSTTY INPUT PASS\\033[0m"); '
                'Path(' + repr(str(identity)) + ').write_text(json.dumps(dict(uid=os.getuid(), '
                'home=str(Path.home()), experiment=os.environ.get("PANVK_G77_LWG"), '
                'gl_override=os.environ.get("MESA_GL_VERSION_OVERRIDE"))))')
            command_file = out / 'ghostty-command.py'
            code += '\n' + '''phase = int(sys.argv[1]) if len(sys.argv) > 1 else 1
colors = [(255,255 if phase % 2 else 0,0),(0,255,0),(0,0,255),(255,255,255)]
print("\\033[2J\\033[H", end="")
print("GHOSTTY GPU RENDER ORACLE", phase)
for r,g,b in colors:
    for _ in range(3):
        print(f"\\033[48;2;{r};{g};{b}m" + " " * 24 + "\\033[0m")
print("GHOSTTY INPUT PASS", phase, flush=True)
'''
            command_file.write_text(code + '\n')
            run(['xdotool', 'type', '--clearmodifiers', '--delay', '5', 'python ' + shlex.quote(str(command_file))])
            run(['xdotool', 'key', 'Return'])
            time.sleep(2)
            screenshot(out / 'ghostty-after-input.png')
            def identity_ready():
                code = terminal.poll()
                if code is not None:
                    raise RuntimeError('Private Ghostty exited while waiting for input: ' + str(code))
                return identity.exists()
            wait(identity_ready)
            data = json.loads(identity.read_text())
            assert data['uid'] == os.getuid() and data['gl_override'] is None, data
            gpu = audit(terminal.pid)
            driver = json.loads(Path(os.environ['VK_DRIVER_FILES']).read_text())['ICD']['library_path']
            if args.ghostty_software:
                assert driver not in gpu['libraries'], gpu
                assert not any(fd['target'] == '/dev/mali0' for fd in gpu['devices']), gpu
            else:
                assert driver in gpu['libraries'], gpu
                assert any(fd['target'] == '/dev/mali0' for fd in gpu['devices']), gpu
            result['ghostty'].update(identity=data, captures=[])
            for phase in range(1, args.cycles * 2 + 1):
                full = phase % 2 == 0
                if full:
                    run(['xdotool', 'windowstate', '--add' if full else '--remove', 'FULLSCREEN', wid])
                else:
                    if phase > 1:
                        run(['xdotool', 'windowstate', '--add' if full else '--remove', 'FULLSCREEN', wid])
                    run(['xdotool', 'windowsize', '--sync', wid,
                         str(803 if phase % 4 == 1 else 641), '620'])
                time.sleep(.5)
                run(['xdotool', 'windowactivate', '--sync', wid])
                time.sleep(.3)
                identity.unlink(missing_ok=True)
                run(['xdotool', 'type', '--clearmodifiers', '--delay', '2',
                     'python ' + shlex.quote(str(command_file)) + ' ' + str(phase)])
                run(['xdotool', 'key', 'Return'])
                wait(identity_ready)
                time.sleep(1)
                path = out / f'ghostty-{phase:02d}.png'
                screenshot(path)
                result['ghostty']['captures'].append({'path': path.name, 'phase': phase,
                    'fullscreen_requested': full,
                    'wm_state': run(['xprop', '-id', wid, '_NET_WM_STATE'], capture_output=True, text=True).stdout,
                    'geometry': run(['xdotool', 'getwindowgeometry', '--shell', wid],
                                    capture_output=True, text=True).stdout})
            screenshot(out / 'ghostty.png')
            run(['xdotool', 'type', '--clearmodifiers', 'exit'])
            run(['xdotool', 'key', 'Return'])
            terminal.wait(timeout=10)
            assert terminal.returncode == 0, terminal.returncode
        for name, command, needle in (
            ('nautilus', ['nautilus', '--new-window', str(out)], 'org.gnome.Nautilus'),
            ('settings', ['gnome-control-center', 'display'], 'gnome-control-center')):
            start(command, name)
            time.sleep(5)
            ids = run(['xdotool', 'search', '--onlyvisible', '--name', '.*'], capture_output=True, text=True).stdout.split()
            tree = '\n'.join(run(['xprop', '-id', wid, 'WM_CLASS', '_NET_WM_NAME'],
                                  capture_output=True, text=True).stdout for wid in ids)
            (out / (name + '-windows.txt')).write_text(tree)
            screenshot(out / (name + '.png'))
            result[name] = {'window_found': needle.lower() in tree.lower()}
            # Close only the active window on this private display.
            run(['xdotool', 'key', 'alt+F4'])
            time.sleep(1)
        app = start([sys.executable, __file__, '--gtk', '--out', str(out)], 'gtk')
        wait(lambda: (out / 'gtk-state.json').exists())
        window = wait(lambda: run(['xdotool', 'search', '--name', '^PanVK GTK4 oracle$'],
                                  check=False, capture_output=True, text=True).stdout.strip().splitlines())[-1]
        result['gtk_initial'] = json.loads((out / 'gtk-state.json').read_text())
        result['gtk_process'] = audit(app.pid)
        phase = 0
        for cycle in range(args.cycles):
            for full in (False, True):
                check_displays()
                phase += 1
                command_file = out / 'command.tmp'
                command_file.write_text(json.dumps({'phase': phase, 'fullscreen': full}))
                command_file.replace(out / 'command.json')
                wait(lambda: json.loads((out / 'gtk-state.json').read_text())['phase'] == phase)
                if not full:
                    width, height = ((641, 359), (803, 451), (527, 317), (960, 541))[cycle % 4]
                    run(['xdotool', 'windowsize', '--sync', window, str(width), str(height)])
                time.sleep(.35)
                state = json.loads((out / 'gtk-state.json').read_text())
                geometry = run(['xdotool', 'getwindowgeometry', '--shell', window], capture_output=True, text=True).stdout
                props = run(['xprop', '-id', window, '_NET_WM_STATE'], capture_output=True, text=True).stdout
                path = out / f'gtk-{cycle:02d}-{"full" if full else "window"}.png'
                screenshot(path)
                result['captures'].append({'path': path.name, 'state': state,
                    'geometry': geometry, 'wm_state': props, 'fullscreen_requested': full})
                if shell.poll() is not None or app.poll() is not None:
                    raise RuntimeError('Shell or GTK application exited')
            if (cycle + 1) % 5 == 0:
                print('CYCLES', cycle + 1, 'OF', args.cycles, flush=True)
        result['shell_end'] = audit(shell.pid)
        result['gtk_end'] = audit(app.pid)
        if args.soak_seconds:
            stop(app)
            cube = start([str(HOME / 'gpu-x1s/root/data/data/com.termux/files/usr/bin/vkcube'),
                          '--wsi', 'xcb', '--present_mode', '2'], 'soak-cube')
            gears = start(['glxgears', '-geometry', '400x400+30+60'], 'soak-gears')
            time.sleep(3)
            windows = run(['xdotool', 'search', '--onlyvisible', '--name', 'vkcube'],
                          capture_output=True, text=True).stdout.split()
            if windows:
                run(['xdotool', 'windowmove', '--sync', windows[-1], '700', '100'])
                time.sleep(1)
                run(['xdotool', 'windowmove', '--sync', windows[-1], '700', '100'])
            result['soak'] = {'seconds_requested': args.soak_seconds,
                              'workloads': 'vkcube FIFO and glxgears concurrently; stability, not a benchmark',
                              'samples': []}
            begin = time.monotonic()
            index = 0
            while time.monotonic() - begin < args.soak_seconds:
                check_displays()
                for name, proc in (('shell', shell), ('cube', cube), ('gears', gears)):
                    if proc.poll() is not None:
                        result['unexpected_process_exit'] = {'name': name, 'pid': proc.pid,
                                                            'returncode': proc.returncode}
                        raise RuntimeError('Soak process exited: ' + name)
                elapsed = time.monotonic() - begin
                sample = {'elapsed': elapsed, 'processes': {name: audit(proc.pid) for name, proc in
                          (('shell', shell), ('cube', cube), ('gears', gears))}}
                path = out / f'soak-{index:03d}.png'
                screenshot(path)
                sample['capture'] = path.name
                result['soak']['samples'].append(sample)
                (out / 'soak-progress.json').write_text(json.dumps(result['soak'], indent=2))
                print('SOAK_SECONDS', round(elapsed), 'OF', args.soak_seconds, flush=True)
                index += 1
                time.sleep(min(30, max(0, args.soak_seconds - (time.monotonic() - begin))))
            result['soak']['seconds_completed'] = time.monotonic() - begin
            result['soak']['final'] = {name: audit(proc.pid) for name, proc in
                                     (('shell', shell), ('cube', cube), ('gears', gears))}
        if args.restart_cycles:
            stop(app)
            result['restart_cycles'] = []
            cube = HOME / 'gpu-x1s/root/data/data/com.termux/files/usr/bin/vkcube'
            for i in range(args.restart_cycles):
                start_time = time.monotonic()
                p = run(['timeout', '-k', '5', '20', str(cube), '--wsi', 'xcb', '--c', '3'],
                        capture_output=True, text=True)
                result['restart_cycles'].append({'index': i, 'returncode': p.returncode,
                    'seconds': time.monotonic() - start_time, 'output': p.stdout + p.stderr})
                if shell.poll() is not None:
                    raise RuntimeError('Shell exited during repeated Vulkan teardown')
                if (i + 1) % 10 == 0:
                    print('CUBE_RESTARTS', i + 1, flush=True)
            result['shell_after_restarts'] = audit(shell.pid)
        result['completed'] = True
    except BaseException:
        result['error'] = traceback.format_exc()
        print(result['error'], flush=True)
        if terminal is not None and terminal.poll() is None:
            try:
                screenshot(out / 'ghostty-failure.png')
                result['failure_active_window'] = run(['xdotool', 'getactivewindow'],
                    check=False, capture_output=True, text=True).stdout
            except Exception as error:
                result['failure_capture_error'] = repr(error)
    finally:
        if terminal is not None:
            result.setdefault('ghostty', {}).update(
                pid=terminal.pid, returncode_before_cleanup=terminal.poll())
            if terminal.poll() is None:
                try:
                    proc = Path('/proc') / str(terminal.pid)
                    result['ghostty']['last_status'] = (proc / 'status').read_text()
                    result['ghostty']['threads'] = {t.name: (t / 'wchan').read_text()
                        for t in (proc / 'task').iterdir()}
                except OSError as error:
                    result['ghostty']['diagnostic_error'] = repr(error)
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        for p in reversed(children):
            stop(p)
        for log in logs:
            log.close()
    return 0 if result.get('completed') else 1


def parent(args):
    from desktop import environment
    from graphics import apply_renderer
    spec = importlib.util.spec_from_file_location('fullscreen', HOME / 'gpu-x1s/browser-tests/browsers/test-fullscreen.py')
    fs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fs)
    args.out.mkdir(parents=True, exist_ok=False)
    print('OUTPUT', args.out, flush=True)
    lock = (Path(os.environ['TMPDIR']) / 'livecd-fullscreen-test.lock').open('a')
    print('Waiting for the shared private-display lock', flush=True)
    fcntl.flock(lock, fcntl.LOCK_EX)
    before = fs.live_state()
    if not args.allow_other_displays and any(name != 'X0' for name in before['displays']):
        raise RuntimeError('Another private X display is active; wait for its owner to finish: ' +
                           repr(before['displays']))
    status_before = run([str(HOME / '.local/bin/livecd'), 'status'], capture_output=True, text=True).stdout
    env = environment('zink' if args.integrated else 'software')
    for key in ('LIVECD_NATIVE_SESSION', 'XAUTHORITY', 'LIBGL_ALWAYS_SOFTWARE'):
        env.pop(key, None)
    icd = Path(env['VK_DRIVER_FILES']) if args.integrated else PAN / 'android/icd.json'
    if args.driver:
        driver = args.driver.resolve(strict=True)
        icd = args.out / 'icd.json'
        icd.write_text(json.dumps({'file_format_version': '1.0.0',
                                  'ICD': {'library_path': str(driver), 'api_version': '1.3.0'}}))
    env.update(GALLIUM_DRIVER='zink', MESA_LOADER_DRIVER_OVERRIDE='zink',
               VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd),
               GSK_RENDERER='gl', COGL_DRIVER='gles2', LIVECD_NATIVE_RENDERER='panvk-experiment',
               LIVECD_FULLSCREEN_TEST=str(args.out), MUTTER_SYNC='1',
               TERMUX_VA_SOCKET=str(args.out / 'absent-va.sock'))
    # Private graphics tests need no battery helper or privileged shell client.
    env['MC_RISH'] = str(args.out / 'absent-rish')
    # Explicit $PREFIX/lib shadows Android platform dependencies: libui then
    # fails its libbinder_ndk version requirement. Default Termux lookup still
    # finds Termux libraries; keep only the private GNOME and X11 paths here.
    env['LD_LIBRARY_PATH'] = ':'.join([*([] if args.no_xlibs or args.integrated else [str(PAN / 'android/xlibs')]), *(
        p for p in env['LD_LIBRARY_PATH'].split(':') if p != os.environ['PREFIX'] + '/lib')])
    if args.mesa_lib_dir:
        libraries = args.mesa_lib_dir.resolve(strict=True)
        env['LD_LIBRARY_PATH'] = str(libraries) + ':' + env['LD_LIBRARY_PATH']
        env['LIBGL_DRIVERS_PATH'] = str(libraries / 'dri')
    env.pop('PANVK_KBASE_DRI3', None)
    if args.mode == 'raw':
        env['PANVK_KBASE_DRI3'] = 'raw'
    if args.server == 'xvfb':
        env['LIBGL_KOPPER_DRI2'] = '1'
    for name in ('config', 'data', 'cache', 'runtime', 'state'):
        directory = args.out / name
        directory.mkdir(mode=0o700)
        env['XDG_' + name.upper() + ('_DIR' if name == 'runtime' else '_HOME')] = str(directory)
    profile = args.out / 'dconf-profile'
    profile.write_text('user-db:user\n')
    env['DCONF_PROFILE'] = str(profile)
    display = next(n for n in range(74, 100) if not any(p.exists() for p in
        (Path(os.environ['TMPDIR']) / f'.X11-unix/X{n}', Path(os.environ['TMPDIR']) / f'.X{n}-lock')))
    env['DISPLAY'] = ':' + str(display)
    server_env = apply_renderer(env.copy(), 'software')
    server_env.pop('PANVK_KBASE_DRI3', None)
    session = server = None
    code = 1
    try:
        with (args.out / 'server.log').open('w') as log:
            command = [str(PAN / 'private-lorie/private-lorie'), env['DISPLAY']] if args.server == 'lorie' else [
                'Xvfb', env['DISPLAY'], '-screen', '0', '1280x720x24', '-nolisten', 'tcp']
            server = subprocess.Popen(command, env=server_env, stdout=log, stderr=log)
        wait(lambda: subprocess.run(['xdpyinfo'], env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=5).returncode == 0)
        (args.out / 'environment.json').write_text(json.dumps(env, indent=2))
        session = subprocess.Popen(['dbus-run-session', '--', sys.executable, __file__, '--worker',
             '--mode', args.mode, '--out', str(args.out), '--cycles', str(args.cycles),
             '--restart-cycles', str(args.restart_cycles), '--soak-seconds', str(args.soak_seconds),
             *(['--allow-other-displays'] if args.allow_other_displays else []),
             *(['--ghostty-probe'] if args.ghostty_probe else []),
             *(['--ghostty-launcher', str(args.ghostty_launcher)] if args.ghostty_launcher else []),
             *(['--ghostty-software'] if args.ghostty_software else []),
             '--ghostty-gsk', args.ghostty_gsk,
             *(['--controller-dir', str(args.controller_dir)] if args.controller_dir else [])],
             env=env, start_new_session=True)
        code = session.wait(timeout=480 + args.soak_seconds)
    finally:
        if session:
            try:
                os.killpg(session.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                session.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(session.pid, signal.SIGKILL)
                session.wait(timeout=5)
        server_exit_before_cleanup = server.poll() if server else None
        stop(server)
        cleaned = cleanup_tagged(args.out)
        for path in (f'.X11-unix/X{display}', f'.X{display}-lock'):
            (Path(os.environ['TMPDIR']) / path).unlink(missing_ok=True)
        after = fs.live_state()
        status_after = run([str(HOME / '.local/bin/livecd'), 'status'], capture_output=True, text=True).stdout
        isolation = {'before': before, 'after': after, 'status_before': status_before,
                     'status_after': status_after, 'cleaned_orphan_pids': cleaned,
                     'server_exit_before_cleanup': server_exit_before_cleanup,
                     'ok': before == after and status_before == status_after}
        (args.out / 'isolation.json').write_text(json.dumps(isolation, indent=2))
    return code if isolation['ok'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=('shm', 'raw'), default='shm')
    parser.add_argument('--server', choices=('lorie', 'xvfb'), default='lorie')
    parser.add_argument('--cycles', type=int, default=20)
    parser.add_argument('--ghostty-launcher', type=Path, help='Private experimental Ghostty launcher')
    parser.add_argument('--ghostty-gsk', choices=('cairo', 'gl'), default='cairo')
    parser.add_argument('--ghostty-software', action='store_true', help='Software control for the Ghostty probe')
    parser.add_argument('--ghostty-probe', action='store_true', help='Check direct GPU Ghostty on the private display')
    parser.add_argument('--restart-cycles', type=int, default=0)
    parser.add_argument('--soak-seconds', type=int, default=0)
    parser.add_argument('--driver', type=Path)
    parser.add_argument('--mesa-lib-dir', type=Path)
    parser.add_argument('--no-xlibs', action='store_true', help='Verify the rebuilt driver uses Termux sonames directly')
    parser.add_argument('--integrated', action='store_true', help='Use the controller-selected packaged PanVK ICD')
    parser.add_argument('--controller-dir', type=Path, help='Test a privately staged controller directory')
    parser.add_argument('--allow-other-displays', action='store_true',
                        help='Record other private displays without rejecting a short correctness run')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--gtk', action='store_true')
    args = parser.parse_args()
    if args.cycles < 1 or args.restart_cycles < 0 or args.soak_seconds < 0:
        parser.error('cycles must be positive; restart and soak counts must be nonnegative')
    if args.server == 'xvfb' and args.mode == 'raw':
        parser.error('raw DRI3 requires the private lorie server')
    if args.allow_other_displays and args.soak_seconds:
        parser.error('overlapping displays are supported only for short correctness checks')
    if args.integrated and args.driver:
        parser.error('the integrated test uses the controller-selected driver')
    if args.controller_dir:
        sys.path.insert(0, str(args.controller_dir.resolve(strict=True)))
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    sys.exit(gtk(args.out) if args.gtk else worker(args) if args.worker else parent(args))
