#!/data/data/com.termux/files/usr/bin/python
"""Check Firefox/mpv acceleration on a private display, or cancel after startup.

--startup-only stops at Marionette/mpv IPC readiness, before loading any video.
It records a cancellation, never a successful hardware decoding test. Full runs
require a numbered fixture and check actual decoder and GPU use; they do not
replace the browser/compositor pixel and fullscreen qualification suite.
"""
import argparse
import functools
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback

from video_oracle import compare, sha256

PREFIX = Path('/data/data/com.termux/files/usr')
HERE = Path(__file__).resolve().parent
NATIVE = Path.home() / '.local/lib/livecd-native'


class StartupComplete(Exception):
    """End a requested startup-only run through normal cleanup."""


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


probe = module('acceleration_browser_probe', HERE / 'test-browsers.py')
isolation = module('acceleration_isolation', HERE / 'test-fullscreen.py')


def wait_for(check, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.1)
    raise RuntimeError('Timed out waiting for application readiness; see app.log')


def gpu_processes(tag):
    from graphics import process_gpu
    found = []
    for pid in probe.tagged(tag):
        try:
            record = process_gpu(pid)
            if record['turnip_libraries'] and record['kgsl_devices']:
                found.append(record)
        except (OSError, ValueError, UnicodeError):
            pass
    return found


class MPV:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(10)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile('rb')
        self.next_id = 0

    def call(self, *command):
        self.next_id += 1
        self.socket.sendall((json.dumps({'command': command, 'request_id': self.next_id}) + '\n').encode())
        while True:
            line = self.stream.readline()
            if not line:
                raise RuntimeError('mpv IPC closed')
            reply = json.loads(line)
            if reply.get('request_id') == self.next_id:
                if reply.get('error') != 'success':
                    raise RuntimeError('mpv IPC: ' + str(reply))
                return reply.get('data')

    def close(self):
        self.stream.close()
        self.socket.close()


