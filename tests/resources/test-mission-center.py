#!/usr/bin/env python3
"""Smoke-test the installed Mission Center on a private X display and bus."""
import os
from pathlib import Path
import select
import signal
import subprocess
import time

cache = Path.home() / '.cache/livecd-resources'
cache.mkdir(parents=True, exist_ok=True)
reader, writer = os.pipe()
server = subprocess.Popen(['Xvfb', '-displayfd', str(writer), '-screen', '0', '1280x900x24', '-nolisten', 'tcp'],
                          pass_fds=[writer], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.close(writer)
client = None
try:
    assert select.select([reader], [], [], 10)[0], 'Xvfb did not start'
    display = ':' + os.read(reader, 32).decode().strip()
    assert display[1:].isdigit(), display
    env = dict(os.environ, DISPLAY=display, GSETTINGS_BACKEND='memory', GTK_A11Y='none', GDK_BACKEND='x11')
    # Mission Center uses the shared library directly. Exercise it without the
    # compatibility shim so failures cannot be hidden by intercepted file reads.
    preload = env.get('LD_PRELOAD', '')
    env['LD_PRELOAD'] = ':'.join(item for item in preload.replace(' ', ':').split(':') if item and 'liblivecd-proc.so' not in item)
    log = cache / 'mission-center-gui.txt'
    with log.open('w') as output:
        client = subprocess.Popen(['dbus-run-session', '--', 'missioncenter'], env=env,
                                  stdout=output, stderr=output, start_new_session=True)
        time.sleep(8)
        assert client.poll() is None, log.read_text()[-2000:]
        windows = subprocess.check_output(['xdotool', 'search', '--name', 'Mission Center'], env=env, text=True)
        assert windows.strip(), 'Mission Center window missing'
        text = log.read_text()
        assert 'CPU counters unavailable' not in text, text[-2000:]
        assert 'failed to load' not in text.lower(), text[-2000:]
        print('PASS installed Mission Center GUI stays live on a private display; shared Magpie backend, no proc preload')
finally:
    if client is not None:
        try:
            os.killpg(client.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        client.wait(timeout=10)
    os.close(reader)
    server.terminate()
    server.wait(timeout=10)
