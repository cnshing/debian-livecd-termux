#!/data/data/com.termux/files/usr/bin/python
"""Native GNOME owner: private profile, session buses, display/audio, and cleanup."""
import argparse
import ast
import fcntl
import functools
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

from graphics import apply_renderer, preferred_renderer
from integrations import Integrations

PREFIX = Path('/data/data/com.termux/files/usr')
BASE = Path.home() / '.local/lib/livecd-native'
ROOT = Path.home() / '.local/opt/livecd-native/gnome-48'
RESOURCE_PRELOAD = PREFIX / 'lib/libandroid-procfs.so'
RESOURCE_COMMANDS = PREFIX / 'libexec/android-procfs/bin'
ACCELERATION = Path.home() / '.local/opt/livecd-native/acceleration'
CAMERA = PREFIX / 'bin/android-v4l2'
CAMERA_PRELOAD = PREFIX / 'lib/android-v4l2/libandroid-v4l2.so'
STATE = Path.home() / '.local/state/livecd-native'
DATA = Path.home() / '.local/share/livecd-native'
CONFIG = Path.home() / '.config/livecd-native'
COMMON = Path.home() / '.local/state/livecd'
RUNTIME = Path(os.environ.get('TMPDIR', str(PREFIX / 'tmp'))) / 'livecd-host'
ENDPOINT = RUNTIME / 'control.sock'
DISPLAY = ':0'
SESSION_LOG_START = b'=== livecd-native session start ===\n'


def process_identity(pid):
    parts = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return parts[0], parts[19]


def request(mode, **values):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(15)
        client.connect(str(ENDPOINT))
        client.sendall((json.dumps({'mode': mode, **values}) + '\n').encode())
        result = json.loads(client.makefile('rb').readline(65537))
    if not result.get('ok'):
        raise RuntimeError(result.get('error', 'Desktop request failed'))
    return result


@functools.lru_cache(maxsize=None)
def probe_preload(preload):
    probe = [str(PREFIX / 'bin/node'), '-e', '0'] if (PREFIX / 'bin/node').exists() else [sys.executable, '-c', '0']
    try:
        return subprocess.run(probe, env={**os.environ, 'LD_PRELOAD': preload}, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def preload_works(library, others):
    # Every program in the session inherits this, so a library that aborts them must stay out.
    # See docs/resources/README.md#compatibility-boundary.
    if probe_preload(':'.join([str(library), *others])):
        return True
    print(f'Leaving {library} out of the session: a test program failed with it', file=sys.stderr)
    return False


def environment(renderer='software'):
    env = os.environ.copy()
    for key in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS', 'WAYLAND_DISPLAY',
                'SESSION_MANAGER', 'DESKTOP_AUTOSTART_ID', 'GJS_PATH'):
        env.pop(key, None)
    env.update(DISPLAY=DISPLAY, XDG_CONFIG_HOME=str(CONFIG), XDG_DATA_HOME=str(DATA),
        XDG_CACHE_HOME=str(Path.home() / '.cache/livecd-native'),
        XDG_STATE_HOME=str(STATE / 'xdg'), XDG_RUNTIME_DIR=str(RUNTIME / 'native'),
        XDG_DATA_DIRS=f'{ROOT}/share:{PREFIX}/share',
        XCURSOR_PATH=f'{DATA}/icons:{PREFIX}/share/icons',
        XDG_CONFIG_DIRS=str(PREFIX / 'etc/xdg'),
        XDG_CURRENT_DESKTOP='GNOME', XDG_SESSION_DESKTOP='livecd-native',
        XDG_MENU_PREFIX='gnome-',
        XDG_SESSION_TYPE='x11', DESKTOP_SESSION='livecd-native',
        PATH=f'{BASE}/bin:{ROOT}/bin:{PREFIX}/bin:/system/bin',
        LD_LIBRARY_PATH=f'{ROOT}/lib:{ROOT}/lib/mutter-16:{ROOT}/lib/gnome-shell:{PREFIX}/lib',
        GI_TYPELIB_PATH=f'{ROOT}/lib/girepository-1.0:{ROOT}/lib/mutter-16:{ROOT}/lib/gnome-shell:{ROOT}/lib/gnome-shell/girepository-1.0:{PREFIX}/lib/girepository-1.0',
        GSETTINGS_SCHEMA_DIR=str(ROOT / 'share/glib-2.0/schemas'),
        GNOME_SHELL_DATADIR=str(ROOT / 'share/gnome-shell'),
        GNOME_SHELL_LIBDIR=str(ROOT / 'lib/gnome-shell'),
        DCONF_PROFILE=str(BASE / 'dconf-profile'),
        GDK_BACKEND='x11', CLUTTER_BACKEND='x11', GSK_RENDERER='cairo',
        GTK_A11Y='none', NO_AT_BRIDGE='1', GVFS_DISABLE_FUSE='1',
        GIO_USE_NETWORK_MONITOR='netlink', LANG='C.UTF-8',
        PULSE_SERVER='unix:' + str(RUNTIME / 'pulse.sock'))
    library = RESOURCE_PRELOAD
    preload = [item for item in env.get('LD_PRELOAD', '').replace(':', ' ').split()
               if Path(item).name not in (library.name, CAMERA_PRELOAD.name)]
    if env.get('ANDROID_PROCFS_COMPAT') != '0' and library.exists() and preload_works(library, preload):
        preload.insert(0, str(library))
        env['PATH'] = f'{RESOURCE_COMMANDS}:' + env['PATH']
    native_encode(env, preload)
    # Last, so the preloads before it see camera paths too; it adds no cost to other paths.
    if camera_enabled() and CAMERA_PRELOAD.exists() and preload_works(CAMERA_PRELOAD, preload):
        preload.append(str(CAMERA_PRELOAD))
    if preload:
        env['LD_PRELOAD'] = ':'.join(preload)
    else:
        env.pop('LD_PRELOAD', None)
    return apply_renderer(env, renderer)