def worker(args):
    sys.path.insert(0, str(NATIVE))
    import acceleration
    tag = 'acceleration-' + args.out.name
    probe.OUT = args.out
    result = {'application': args.application, 'startup_only': args.startup_only,
              'decoder_expectation': 'software' if args.expect_software else 'hardware',
              'display': os.environ['DISPLAY'], 'started': False,
              'hardware_verified': False, 'ok': False, 'command': sys.argv}
    browser = ipc = server = None
    code = 1
    try:
        profile = args.out / 'profile'
        profile.mkdir()
        # Use the installed product launcher, with a fresh profile and a private
        # daemon endpoint. Do not modify the user's managed Firefox profile.
        launcher = args.out / 'launch-app'
        launcher.write_text('#!' + str(PREFIX / 'bin/sh') + '\nexec ' + shlex.join([
            str(PREFIX / 'bin/livecd-accelerate'), 'run', '--profile', args.application,
            '--video', 'on', '--', str(PREFIX / 'bin' / args.application)]) + ' "$@"\n')
        launcher.chmod(0o700)
        if args.application == 'firefox':
            acceleration.firefox_preferences(profile, True, True)
            browser = probe.Firefox(launcher, profile, tag, preserve_prefs=True)
            result['version'] = browser.version
        else:
            path = args.out / 'mpv.sock'
            player = probe.launch([str(launcher), '--idle=yes', '--force-window=yes',
                '--no-terminal', '--audio=no', '--keep-open=yes', '--input-ipc-server=' + str(path),
                '--log-file=' + str(args.out / 'mpv.log'),
                '--msg-level=all=v,ffmpeg=debug'], tag)

            def mpv_ready():
                if player.poll() is not None:
                    raise RuntimeError('mpv exited during startup: ' + str(player.returncode))
                return path.is_socket()

            wait_for(mpv_ready)
            ipc = MPV(path)
            result['version'] = ipc.call('get_property', 'mpv-version')
        result['started'] = True
        print('STARTED', args.application, result['version'], flush=True)
        if args.startup_only:
            raise StartupComplete()

        fixture = json.loads((args.fixtures / 'manifest.json').read_text())
        selected = next(item for item in fixture['fixtures'] if item['name'] == args.case)
        clip = args.fixtures / args.case
        if sha256(clip) != selected['sha256']:
            raise RuntimeError('Fixture hash mismatch')
        if browser:
            result['support'] = browser.chrome("const {Troubleshoot} = ChromeUtils.importESModule("
                "'resource://gre/modules/Troubleshoot.sys.mjs'); return await Troubleshoot.snapshot();")
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(args.fixtures))
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            browser.call('WebDriver:SetTimeouts', script=20000, pageLoad=20000)
            browser.open('http://127.0.0.1:' + str(server.server_port) + '/')
            browser.evaluate("(() => {document.body.innerHTML='';let v=document.createElement('video');"
                "v.src=" + json.dumps('/' + args.case) + ";v.muted=true;v.loop=true;v.autoplay=true;"
                "document.body.append(v);v.play();return true})()")

            def frames():
                state = browser.evaluate("(() => {let v=document.querySelector('video');return {"
                    "frames:v.getVideoPlaybackQuality().totalVideoFrames,error:v.error?.message}})()")
                if state.get('error'):
                    raise RuntimeError(state['error'])
                return state if state['frames'] >= selected['frames'] else None

            result['playback'] = wait_for(frames)
            result['graphics'] = browser.chrome('return window.windowUtils.layerManagerType;')
            if result['graphics'] != 'WebRender':
                raise RuntimeError('Firefox is not using WebRender: ' + str(result['graphics']))
            logs = '\n'.join(path.read_text(errors='replace') for path in args.out.glob('mozilla.log*'))
            # These FFmpegVideoDecoder messages describe successful init and
            # received VA-API frames, rather than just a requested preference.
            vaapi_frames = bool(re.search(r'VA-API frame pts=', logs))
            if args.expect_software:
                if vaapi_frames or 'Using preferred software codec ' + selected['codec'] not in logs:
                    raise RuntimeError('Firefox did not use the expected software fallback')
                result['decoder'] = 'software'
            else:
                if 'VA-API FFmpeg init successful' not in logs or not vaapi_frames:
                    raise RuntimeError('Firefox did not report successful VA-API frame decoding; see mozilla.log*')
                result['decoder'] = 'VA-API'
            browser.screenshot(args.out / 'video.png')
            box = browser.evaluate("(() => {let r=document.querySelector('video').getBoundingClientRect(),"
                "d=devicePixelRatio;return {left:r.left*d,top:r.top*d,width:r.width*d,height:r.height*d}})()")
        else:
            ipc.call('loadfile', str(clip), 'replace')

            def decoded():
                if player.poll() is not None:
                    raise RuntimeError('mpv exited during playback')
                try:
                    frame = ipc.call('get_property', 'estimated-frame-number')
                    return {'last_frame': frame} if frame >= selected['frames'] - 1 else None
                except RuntimeError as error:
                    if 'property unavailable' not in str(error):
                        raise
                    return False

            result['playback'] = wait_for(decoded)
            result['decoder'] = ipc.call('get_property', 'hwdec-current')
            result['vo'] = ipc.call('get_property', 'current-vo')
            if result['decoder'] != 'mediacodec-copy' or result['vo'] != 'gpu-next':
                raise RuntimeError('mpv hardware decoder or GPU output fell back: ' + str(result))
            log = (args.out / 'mpv.log').read_text(errors='replace')
            components = re.findall(r'MediaCodec started successfully: codec = ([\w.]+)', log)
            if not components or any(c.lower().startswith(('omx.google.', 'c2.android.')) for c in components):
                raise RuntimeError('mpv did not identify an Android hardware codec component')
            result['android_codecs'] = components
            ipc.call('screenshot-to-file', str(args.out / 'video.png'), 'video')
            box = {'left': 0, 'top': 0, 'width': selected['width'], 'height': selected['height']}
        result['pixels'] = compare(args.out / 'video.png', box, args.fixtures, selected,
            args.out / 'video-normalized.png')
        if not result['pixels']['ok']:
            raise RuntimeError('Decoded video pixels differ from the numbered reference')
        result['gpu_processes'] = gpu_processes(tag)
        if not result['gpu_processes']:
            raise RuntimeError('No application process holds KGSL with Turnip mapped')
        result.update(status='passed', hardware_verified=not args.expect_software, ok=True)
        code = 0
    except StartupComplete:
        result['status'] = 'cancelled_after_start'
        code = 0
    except (Exception, KeyboardInterrupt) as error:
        traceback.print_exc()
        result.update(status='failed', error=repr(error))
    finally:
        if browser:
            try:
                browser.quit()
            except Exception:
                pass
        if ipc:
            try:
                ipc.call('quit')
            except Exception:
                pass
            ipc.close()
        probe.stop(tag, grace=2)
        # SIGKILL delivery and kernel exit are asynchronous. Wait for tagged
        # processes to disappear before judging cleanup, rather than sampling
        # them in the instant after sending the signal.
        deadline = time.monotonic() + 5
        while probe.tagged(tag) and time.monotonic() < deadline:
            time.sleep(.05)
        if server:
            server.shutdown()
            server.server_close()
        result['remaining_app_processes'] = probe.tagged(tag)
        if result['remaining_app_processes']:
            result.update(status='failed', error='Test application survived cleanup', ok=False)
            code = 1
        (args.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print('RESULT', args.application, result.get('status'), flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application', choices=('firefox', 'mpv'))
    parser.add_argument('--startup-only', action='store_true')
    parser.add_argument('--expect-software', action='store_true', help='Verify Firefox fallback for a codec hidden from VA-API')
    parser.add_argument('--fixtures', type=lambda path: Path(path).resolve())
    parser.add_argument('--case', default='chart-vp9.webm')
    parser.add_argument('--out', required=True, type=lambda path: Path(path).resolve())
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.expect_software and args.application != 'firefox':
        parser.error('--expect-software currently applies to Firefox only')
    if args.worker:
        return worker(args)
    if not args.startup_only and not args.fixtures:
        parser.error('Playback checks require --fixtures; use --startup-only to cancel before playback')
    if not args.startup_only and not (args.fixtures / 'manifest.json').is_file():
        parser.error('Fixture manifest is missing')
    args.out.mkdir(parents=True, exist_ok=False)
    before = isolation.live_state()
    sys.path.insert(0, str(NATIVE))
    from desktop import environment
    from graphics import apply_renderer
    # The resource preload is unrelated to GPU/video. Do not run its health
    # probe or inherit a live session ownership marker in this private test.
    os.environ['LIVECD_RESOURCES_COMPAT'] = '0'
    env = environment('zink')
    for key in ('LIVECD_NATIVE_SESSION', 'XAUTHORITY', 'PULSE_SERVER'):
        env.pop(key, None)
    env.update(LIVECD_FULLSCREEN_TEST=str(args.out), LIVECD_HARDWARE_VIDEO='1',
               LIVECD_FIREFOX_GPU='1', LIVECD_MPV_GPU='1',
               MOZ_LOG='sync,FFmpegVideo:5,PlatformDecoderModule:5',
               MOZ_LOG_FILE=str(args.out / 'mozilla.log'))
    for name in ('config', 'data', 'cache', 'runtime', 'state'):
        path = args.out / name
        path.mkdir(mode=0o700)
        env['XDG_' + name.upper() + ('_DIR' if name == 'runtime' else '_HOME')] = str(path)
    dconf = args.out / 'dconf-profile'
    dconf.write_text('user-db:user\n')
    env['DCONF_PROFILE'] = str(dconf)
    env['TERMUX_VA_SOCKET'] = str(args.out / 'va.sock')
    # No socket or lock belonging to :0 is ever used or removed.
    display = next(n for n in range(71, 100) if not any(path.exists() for path in (
        PREFIX / f'tmp/.X11-unix/X{n}', PREFIX / f'tmp/.X{n}-lock')))
    env['DISPLAY'] = ':' + str(display)
    server = daemon = session = None
    code = 1
    try:
        with (args.out / 'x-server.log').open('w') as log:
            server = subprocess.Popen([str(HERE / 'private-lorie/private-lorie'), env['DISPLAY']],
                env=apply_renderer(env.copy(), 'software'), stdout=log, stderr=log)

        def display_ready():
            if server.poll() is not None:
                raise RuntimeError('Private X server exited; see x-server.log')
            return subprocess.run(['xdpyinfo'], env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5).returncode == 0

        wait_for(display_ready)
        if args.application == 'firefox':
            with (args.out / 'daemon.log').open('w') as log:
                daemon_env = apply_renderer(env.copy(), 'software')
                for key in ('LD_PRELOAD', 'LD_LIBRARY_PATH'):
                    daemon_env.pop(key, None)
                daemon = subprocess.Popen([str(Path.home() /
                    '.local/opt/livecd-native/acceleration/service/bin/termux-va')],
                    env=daemon_env, stdout=log, stderr=log)

            def daemon_ready():
                if daemon.poll() is not None:
                    raise RuntimeError('Private MediaCodec daemon exited; see daemon.log')
                return Path(env['TERMUX_VA_SOCKET']).is_socket()

            wait_for(daemon_ready)
        session = subprocess.Popen(['dbus-run-session', '--', sys.executable, str(Path(__file__).resolve()),
            *sys.argv[1:], '--worker'], env=env, start_new_session=True)
        code = session.wait(timeout=180)
    except (Exception, KeyboardInterrupt) as error:
        print('FAIL', repr(error), flush=True)
        (args.out / 'startup-error.json').write_text(json.dumps({'error': repr(error)}) + '\n')
    finally:
        if session:
            try:
                os.killpg(session.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            isolation.stop(session)
        for process in (daemon, server):
            if process:
                isolation.stop(process)
        for path in (f'.X11-unix/X{display}', f'.X{display}-lock'):
            (PREFIX / 'tmp' / path).unlink(missing_ok=True)
        after = isolation.live_state()
        (args.out / 'isolation.json').write_text(json.dumps(
            {'before': before, 'after': after, 'ok': before == after}, indent=2) + '\n')
        if before != after:
            print('FAIL: Shared desktop/daemon state changed', flush=True)
            code = 1
    return code


if __name__ == '__main__':
    def cancelled(number, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGHUP, cancelled)
    raise SystemExit(main())
