#!/usr/bin/env python3
"""Private GNOME/GTK4 presentation experiment for PanVK (Mali) or Turnip (Adreno); no installed settings change."""
import argparse
import ctypes
import faulthandler
import fcntl
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import signal
import socket
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import traceback

HOME = Path.home()
PAN = HOME / 'gpu-x1s/panvk'
ROOT = HOME / '.local/opt/livecd-native/gnome-48'
BROWSERS = Path(__file__).resolve().parents[1] / 'browsers'
if not BROWSERS.is_dir():
    BROWSERS = HOME / 'gpu-x1s/browser-tests/browsers'
sys.path.insert(0, str(HOME / '.local/lib/livecd-native'))
sys.path.insert(0, str(BROWSERS))


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
            if target in ('/dev/mali0', '/dev/kgsl-3d0', '/dev/ion') or 'dmabuf' in target:
                devices.append({'fd': int(fd.name), 'target': target})
        except OSError:
            pass
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'cpu_ticks': int(fields[11]) + int(fields[12]),
            'libraries': sorted({s.split()[-1] for s in maps.splitlines()
            if any(k in s for k in ('panfrost', 'freedreno', 'gallium', 'EGL', 'GLES', 'mutter-cogl',
                                   'angle', 'libgtk-4', 'libX11', 'libxcb', 'libxshmfence'))}),
            'devices': devices, 'fd_count': len(list((proc / 'fd').iterdir())),
            'status': (proc / 'status').read_text()}