def acceleration_settings():
    try:
        settings = json.loads((CONFIG / 'acceleration.json').read_text())
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        return {}


def camera_enabled():
    try:
        options = json.loads((CONFIG / 'integrations.json').read_text())
    except (OSError, ValueError):
        options = {}
    return os.access(CAMERA, os.X_OK) and not (isinstance(options, dict) and options.get('camera') is False)


def camera_status(runtime):
    if not os.access(CAMERA, os.X_OK):
        return {'status': 'not-installed'}
    if not camera_enabled():
        return {'status': 'disabled'}
    try:
        data = json.loads((runtime / 'android-v4l2.json').read_text())
        status = data['status']
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'starting'}
    if status in ('starting', 'ready'):
        try:
            state, birth = process_identity(int(data['pid']))
            alive = state != 'Z' and birth == data.get('start')
        except (OSError, ValueError, TypeError):
            alive = False
        status = status if alive else 'stopped'
    result = {'status': status, 'devices': [{key: device.get(key) for key in ('device', 'name', 'state')}
                                            for device in data.get('devices', [])]}
    if data.get('detail'):
        result['detail'] = data['detail']
    return result


def native_encode(env, preload):
    """Offer hardware encoding and decoding to every program, as Linux does: the GPU
    appears as /dev/dri/renderD128 through the stack's preload and libva finds the
    driver beside it. Both are on unless acceleration.json turns them off."""
    if acceleration_settings().get('native_encode') is False:
        return
    # A selected development stack comes first, then the android-vaapi package.
    stack = (ACCELERATION / 'bionic').resolve()
    if not (stack / 'manifest.json').is_file():
        stack = PREFIX / 'lib/android-vaapi'
    if not (stack / 'manifest.json').is_file():
        return  # The android-vaapi package is not installed.
    try:
        manifest = json.loads((stack / 'manifest.json').read_text())
        library = stack / manifest['session_preload']
        drivers = stack / manifest['driver_directory']
    except (OSError, ValueError, KeyError, TypeError):
        print('Native encoding is on, but the selected Bionic stack has no encoders', file=sys.stderr)
        return
    if not library.is_file() or not preload_works(library, preload):
        return
    preload.append(str(library))
    env['LIBVA_DRIVERS_PATH'] = str(drivers)
    if acceleration_settings().get('native_decode') is False:
        env['TERMUX_VA_DECODE'] = '0'


