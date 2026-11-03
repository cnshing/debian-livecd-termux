#!/data/data/com.termux/files/usr/bin/python
"""Open a real recovery terminal on X11 with the managed desktop stopped."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from desktop import RUNTIME, STATE, process_identity

assert not (RUNTIME / 'control.sock').exists(), 'Stop the desktop first'
env = dict(os.environ, DISPLAY=':0')
server = subprocess.Popen(['termux-x11', ':0', '-legacy-drawing'], env=env,
                          start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
owner = None


def wait(predicate):
    for _ in range(150):
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError('Standalone terminal timed out')


def window():
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'gnome-terminal'], env=env, text=True, capture_output=True)
    return result.stdout.splitlines()


try:
    wait(lambda: subprocess.run(['xdpyinfo'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
    status = json.loads(subprocess.check_output([str(Path.home() / '.local/bin/livecd-native'), 'terminal', str(Path.home())], text=True))
    assert status['standalone']
    owner = status['pid']
    wid = wait(window)[-1]
    subprocess.run(['xdotool', 'windowfocus', '--sync', wid], env=env, check=True)
    marker = STATE / 'standalone-identity.json'
    marker.unlink(missing_ok=True)
    code = 'import json,os,pathlib;pathlib.Path(' + repr(str(marker)) + ').write_text(json.dumps({"uid":os.getuid(),"cwd":os.getcwd()}))'
    subprocess.run(['xdotool', 'type', '--clearmodifiers', 'python -c ' + shlex.quote(code)], env=env, check=True)
    subprocess.run(['xdotool', 'key', 'Return'], env=env, check=True)
    wait(marker.exists)
    identity = json.loads(marker.read_text())
    assert identity == {'uid': os.getuid(), 'cwd': str(Path.home())}
    subprocess.run(['xdotool', 'type', '--clearmodifiers', 'exit'], env=env, check=True)
    subprocess.run(['xdotool', 'key', 'Return'], env=env, check=True)
    wait(lambda: not window())
    def exited():
        try:
            return process_identity(owner)[0] == 'Z'
        except FileNotFoundError:
            return True
    wait(exited)
    print(json.dumps({'ok': True, 'standalone': status, 'identity': identity, 'owner_exited': True}, indent=2))
finally:
    if owner is not None:
        try:
            os.kill(owner, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if server.poll() is None:
        os.killpg(server.pid, signal.SIGTERM)
        server.wait(timeout=5)