def resources(include_battery=False):
    thermal = {}
    for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            thermal[zone.name] = {'type': (zone / 'type').read_text().strip(),
                                  'raw_temp': (zone / 'temp').read_text().strip()}
        except OSError:
            pass
    result = {'monotonic': time.monotonic(), 'wall_time': time.time(),
              'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'),
              'meminfo': Path('/proc/meminfo').read_text(), 'thermal': thermal}
    if include_battery:
        try:
            reply = subprocess.run(['termux-battery-status'], check=True,
                                   capture_output=True, text=True, timeout=5)
            result['battery'] = json.loads(reply.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            result['battery_error'] = str(error)
    return result


def benchmark(args, shell, start, check_displays):
    """Measure transport cost separately from screenshots and correctness checks."""
    from capture import screenshot
    ticks = os.sysconf('SC_CLK_TCK')
    video_socket = Path(os.environ['XDG_RUNTIME_DIR']) / 'benchmark-mpv.sock'

    def video_stats(detailed=False):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(video_socket))
            with client.makefile('rwb') as stream:
                values = {}
                names = ['time-pos', 'estimated-vf-fps', 'frame-drop-count', 'decoder-frame-drop-count']
                if detailed:
                    names += ['vo-passes', 'video-out-params', 'current-vo', 'current-gpu-context',
                              'video-sync', 'display-sync-active', 'display-fps',
                              'estimated-display-fps', 'vsync-ratio', 'vo-delayed-frame-count',
                              'mistimed-frame-count', 'avsync']
                for request_id, name in enumerate(names):
                    stream.write((json.dumps({'command': ['get_property', name],
                                              'request_id': request_id}) + '\n').encode())
                    stream.flush()
                    while True:
                        line = stream.readline()
                        if not line:
                            raise RuntimeError('mpv IPC closed during benchmark')
                        reply = json.loads(line)
                        if reply.get('request_id') == request_id:
                            if name in names[:4] and (reply.get('error') != 'success' or reply.get('data') is None):
                                raise RuntimeError('mpv property unavailable: ' + name + ': ' + str(reply))
                            values[name] = reply
                            break
                return values

    def sample(processes):
        cpu = {}
        for name, pid in processes.items():
            # comm may contain spaces and parentheses; fields start after its final ')'.
            fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] == 'Z':
                raise RuntimeError('Benchmark process exited: ' + name)
            cpu[name] = (int(fields[11]) + int(fields[12])) / ticks
        result = {**resources(), 'cpu_seconds': cpu}
        if 'video' in processes:
            result['video'] = video_stats()
        return result

    def thread_stats(pid):
        values = {}
        for task in (Path('/proc') / str(pid) / 'task').iterdir():
            try:
                stat = (task / 'stat').read_text()
                fields = stat.rsplit(')', 1)[1].split()
                values[task.name] = {'name': stat.split('(', 1)[1].rsplit(')', 1)[0],
                    'start_ticks': fields[19], 'user_seconds': int(fields[11]) / ticks,
                    'system_seconds': int(fields[12]) / ticks}
            except FileNotFoundError:
                continue
        return values

    phases = [] if args.benchmark_video_only else [('idle', None),
        ('gears', ['stdbuf', '-oL', 'glxgears', '-fullscreen'])]
    if args.benchmark_video:
        # The real binary: the session's mpv on PATH is the livecd wrapper, which adds
        # its own --gpu-context/--hwdec choices.
        phases.append(('video', [str(Path(os.environ['PREFIX']) / 'bin/mpv'), '--no-config', '--hwdec=no', '--vo=gpu',
            '--gpu-api=opengl', '--fullscreen', '--loop-file=inf', '--audio=no',
            '--input-ipc-server=' + str(video_socket),
            *(['--vf=fps=' + str(args.benchmark_video_fps)] if args.benchmark_video_fps else []),
            '--term-status-msg=BENCH fps=${estimated-vf-fps} dropped=${frame-drop-count} '
            'decoder_dropped=${decoder-frame-drop-count} avsync=${avsync}',
            str(args.benchmark_video)]))
    results = {'seconds_per_phase': args.benchmark_seconds,
               'video_decode': 'software, audio disabled to isolate presentation cost',
               'video': str(args.benchmark_video) if args.benchmark_video else None,
               'display': run(['xdpyinfo'], capture_output=True, text=True).stdout,
               'randr': run(['xrandr'], capture_output=True, text=True).stdout,
               'video_filter_fps': args.benchmark_video_fps,
               'video_profile_requested': args.benchmark_video_profile, 'phases': []}
    if args.benchmark_video:
        digest = hashlib.sha256()
        with args.benchmark_video.open('rb') as fixture:
            for chunk in iter(lambda: fixture.read(1024 * 1024), b''):
                digest.update(chunk)
        results['video_sha256'] = digest.hexdigest()
    for name, command in phases:
        proc = start(command, 'benchmark-' + name) if command else None
        try:
            time.sleep(5)  # Warm up before measuring each phase.
            log_path = args.out / ('benchmark-' + name + '.log')
            log_offset = log_path.stat().st_size if proc else 0
            processes = {'shell': shell.pid, 'server': args.benchmark_server_pid}
            if proc:
                processes[name] = proc.pid
            detailed = name == 'video' and args.benchmark_video_profile
            profile_before = video_stats(detailed=True) if detailed else None
            threads_before = thread_stats(proc.pid) if detailed else None
            watcher = None
            if args.present_watch and proc:
                # How the server completes the compositor's presents over the same interval.
                watcher = subprocess.Popen([sys.executable, str(Path(__file__).with_name('present-watch.py')),
                    '--seconds', str(args.benchmark_seconds),
                    '--out', str(args.out / ('present-' + name + '.json'))])
            samples = [sample(processes)]
            end = time.monotonic() + args.benchmark_seconds
            while time.monotonic() < end:
                check_displays()
                if shell.poll() is not None or (proc and proc.poll() is not None):
                    raise RuntimeError('Benchmark workload exited: ' + name)
                time.sleep(min(1, max(0, end - time.monotonic())))
                samples.append(sample(processes))
            duration = samples[-1]['monotonic'] - samples[0]['monotonic']
            wall_duration = samples[-1]['wall_time'] - samples[0]['wall_time']
            present_modes = None
            if watcher:
                if watcher.wait(timeout=30) != 0:
                    raise RuntimeError('present-watch failed during ' + name)
                present_modes = json.loads((args.out / ('present-' + name + '.json')).read_text())
            if abs(wall_duration - duration) > max(2, duration * .1):
                raise RuntimeError('Phone suspended or wall clock changed; keep it awake and rerun')
            log_end = log_path.stat().st_size if proc else 0
            results['phases'].append({'name': name, 'elapsed_seconds': duration,
                'elapsed_wall_seconds': wall_duration,
                'processes': {key: audit(pid) for key, pid in processes.items()},
                'cpu_percent_one_core': {key: 100 * (samples[-1]['cpu_seconds'][key] - value) / duration
                                        for key, value in samples[0]['cpu_seconds'].items()},
                'present_modes': present_modes,
                'samples': samples})
            if detailed:
                threads_after = thread_stats(proc.pid)
                thread_cpu = []
                for tid, after in threads_after.items():
                    before = threads_before.get(tid)
                    if before and before['start_ticks'] == after['start_ticks']:
                        thread_cpu.append({'tid': int(tid), 'name': after['name'],
                            **{key.replace('_seconds', '_percent'): 100 * (after[key] - before[key]) / duration
                               for key in ('user_seconds', 'system_seconds')}})
                results['phases'][-1]['video_profile'] = {
                    'before': profile_before, 'after': video_stats(detailed=True),
                    'threads_before': threads_before, 'threads_after': threads_after,
                    'thread_cpu_percent_one_core': thread_cpu,
                    'thread_scope': 'threads alive at both snapshots with matching start ticks'}
            if name == 'video':
                first, last = samples[0]['video'], samples[-1]['video']
                advanced = last['time-pos']['data'] - first['time-pos']['data']
                if advanced < duration * .8:
                    raise RuntimeError('Video stalled or looped during measurement; use a longer fixture')
                results['phases'][-1]['video_seconds_advanced'] = advanced
                results['phases'][-1]['video_counters_delta'] = {
                    key: last[key]['data'] - first[key]['data']
                    for key in ('frame-drop-count', 'decoder-frame-drop-count')}
                if any(value < 0 for value in results['phases'][-1]['video_counters_delta'].values()):
                    raise RuntimeError('Video drop counters reset during measurement')
            screenshot(args.out / ('benchmark-' + name + '.png'))
        finally:
            stop(proc)
        if name == 'gears':
            log = log_path.read_bytes()[log_offset:log_end].decode(errors='replace')
            results['phases'][-1]['reported_fps'] = [float(fps) for fps in
                re.findall(r'=\s*([\d.]+) FPS', log)]
            if not results['phases'][-1]['reported_fps']:
                raise RuntimeError('glxgears reported no FPS during measurement')
        (args.out / 'benchmark.json').write_text(json.dumps(results, indent=2) + '\n')
        print('BENCHMARK', name, results['phases'][-1]['cpu_percent_one_core'], flush=True)
    return results


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
        extensions = ['panvk-capture@livecd']
        if args.menu_race_button:
            extensions += ['dash-to-panel@jderose9.github.com', 'arcmenu@arcmenu.com',
                           'user-theme@gnome-shell-extensions.gcampax.github.com']
        run(['gsettings', 'set', 'org.gnome.shell', 'enabled-extensions', str(extensions)])
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
        if args.benchmark_seconds:
            result['benchmark'] = benchmark(args, shell, start, check_displays)
            if args.benchmark_only:
                result['completed'] = True
                return 0
        if args.present_race_trials:
            subprocess.run([sys.executable, str(Path(__file__).with_name('panvk-present-race.py')),
                '--out', str(out / 'race'), '--trials', str(args.present_race_trials),
                '--frames', str(args.present_race_frames),
                *(['--menu-button', args.menu_race_button] if args.menu_race_button else [])], check=True,
                timeout=180 + args.present_race_trials * (args.present_race_frames / 30 + 45))
            if args.present_race_only:
                result['completed'] = True
                return 0
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
            result['ghostty'] = dict(gpu, software_control=args.ghostty_software, window=wid,
                                     renderer=args.ghostty_gsk)
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
                presentation_log_start = (out / 'ghostty.log').stat().st_size
                run(['xdotool', 'key', 'Return'])
                wait(identity_ready)
                time.sleep(1)
                path = out / f'ghostty-{phase:02d}.png'
                screenshot(path)
                result['ghostty']['captures'].append({'path': path.name, 'phase': phase,
                    'presentation_log_start': presentation_log_start,
                    'presentation_log_end': (out / 'ghostty.log').stat().st_size,
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
                time.sleep(args.capture_settle)
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
            cube = start([str(args.vkcube or HOME / 'gpu-x1s/root/data/data/com.termux/files/usr/bin/vkcube'),
                          '--wsi', 'xcb', '--present_mode', '2'], 'soak-cube')
            gears = start(['stdbuf', '-oL', 'glxgears', '-geometry', '400x400+30+60'], 'soak-gears')
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
            begin_wall = time.time()
            result['soak']['wall_time_started'] = begin_wall
            index = 0
            gears_log_offset = 0
            while time.monotonic() - begin < args.soak_seconds:
                check_displays()
                for name, proc in (('shell', shell), ('cube', cube), ('gears', gears)):
                    if proc.poll() is not None:
                        result['unexpected_process_exit'] = {'name': name, 'pid': proc.pid,
                                                            'returncode': proc.returncode}
                        raise RuntimeError('Soak process exited: ' + name)
                elapsed = time.monotonic() - begin
                sample = {**resources(include_battery=True), 'elapsed': elapsed, 'processes': {name: audit(proc.pid) for name, proc in
                          (('shell', shell), ('cube', cube), ('gears', gears))}}
                gears_log = (out / 'soak-gears.log').read_bytes()
                sample['gears_reported_fps'] = [float(fps) for fps in re.findall(
                    r'=\s*([\d.]+) FPS', gears_log[gears_log_offset:].decode(errors='replace'))]
                gears_log_offset = len(gears_log)
                if result['soak']['samples']:
                    previous = result['soak']['samples'][-1]
                    if (not sample['gears_reported_fps'] or
                            not all(fps > 0 for fps in sample['gears_reported_fps']) or
                            sample['processes']['cube']['cpu_ticks'] <= previous['processes']['cube']['cpu_ticks']):
                        result['soak']['stalled_sample'] = sample
                        raise RuntimeError('Soak rendering stopped advancing')
                path = out / f'soak-{index:03d}.png'
                screenshot(path)
                sample['capture'] = path.name
                result['soak']['samples'].append(sample)
                (out / 'soak-progress.json').write_text(json.dumps(result['soak'], indent=2))
                print('SOAK_SECONDS', round(elapsed), 'OF', args.soak_seconds, flush=True)
                index += 1
                time.sleep(min(30, max(0, args.soak_seconds - (time.monotonic() - begin))))
            result['soak']['seconds_completed'] = time.monotonic() - begin
            result['soak']['wall_seconds_completed'] = time.time() - begin_wall
            result['soak']['final'] = {name: audit(proc.pid) for name, proc in
                                     (('shell', shell), ('cube', cube), ('gears', gears))}
        if args.restart_cycles:
            stop(app)
            result['restart_cycles'] = []
            cube = args.vkcube or HOME / 'gpu-x1s/root/data/data/com.termux/files/usr/bin/vkcube'
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
    spec = importlib.util.spec_from_file_location('fullscreen', BROWSERS / 'test-fullscreen.py')
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
    if args.present_race_trials or args.benchmark_seconds or args.soak_seconds or args.restart_cycles:
        # Graphics probes need real /proc counters, not the compatibility broker.
        os.environ['ANDROID_PROCFS_COMPAT'] = '0'
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
    if args.benchmark_seconds:
        # MUTTER_SYNC enables synchronous X11 debugging; measure normal behavior.
        env.pop('MUTTER_SYNC', None)
    # Private graphics tests need no privileged shell client.
    env['MC_RISH'] = str(args.out / 'absent-rish')
    # Explicit $PREFIX/lib shadows Android platform dependencies: libui then
    # fails its libbinder_ndk version requirement. Default Termux lookup still
    # finds Termux libraries; keep only the private GNOME and X11 paths here.
    env['LD_LIBRARY_PATH'] = ':'.join([*([] if args.no_xlibs or args.integrated else [str(PAN / 'android/xlibs')]), *(
        p for p in env['LD_LIBRARY_PATH'].split(':') if p != os.environ['PREFIX'] + '/lib')])
    if args.driver and (args.driver.parent / 'x11').is_dir():
        # Zenith-built Android drivers dlopen versioned X11 sonames (see the PanVK package).
        env['LD_LIBRARY_PATH'] = str(args.driver.resolve().parent / 'x11') + ':' + env['LD_LIBRARY_PATH']
    if args.mesa_lib_dir:
        libraries = args.mesa_lib_dir.resolve(strict=True)
        env['LD_LIBRARY_PATH'] = str(libraries) + ':' + env['LD_LIBRARY_PATH']
        env['LIBGL_DRIVERS_PATH'] = str(libraries / 'dri')
    if args.mode == 'installed':
        # Keep the installed controller's own presentation choice and record it.
        (args.out / 'presentation.json').write_text(json.dumps(
            {key: env.get(key) for key in ('PANVK_KBASE_DRI3', 'TU_KGSL_DRI3', 'VK_DRIVER_FILES')}) + '\n')
    else:
        env.pop('PANVK_KBASE_DRI3', None)
        env.pop('TU_KGSL_DRI3', None)
    if args.mode in ('raw', 'ahb'):
        env['PANVK_KBASE_DRI3'] = args.mode
    if args.mode == 'ahb':
        # Turnip's equivalent; each driver ignores the other's switch.
        env['TU_KGSL_DRI3'] = 'ahb'
    if args.present_mode:
        env['MESA_VK_WSI_PRESENT_MODE'] = args.present_mode
    if args.wsi_debug:
        # apply_renderer strips MESA_VK_WSI_*; set it afterwards.
        env['MESA_VK_WSI_DEBUG'] = args.wsi_debug
    if args.server == 'xvfb':
        env['LIBGL_KOPPER_DRI2'] = '1'
    for name in ('config', 'data', 'cache', 'state'):
        directory = args.out / name
        directory.mkdir(mode=0o700)
        env['XDG_' + name.upper() + '_HOME'] = str(directory)
    if args.shell_profile:
        dconf = args.out / 'config/dconf'
        dconf.mkdir()
        shutil.copyfile(args.shell_profile, dconf / 'user')
    profile = args.out / 'dconf-profile'
    profile.write_text('user-db:user\n' + (
        'file-db:' + str(HOME / '.local/lib/livecd-native/dconf-defaults') + '\n'
        if args.shell_profile else ''))
    if args.shell_profile:
        themes = HOME / '.local/share/livecd-native/themes'
        if themes.is_dir():
            (args.out / 'data/themes').symlink_to(themes, target_is_directory=True)
    env['DCONF_PROFILE'] = str(profile)
    display = next(n for n in range(74, 100) if not any(p.exists() for p in
        (Path(os.environ['TMPDIR']) / f'.X11-unix/X{n}', Path(os.environ['TMPDIR']) / f'.X{n}-lock')))
    env['DISPLAY'] = ':' + str(display)
    server_env = apply_renderer(env.copy(), 'software')
    server_env.pop('PANVK_KBASE_DRI3', None)
    server_env.pop('TU_KGSL_DRI3', None)
    # Keep the control independent of the caller's environment.
    env.pop('TERMUX_X11_FORCE_FLIP', None)
    server_env.pop('TERMUX_X11_FORCE_FLIP', None)
    if args.force_flip:
        server_env['TERMUX_X11_FORCE_FLIP'] = '1'
    server_env.pop('TERMUX_X11_DEBUG', None)
    if args.server_debug:
        server_env['TERMUX_X11_DEBUG'] = '1'
    session = server = None
    runtime = None
    code = 1
    try:
        runtime = Path(tempfile.mkdtemp(prefix='pvk-', dir=os.environ['TMPDIR']))
        env['XDG_RUNTIME_DIR'] = server_env['XDG_RUNTIME_DIR'] = str(runtime)
        (args.out / 'runtime-directory.json').write_text(json.dumps({'path': str(runtime)}))
        with (args.out / 'server.log').open('w') as log:
            command = [str(BROWSERS / 'private-lorie/private-lorie'), env['DISPLAY']] if args.server == 'lorie' else [
                'Xvfb', env['DISPLAY'], '-screen', '0', '1280x720x24', '-nolisten', 'tcp']
            if args.screen_fps:
                command += ['-fakescreenfps', str(args.screen_fps)]
            server = subprocess.Popen(command, env=server_env, stdout=log, stderr=log)
        wait(lambda: subprocess.run(['xdpyinfo'], env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=5).returncode == 0)
        actual_server_env = dict(entry.split('=', 1) for entry in
            (Path('/proc') / str(server.pid) / 'environ').read_text().split('\0') if '=' in entry)
        actual_force_flip = actual_server_env.get('TERMUX_X11_FORCE_FLIP')
        (args.out / 'server-environment.json').write_text(json.dumps({
            'pid': server.pid, 'command': command, 'force_flip_requested': args.force_flip,
            'TERMUX_X11_FORCE_FLIP': actual_force_flip}, indent=2) + '\n')
        if actual_force_flip != ('1' if args.force_flip else None):
            raise RuntimeError('Private server force-flip environment does not match the request')
        if args.screen_size:
            run(['xrandr', '--fb', args.screen_size], env=env)
            dimensions = run(['xdpyinfo'], env=env, capture_output=True, text=True).stdout
            if not re.search(r'dimensions:\s+' + re.escape(args.screen_size) + r'\s', dimensions):
                raise RuntimeError('Private server did not accept screen-size')
        (args.out / 'environment.json').write_text(json.dumps(env, indent=2))
        session = subprocess.Popen(['dbus-run-session', '--', sys.executable, __file__, '--worker',
             '--mode', args.mode, '--out', str(args.out), '--cycles', str(args.cycles),
             '--capture-settle', str(args.capture_settle),
             '--restart-cycles', str(args.restart_cycles), '--soak-seconds', str(args.soak_seconds),
             '--benchmark-seconds', str(args.benchmark_seconds),
             '--benchmark-server-pid', str(server.pid),
             '--present-race-trials', str(args.present_race_trials),
             '--present-race-frames', str(args.present_race_frames),
             *(['--menu-race-button', args.menu_race_button] if args.menu_race_button else []),
             *(['--vkcube', str(args.vkcube.resolve())] if args.vkcube else []),
             *(['--present-race-only'] if args.present_race_only else []),
             *(['--benchmark-only'] if args.benchmark_only else []),
             *(['--present-watch'] if args.present_watch else []),
             *(['--benchmark-video-only'] if args.benchmark_video_only else []),
             *(['--benchmark-video-profile'] if args.benchmark_video_profile else []),
             *(['--benchmark-video-fps', str(args.benchmark_video_fps)] if args.benchmark_video_fps else []),
             *(['--benchmark-video', str(args.benchmark_video.resolve())] if args.benchmark_video else []),
             *(['--allow-other-displays'] if args.allow_other_displays else []),
             *(['--ghostty-probe'] if args.ghostty_probe else []),
             *(['--ghostty-launcher', str(args.ghostty_launcher)] if args.ghostty_launcher else []),
             *(['--ghostty-software'] if args.ghostty_software else []),
             '--ghostty-gsk', args.ghostty_gsk,
             *(['--controller-dir', str(args.controller_dir)] if args.controller_dir else [])],
             env=env, start_new_session=True)
        code = session.wait(timeout=480 + args.soak_seconds +
                            (3 if args.benchmark_video else 2) * (args.benchmark_seconds + 5) +
                            args.present_race_trials * (args.present_race_frames / 30 + 45))
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
        if server:
            # The server logs DRI3 imports and errors to Android's log, not to stdout.
            with (args.out / 'server-logcat.txt').open('w') as log:
                subprocess.run(['/system/bin/logcat', '-d', '-v', 'time', '--pid', str(server.pid)],
                               stdout=log, stderr=subprocess.STDOUT, timeout=20, check=False)
        cleaned = cleanup_tagged(args.out)
        if runtime:
            shutil.rmtree(runtime)
            (args.out / 'runtime-directory.json').write_text(json.dumps({
                'path': str(runtime), 'removed_after_owned_cleanup': True}))
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
    faulthandler.register(signal.SIGUSR1)
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=('shm', 'raw', 'ahb', 'installed', 'default'), default='shm',
                        help="installed keeps the integrated controller's presentation choice; "
                             'default sets no PanVK override (Turnip)')
    parser.add_argument('--present-mode', choices=('fifo', 'relaxed', 'mailbox', 'immediate'),
                        help='Override the Vulkan present mode after controller environment setup')
    parser.add_argument('--server', choices=('lorie', 'xvfb'), default='lorie')
    parser.add_argument('--screen-size', help='Private framebuffer size, e.g. 1920x1080')
    parser.add_argument('--screen-fps', type=int, help='Private lorie refresh rate (1–600)')
    parser.add_argument('--wsi-debug', help='Set MESA_VK_WSI_DEBUG for the session only, e.g. sw')
    parser.add_argument('--server-debug', action='store_true',
                        help='Set TERMUX_X11_DEBUG on the private server to log DRI3 imports')
    parser.add_argument('--force-flip', action='store_true',
                        help='Allow imported raw-fd flips on the private lorie; experimental')
    parser.add_argument('--cycles', type=int, default=20)
    parser.add_argument('--capture-settle', type=float, default=.35,
                        help='Seconds between a GTK colour/resize step and its capture')
    parser.add_argument('--ghostty-launcher', type=Path, help='Private experimental Ghostty launcher')
    parser.add_argument('--ghostty-gsk', choices=('cairo', 'gl'), default='cairo')
    parser.add_argument('--ghostty-software', action='store_true', help='Software control for the Ghostty probe')
    parser.add_argument('--ghostty-probe', action='store_true', help='Check direct GPU Ghostty on the private display')
    parser.add_argument('--restart-cycles', type=int, default=0)
    parser.add_argument('--vkcube', type=Path, help='Private or installed vkcube binary for restart/soak tests')
    parser.add_argument('--soak-seconds', type=int, default=0)
    parser.add_argument('--benchmark-seconds', type=int, default=0,
                        help='Measure idle, fullscreen gears and optional video before correctness checks')
    parser.add_argument('--benchmark-video', type=Path, help='Local video fixture for the presentation benchmark')
    parser.add_argument('--benchmark-video-only', action='store_true', help='Measure only the video phase')
    parser.add_argument('--benchmark-video-profile', action='store_true',
                        help='Record mpv render timings and per-thread CPU snapshots')
    parser.add_argument('--benchmark-video-fps', type=int,
                        help='Apply an mpv fps filter for equal-output-rate comparisons')
    parser.add_argument('--benchmark-only', action='store_true', help='Skip correctness checks after measuring')
    parser.add_argument('--present-watch', action='store_true',
                        help="Count copied and flipped completions of the compositor's presents")
    parser.add_argument('--benchmark-server-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--present-race-trials', type=int, default=0,
                        help='Record fullscreen WebGL flips for race analysis')
    parser.add_argument('--present-race-frames', type=int, default=900)
    parser.add_argument('--present-race-only', action='store_true')
    parser.add_argument('--menu-race-button', help='Record ArcMenu clicks instead of WebGL; private button X,Y')
    parser.add_argument('--shell-profile', type=Path, help='Copy this dconf database into the private profile')
    parser.add_argument('--driver', type=Path)
    parser.add_argument('--mesa-lib-dir', type=Path)
    parser.add_argument('--no-xlibs', action='store_true', help='Verify the rebuilt driver uses Termux sonames directly')
    parser.add_argument('--integrated', action='store_true',
                        help='Use the controller PanVK environment; --driver can override its ICD privately')
    parser.add_argument('--controller-dir', type=Path, help='Test a privately staged controller directory')
    parser.add_argument('--allow-other-displays', action='store_true',
                        help='Record other private displays without rejecting a short correctness run')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--gtk', action='store_true')
    args = parser.parse_args()
    if args.screen_size and not re.fullmatch(r'[1-9]\d{0,4}x[1-9]\d{0,4}', args.screen_size):
        parser.error('screen-size must be WIDTHxHEIGHT')
    if args.screen_fps is not None and (args.server != 'lorie' or not 1 <= args.screen_fps <= 600):
        parser.error('screen-fps requires lorie and a rate from 1 to 600')
    if args.cycles < 1 or args.restart_cycles < 0 or args.soak_seconds < 0:
        parser.error('cycles must be positive; restart and soak counts must be nonnegative')
    if args.vkcube and not args.vkcube.is_file():
        parser.error('vkcube must be an existing binary')
    if args.benchmark_seconds < 0 or 0 < args.benchmark_seconds < 10:
        parser.error('benchmark-seconds must be zero or at least 10')
    if args.benchmark_video and (not args.benchmark_seconds or not args.benchmark_video.is_file()):
        parser.error('benchmark-video requires a benchmark and an existing file')
    if (args.benchmark_video_only or args.benchmark_video_profile or
            args.benchmark_video_fps is not None) and not args.benchmark_video:
        parser.error('video-only/profile/fps requires benchmark-video')
    if args.benchmark_video_fps is not None and not 1 <= args.benchmark_video_fps <= 60:
        parser.error('benchmark-video-fps must be between 1 and 60')
    if args.benchmark_seconds and args.allow_other_displays:
        parser.error('benchmarks require no other private displays')
    if args.present_watch and not args.benchmark_seconds:
        parser.error('present-watch requires benchmark-seconds')
    if args.benchmark_only and not args.benchmark_seconds:
        parser.error('benchmark-only requires benchmark-seconds')
    if args.present_race_trials < 0 or args.present_race_frames < 1:
        parser.error('race trials must be nonnegative and race frames positive')
    if args.shell_profile and not args.shell_profile.is_file():
        parser.error('shell-profile must be an existing dconf database')
    if args.menu_race_button and (not args.present_race_trials or
            not re.fullmatch(r'\d{1,5},\d{1,5}', args.menu_race_button) or
            (not args.worker and not args.shell_profile)):
        parser.error('menu-race-button requires race trials, X,Y coordinates and shell-profile')
    if args.present_race_only and not args.present_race_trials:
        parser.error('present-race-only requires present-race-trials')
    if args.present_race_trials and (args.allow_other_displays or args.benchmark_only):
        parser.error('race checks require isolation and cannot use benchmark-only')
    if args.mode == 'installed' and not (args.integrated or args.worker):
        parser.error('installed mode tests the integrated controller')
    if args.server == 'xvfb' and (args.mode in ('raw', 'ahb', 'installed') or args.server_debug):
        parser.error('raw/AHB DRI3 requires the private lorie server')
    if args.force_flip and (args.server != 'lorie' or args.mode != 'raw'):
        parser.error('force-flip requires raw DRI3 on the private lorie server')
    if args.allow_other_displays and args.soak_seconds:
        parser.error('overlapping displays are supported only for short correctness checks')
    if args.controller_dir:
        sys.path.insert(0, str(args.controller_dir.resolve(strict=True)))
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    sys.exit(gtk(args.out) if args.gtk else worker(args) if args.worker else parent(args))