def start_video_daemon(env):
    # The shared Termux:VA daemon serves both encoding and opt-in decoding. A
    # running one is reused; none is ever stopped here.
    if acceleration_settings().get('native_encode') is False:
        return
    try:
        sys.path.insert(0, str(BASE))
        from acceleration import ensure_daemon
        ensure_daemon(dict(env))
    except (ImportError, OSError, RuntimeError) as error:
        print('Hardware encoding is unavailable: ' + str(error), file=sys.stderr)


def session_environment(renderer=None):
    data = json.loads((STATE / 'session.json').read_text())
    state, birth = process_identity(int(data['pid']))
    if state == 'Z' or birth != data['birth'] or not ENDPOINT.exists():
        raise RuntimeError('The saved native session is no longer active')
    env = environment(renderer or data.get('renderer', 'software'))
    # Only export fields published by this controller; no arbitrary saved env.
    if Path(data['XDG_RUNTIME_DIR']).parent != RUNTIME / 'native':
        raise RuntimeError('Invalid saved native runtime directory')
    for key in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS', 'LIVECD_NATIVE_SESSION', 'XDG_RUNTIME_DIR'):
        env[key] = data[key]
    return env


def bus_call(env, name, path, interface, method, signature=None, values=()):
    from gi.repository import Gio, GLib
    # A direct connection permits callers that did not inherit the desktop bus.
    bus = Gio.DBusConnection.new_for_address_sync(env['DBUS_SESSION_BUS_ADDRESS'],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    try:
        return bus.call_sync(name, path, interface, method,
            GLib.Variant(signature, values) if signature else None, None,
            Gio.DBusCallFlags.NONE, 2500, None).unpack()
    finally:
        bus.close_sync(None)


def shell_pid(env):
    return bus_call(env, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
        'org.freedesktop.DBus', 'GetConnectionUnixProcessID', '(s)', ('org.gnome.Shell',))[0]


def tagged_processes(tag):
    result = {}
    marker = ('LIVECD_NATIVE_SESSION=' + tag).encode()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid == os.getuid() and marker in (proc / 'environ').read_bytes().split(b'\0'):
                state, birth = process_identity(int(proc.name))
                if state != 'Z':
                    result[int(proc.name)] = birth
        except (OSError, ValueError):
            pass
    return result


def cleanup(tag):
    # D-Bus activated processes can detach from the original process group.
    # Match an unguessable inherited tag and PID birth, never executable names.
    for signum, timeout in ((signal.SIGTERM, 6), (signal.SIGKILL, 2)):
        owned = tagged_processes(tag)
        for pid, birth in owned.items():
            try:
                if process_identity(pid)[1] == birth:
                    os.kill(pid, signum)
            except (OSError, ValueError):
                pass
        deadline = time.monotonic() + timeout
        while tagged_processes(tag) and time.monotonic() < deadline:
            time.sleep(0.1)
    remaining = tagged_processes(tag)
    if remaining:
        raise RuntimeError('Owned processes survived cleanup: ' + str(remaining))


def terminal_command(cwd):
    return [str(PREFIX / 'bin/ghostty'), '--gtk-single-instance=false', '--working-directory=' + cwd]


def launch_terminal(env, cwd, emulator='ghostty'):
    if not isinstance(cwd, str) or not cwd.startswith('/') or '\0' in cwd or len(cwd) > 4096 or not Path(cwd).is_dir():
        raise ValueError('Expected an existing absolute native directory')
    if emulator != 'ghostty':
        raise ValueError('Unknown native terminal emulator')
    # As the Terminal overlay's launcher does: Ghostty 1.4 cannot create its surface while GTK
    # also draws through GL on Zink. The terminal itself still renders with OpenGL.
    return subprocess.Popen(terminal_command(cwd), env={**env, 'GSK_RENDERER': 'cairo'}, cwd=cwd, start_new_session=True)


def standalone_terminal(cwd):
    if not Path(cwd).is_dir() or not Path(cwd).is_absolute():
        raise ValueError('Expected an existing absolute native directory')
    env = environment()
    tag = uuid.uuid4().hex
    env['LIVECD_NATIVE_SESSION'] = tag
    runtime = tempfile.TemporaryDirectory(prefix='livecd-terminal-', dir=RUNTIME.parent)
    env['XDG_RUNTIME_DIR'] = runtime.name
    env.pop('DBUS_SYSTEM_BUS_ADDRESS', None)
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    child = subprocess.Popen(['dbus-run-session', '--', *terminal_command(cwd)], env=env)
    try:
        return child.wait()
    finally:
        cleanup(tag)
        runtime.cleanup()


def inner(safe):
    env = os.environ.copy()
    STATE.mkdir(parents=True, exist_ok=True)
    state = {'pid': os.getpid(), 'birth': process_identity(os.getpid())[1],
        'renderer': env.get('LIVECD_NATIVE_RENDERER', 'software'),
        **{k: env[k] for k in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS', 'LIVECD_NATIVE_SESSION', 'XDG_RUNTIME_DIR')}}
    path = STATE / 'session.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(path)
    subprocess.run(['dbus-update-activation-environment', *env.keys()], env=env, check=True,
                   stdout=subprocess.DEVNULL)
    from gi.repository import Gio
    settings = Gio.Settings.new('org.gnome.shell')
    recovery = STATE / 'recovery.json'
    if safe:
        if not recovery.exists():
            previous = settings.get_user_value('disable-user-extensions')
            recovery.write_text(json.dumps({'previous': previous.unpack() if previous is not None else None}))
        settings.set_boolean('disable-user-extensions', True)
    elif recovery.exists():
        previous = json.loads(recovery.read_text())['previous']
        if previous is None:
            settings.reset('disable-user-extensions')
        else:
            settings.set_boolean('disable-user-extensions', previous)
        recovery.unlink()
    Gio.Settings.sync()
    subprocess.Popen(['xdg-user-dirs-update'], env=env).wait()
    if (BASE / 'xsettings.py').exists():
        subprocess.Popen([sys.executable, str(BASE / 'xsettings.py')], env=env)
    # Cameras are published before any application starts. The supervisor and its
    # PipeWire share this session's runtime directory, bus and cleanup tag.
    if not safe and camera_enabled():
        subprocess.Popen([str(CAMERA), 'run'], env=env, stdin=subprocess.DEVNULL, start_new_session=True)
    # The native session is explicitly supervised, without systemd or logind.
    # Session management comes from the source-built gnome-session package.
    manager = PREFIX / 'bin/gnome-session'
    if manager.exists():
        return subprocess.call([str(manager), '--session=livecd-native', '--disable-acceleration-check',
                                '--autostart=' + str(BASE / 'autostart')], env=env)
    return subprocess.call([str(ROOT / 'bin/gnome-shell'), '--x11'], env=env)


def run(safe, renderer='software'):
    for directory in (STATE, COMMON, RUNTIME, RUNTIME / 'native'):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    lock = open(COMMON / 'session.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('A desktop session or setup is already running')
    tag = uuid.uuid4().hex
    renderer = 'software' if safe else renderer
    env = environment(renderer)
    runtime = RUNTIME / 'native' / tag
    runtime.mkdir(mode=0o700)
    env['LIVECD_NATIVE_SESSION'] = tag
    env['XDG_RUNTIME_DIR'] = str(runtime)
    env['DBUS_SYSTEM_BUS_ADDRESS'] = 'unix:path=' + str(runtime / 'system-bus')
    stopping = False

    def stop(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server = socket.socket(socket.AF_UNIX)
    children = []
    integrations = None
    try:
        ENDPOINT.unlink(missing_ok=True)
        if subprocess.run(['xdpyinfo'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            display_command = ['termux-x11', DISPLAY] + (['-legacy-drawing'] if renderer == 'software' else [])
            children.append(subprocess.Popen(display_command, env=env, start_new_session=True))
        deadline = time.monotonic() + 15
        while subprocess.run(['xdpyinfo'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            if stopping or time.monotonic() > deadline:
                raise RuntimeError('Termux:X11 did not become ready')
            time.sleep(0.1)
        subprocess.run([str(PREFIX / 'bin/am'), 'start', '--user', '0', '-n', 'com.termux.x11/.MainActivity'], check=False)
        pulse = RUNTIME / 'pulse.sock'
        pulse.unlink(missing_ok=True)
        audio_env = os.environ.copy()
        audio_env['LIVECD_NATIVE_SESSION'] = tag
        children.append(subprocess.Popen(['pulseaudio', '--daemonize=no', '--exit-idle-time=-1',
            '--use-pid-file=no', '-n', '--load=module-sles-sink',
            # Otherwise the default source is the speaker monitor, which clients record as a microphone.
            '--load=module-null-source source_name=android_no_microphone format=s16le rate=48000 channels=1 description="No microphone"',
            '--load=module-native-protocol-unix socket=' + str(pulse) + ' auth-anonymous=1'], env=audio_env, start_new_session=True))
        deadline = time.monotonic() + 10
        while subprocess.run(['pactl', 'info'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            if children[-1].poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Native PulseAudio did not become ready')
            time.sleep(0.1)
        sinks = subprocess.check_output(['pactl', 'list', 'short', 'sinks'], env=env, text=True)
        if 'OpenSL_ES_sink' not in sinks:
            raise RuntimeError('PulseAudio has no Android output sink')
        bus_config = runtime / 'system.conf'
        bus_config.write_text('<busconfig><type>session</type><auth>EXTERNAL</auth><listen>'
            + env['DBUS_SYSTEM_BUS_ADDRESS'] + '</listen><policy context="default"><allow user="'
            + str(os.getuid()) + '"/><allow own="*"/><allow send_destination="*"/>'
            '<allow receive_sender="*"/></policy></busconfig>')
        children.append(subprocess.Popen(['dbus-daemon', '--nofork', '--nopidfile',
            '--config-file=' + str(bus_config)], env=env, start_new_session=True))
        # Shell and Mission Center read the battery from UPower on this bus, and
        # UPower exits if the bus is not up yet.
        deadline = time.monotonic() + 5
        while not (runtime / 'system-bus').exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        children.append(subprocess.Popen([str(PREFIX / 'libexec/upowerd')], env=env, start_new_session=True))
        start_video_daemon(env)
        desktop = subprocess.Popen(['dbus-run-session', '--', sys.executable, str(BASE / 'desktop.py'),
            '_inner'] + (['--safe'] if safe else []), env=env, start_new_session=True)
        children.append(desktop)
        deadline = time.monotonic() + 75
        while True:
            if desktop.poll() is not None:
                raise RuntimeError('Native GNOME exited during startup')
            if stopping or time.monotonic() > deadline:
                raise RuntimeError('Native GNOME readiness timed out')
            try:
                live_env = session_environment_unchecked()
                pid = shell_pid(live_env)
                # Shell owns its bus name before the UI and extensions exist.
                bus_call(live_env, 'org.gnome.Shell', '/org/gnome/Shell',
                    'org.freedesktop.DBus.Properties', 'Get', '(ss)', ('org.gnome.Shell', 'OverviewActive'))
                # Especially in safe mode, the Shell bus objects precede its
                # startup-complete callback and session registration. Waiting
                # here avoids activating the extension helper during startup.
                if (PREFIX / 'bin/gnome-session').exists() and not bus_call(
                        live_env, 'org.gnome.SessionManager', '/org/gnome/SessionManager',
                        'org.gnome.SessionManager', 'IsSessionRunning')[0]:
                    time.sleep(0.1)
                    continue
                # Query on the desktop's bus, after the extension manager has
                # completed initialization and exported its public interface.
                states = bus_call(live_env, 'org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions',
                    'org.gnome.Shell.Extensions', 'ListExtensions')[0]
                raw = subprocess.check_output(['gsettings', 'get', 'org.gnome.shell', 'enabled-extensions'], env=live_env, text=True)
                expected = ast.literal_eval(raw.removeprefix('@as '))
                disabled = subprocess.check_output(['gsettings', 'get', 'org.gnome.shell', 'disable-user-extensions'], env=live_env, text=True).strip() == 'true'
                # Shell ignores an enabled extension that is not installed, and
                # it would never become active; validate reports it instead.
                if safe or disabled or all(states[key].get('state') == 1 for key in expected if key in states):
                    # Allow Shell's final layout startup callback to complete
                    # before dismissing its initial overview exactly once.
                    time.sleep(0.5)
                    break
            except Exception:
                time.sleep(0.2)
        birth = process_identity(pid)[1]
        from gi.repository import GLib
        bus_call(live_env, 'org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties',
            'Set', '(ssv)', ('org.gnome.Shell', 'OverviewActive', GLib.Variant('b', False)))
        if not safe:
            integrations = Integrations(live_env, STATE, CONFIG)
            integrations.start()
        server.bind(str(ENDPOINT))
        ENDPOINT.chmod(0o600)
        server.listen(5)
        server.settimeout(0.5)
        print('Native desktop ready; owner', os.getpid(), 'Shell', pid, flush=True)
        while not stopping and desktop.poll() is None:
            try:
                state, current = process_identity(pid)
                if state == 'Z' or current != birth:
                    raise RuntimeError('Native GNOME Shell exited')
            except OSError:
                raise RuntimeError('Native GNOME Shell exited')
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            with client:
                client.settimeout(5)
                try:
                    message = json.loads(client.makefile('rb').readline(65537))
                    if not isinstance(message, dict):
                        raise ValueError('Expected a JSON object')
                    mode = message.get('mode')
                    if mode == 'status':
                        result = {'ok': True, 'backend': 'native', 'owner': os.getpid(),
                                  'shell': pid, 'safe': safe, 'tag': tag, 'renderer': renderer,
                                  'integrations': integrations.status() if integrations else {'phase': 'disabled'}}
                        if integrations:
                            result['integrations']['features']['camera'] = camera_status(runtime)
                    elif mode == 'stop':
                        stopping = True
                        result = {'ok': True}
                    elif mode in ('termux', 'terminal'):
                        terminal_env = apply_renderer(live_env.copy(), message['renderer']) if message.get('renderer') else live_env
                        child = launch_terminal(terminal_env, message.get('cwd', str(Path.home())), message.get('emulator', 'ghostty'))
                        children.append(child)
                        result = {'ok': True, 'pid': child.pid}
                    else:
                        raise ValueError('Unsupported native desktop request')
                except (ValueError, OSError, RuntimeError) as exc:
                    result = {'ok': False, 'error': str(exc)}
                try:
                    client.sendall((json.dumps(result) + '\n').encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass
            for child in children:
                child.poll()
    finally:
        try:
            try:
                if integrations:
                    integrations.stop()
            finally:
                cleanup(tag)
        finally:
            for child in children:
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            server.close()
            ENDPOINT.unlink(missing_ok=True)
            (STATE / 'session.json').unlink(missing_ok=True)
            (RUNTIME / 'pulse.sock').unlink(missing_ok=True)
            shutil.rmtree(runtime)


def session_environment_unchecked():
    data = json.loads((STATE / 'session.json').read_text())
    state, birth = process_identity(data['pid'])
    if state == 'Z' or birth != data['birth']:
        raise RuntimeError('Stale native session')
    return {**environment(data.get('renderer', 'software')), **{k: data[k] for k in ('DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS', 'LIVECD_NATIVE_SESSION', 'XDG_RUNTIME_DIR')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status', 'terminal', 'exec', 'validate', 'select', '_run', '_inner', '_standalone'])
    parser.add_argument('--safe', action='store_true')
    parser.add_argument('--emulator', choices=['ghostty'], default='ghostty')
    parser.add_argument('--renderer', choices=['software', 'zink'])
    args, rest = parser.parse_known_args()
    if args.renderer and args.action not in ('start', '_run', 'exec', 'terminal', 'select'):
        parser.error('--renderer applies to start, exec, terminal or select')
    STATE.mkdir(parents=True, exist_ok=True)
    if args.action == '_run':
        return run(args.safe, args.renderer or preferred_renderer())
    if args.action == '_inner':
        return inner(args.safe)
    if args.action == '_standalone':
        return standalone_terminal(rest[0] if rest else str(Path.home()))
    if args.action == 'start':
        renderer = 'software' if args.safe else (args.renderer or preferred_renderer())
        # Validate the private driver before spawning a detached owner.
        apply_renderer({}, renderer)
        try:
            status = request('status')
        except (OSError, RuntimeError):
            status = None
        if status:
            if args.safe and not status.get('safe'):
                raise RuntimeError('Stop the desktop before starting recovery mode')
            if status.get('renderer', 'software') != renderer:
                raise RuntimeError('Stop the desktop before changing its renderer')
            print(json.dumps(status))
            return 0
        with open(STATE / 'session.log', 'ab', buffering=0) as log:
            log.write(SESSION_LOG_START)
            child = subprocess.Popen([sys.executable, str(BASE / 'desktop.py'), '_run', '--renderer', renderer] + (['--safe'] if args.safe else []),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(900):
            if child.poll() is not None:
                raise RuntimeError('Native desktop failed; see ' + str(STATE / 'session.log'))
            try:
                print(json.dumps(request('status')))
                return 0
            except (OSError, RuntimeError):
                time.sleep(0.1)
        raise RuntimeError('Native startup timed out; see session.log')
    if args.action in ('stop', 'status'):
        result = request('status')
        if args.action == 'stop':
            result = request('stop')
            for _ in range(1300):
                if not ENDPOINT.exists():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError('Native shutdown timed out')
        print(json.dumps(result))
    elif args.action == 'terminal':
        cwd = rest[0] if rest else str(Path.home())
        try:
            result = request('terminal', cwd=cwd, emulator=args.emulator, renderer=args.renderer)
        except (FileNotFoundError, ConnectionRefusedError):
            if not Path(cwd).is_dir() or not Path(cwd).is_absolute():
                raise ValueError('Expected an existing absolute native directory')
            with open(STATE / 'terminal.log', 'ab', buffering=0) as log:
                child = subprocess.Popen([sys.executable, str(BASE / 'desktop.py'), '_standalone', cwd],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            result = {'ok': True, 'standalone': True, 'pid': child.pid, 'emulator': 'ghostty'}
        print(json.dumps(result))
    elif args.action == 'select':
        status = request('status')
        if status.get('safe'):
            raise RuntimeError('Start a normal desktop before selecting its renderer as default')
        renderer = status.get('renderer', 'software')
        if args.renderer and args.renderer != renderer:
            raise RuntimeError('Start the requested renderer before selecting it')
        subprocess.run([sys.executable, str(BASE / 'validate.py')], env=session_environment(), check=True)
        path = Path.home() / '.local/lib/livecd/config.json'
        config = json.loads(path.read_text()) if path.exists() else {}
        config['backend'] = 'native'
        config['native_renderer'] = renderer
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(config))
        temporary.chmod(0o600)
        temporary.replace(path)
        print(json.dumps({'selected': 'native', 'renderer': renderer}))
    elif args.action in ('exec', 'validate'):
        command = rest[1:] if rest and rest[0] == '--' else rest
        if args.action == 'validate':
            command = [sys.executable, str(BASE / 'validate.py')]
        if not command:
            raise ValueError('exec requires a command')
        os.execvpe(command[0], command, session_environment(args.renderer))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('livecd-native:', exc, file=sys.stderr)
        sys.exit(1)
