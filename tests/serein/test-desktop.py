#!/usr/bin/env python3
"""Exercise the packaged X11/wgpu client with synthetic data on a private display.

Needs Xvfb, xdotool, dbus-run-session and Python GI (GTK3). Never signs in,
joins a call, or opens the microphone. Output is a JSON result, logs and PNGs.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time


CAPTURE = '''
import json, sys, gi
gi.require_version('Gdk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Gdk, GdkX11
window = GdkX11.X11Window.foreign_new_for_display(Gdk.Display.get_default(), int(sys.argv[1]))
_, _, width, height = window.get_geometry()
image = Gdk.pixbuf_get_from_window(window, 0, 0, width, height)
if image is None:
    raise RuntimeError('X11 window readback failed')
image.savev(sys.argv[2], 'png', [], [])
pixels, stride, channels = image.get_pixels(), image.get_rowstride(), image.get_n_channels()
colors = len({bytes(pixels[y * stride + x * channels:y * stride + x * channels + 3])
              for y in range(0, height, max(1, height // 120))
              for x in range(0, width, max(1, width // 160))})
if colors < 100:
    raise RuntimeError(f'Window is blank or incomplete: {colors} sampled colors')
print(json.dumps(dict(width=width, height=height, sampled_colors=colors)))
'''


def stop(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def run(binary, out, backend):
    out.mkdir(parents=True, exist_ok=False)
    result = {'backend': backend, 'checks': {}, 'passed': False}
    server = client = None
    try:
        with tempfile.TemporaryDirectory(prefix='serein-desktop-') as temporary, \
                (out / 'xvfb.log').open('w') as xvfb_log, \
                (out / 'client.log').open('w') as client_log, \
                contextlib.ExitStack() as processes:
            scratch = Path(temporary)
            env = dict(os.environ)
            for name in ('WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS',
                         'SEREIN_DATA_DIR', 'SEREIN_FRAME_DIAGNOSTICS'):
                env.pop(name, None)
            for name, directory in [('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
                                    ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache'),
                                    ('XDG_RUNTIME_DIR', 'runtime')]:
                path = scratch / directory
                path.mkdir(mode=0o700)
                env[name] = str(path)
            env.update(GDK_BACKEND='x11', GSETTINGS_BACKEND='memory',
                       WGPU_BACKEND=backend, LIBGL_ALWAYS_SOFTWARE='1')
            read_fd, write_fd = os.pipe()
            try:
                server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                                           '1280x900x24', '-nolisten', 'tcp', '-ac', '-noreset'],
                                          pass_fds=(write_fd,), env=env, stdout=xvfb_log,
                                          stderr=subprocess.STDOUT, start_new_session=True)
                processes.callback(stop, server)
                os.close(write_fd)
                write_fd = None
                if not select.select([read_fd], [], [], 20)[0]:
                    raise RuntimeError('Private X server did not report a display')
                # Xvfb can write the digits and newline separately. Keep the pipe
                # open through the newline so its final write cannot get EPIPE.
                with os.fdopen(os.dup(read_fd)) as display_pipe:
                    display = display_pipe.readline().strip()
                if not display.isdecimal():
                    raise RuntimeError('Private X server exited before reporting a display')
            finally:
                os.close(read_fd)
                if write_fd is not None:
                    os.close(write_fd)
            env['DISPLAY'] = ':' + display
            geometry = subprocess.run(['xdotool', 'getdisplaygeometry'], env=env,
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      timeout=10, check=True)
            result['checks']['private_display'] = geometry.stdout.strip()
            client = subprocess.Popen(['dbus-run-session', '--', str(binary), '--demo'],
                                      env=env, stdout=client_log, stderr=subprocess.STDOUT,
                                      start_new_session=True)
            processes.callback(stop, client)

            def xdo(*args, check=True):
                return subprocess.run(['xdotool', *args], env=env, text=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      timeout=10, check=check)

            deadline = time.monotonic() + 90
            window = None
            while time.monotonic() < deadline:
                if client.poll() is not None:
                    raise RuntimeError(f'Client exited before showing a window: {client.returncode}')
                windows = xdo('search', '--onlyvisible', '--name', 'Serein', check=False)
                if windows.returncode == 0 and windows.stdout.strip():
                    window = windows.stdout.splitlines()[0]
                    break
                time.sleep(0.25)
            if window is None:
                raise RuntimeError('Client did not show its demo window')
            result['checks']['x11_window'] = True

            def capture(name):
                if client.poll() is not None:
                    raise RuntimeError('Client exited while rendering')
                captured = subprocess.run([sys.executable, '-c', CAPTURE, window, str(out / name)],
                                          env=env, text=True, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, timeout=30, check=True)
                return json.loads(captured.stdout)

            time.sleep(5)
            initial = capture('demo.png')
            result['checks']['rendered_demo'] = initial
            xdo('windowsize', window, '1024', '760')
            time.sleep(3)
            resized = capture('resized.png')
            if (resized['width'], resized['height']) != (1024, 760):
                raise RuntimeError('X11 resize did not reach the rendering window')
            result['checks']['resize'] = resized
            xdo('windowfocus', window)
            xdo('key', '--clearmodifiers', 'ctrl+q')
            if client.wait(timeout=20) != 0:
                raise RuntimeError(f'Client did not exit cleanly: {client.returncode}')
            result['checks']['keyboard_quit'] = True
            result['passed'] = True
    except Exception as error:
        result['error'] = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            result['error_details'] = error.stderr
    finally:
        stop(client)
        stop(server)
        result['checks']['private_processes_stopped'] = all(
            process is None or process.poll() is not None for process in (client, server))
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', default='serein')
    parser.add_argument('--out', type=Path, required=True, help='A new output directory')
    parser.add_argument('--backend', choices=['gl', 'vulkan'], default='gl')
    args = parser.parse_args()
    binary = shutil.which(args.binary)
    if binary is None:
        parser.error('Serein executable not found: ' + args.binary)
    sys.exit(run(Path(binary).resolve(), args.out.resolve(), args.backend))
