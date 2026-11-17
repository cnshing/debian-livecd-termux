#!/data/data/com.termux/files/usr/bin/python
"""Attach a preference-following DeX caption helper to debuggable Termux:X11."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

NAME = 'android-legacy-dex-fullscreen'
PREFIX = Path(os.environ.get('PREFIX', '/data/data/com.termux/files/usr'))
FILES = PREFIX / 'libexec' / NAME
STATE = Path.home() / '.local/state' / NAME
APP = 'com.termux.x11'
APPDIR = f'/data/user/0/{APP}/files/{NAME}'


def identity(pid):
    fields = Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()
    return fields[0], fields[19]


def owner():
    try:
        data = json.loads((STATE / 'session.json').read_text())
        state, birth = identity(data['pid'])
        if state != 'Z' and birth == data['start']:
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def supported():
    return subprocess.run(['/system/bin/sh', str(FILES / 'device.sh')],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def shell(script, timeout=8):
    rish = Path(os.environ.get('ANDROID_LEGACY_DEX_RISH',
                              str(Path.home() / '.local/lib/shizuku/rish')))
    if not rish.is_file():
        raise RuntimeError("Export Shizuku's rish into ~/.local/lib/shizuku and authorize Termux.")
    result = subprocess.run(['/system/bin/sh', str(rish), '-c', script],
        env={**os.environ, 'RISH_APPLICATION_ID': 'com.termux', 'RISH_PRESERVE_ENV': '0'},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    output = result.stdout + '\n' + result.stderr
    if result.returncode:
        raise RuntimeError(output.strip()[-1500:] or f'Shizuku shell exited {result.returncode}')
    return output


def record(output):
    # Shizuku+ can print authorization notices and route output through stderr.
    for line in reversed(output.splitlines()):
        try:
            data = json.loads(line)
            if isinstance(data, dict) and 'pid' in data and 'phase' in data:
                return data
        except ValueError:
            pass
    raise RuntimeError('No helper status received from the Shizuku shell: ' + output.strip()[-1000:])


def guard():
    return f'''set -eu
[ "$(id -u)" = 2000 ] || {{ echo 'Shizuku must run as Android shell UID 2000' >&2; exit 1; }}
run-as {APP} id >/dev/null || {{ echo 'Termux:X11 must be debuggable; its APK will not be changed' >&2; exit 1; }}
'''


def payload_id():
    return hashlib.sha256((FILES / 'libdexfullscreen.so').read_bytes()
                          + (FILES / 'helper.dex').read_bytes()).hexdigest()[:20]


def staging():
    """Embed public payload bytes: rish variants may lose piped stdin."""
    parts = [guard(), f'run-as {APP} mkdir -p files/{NAME}/{payload_id()} code_cache\n']
    for source, name in [('libdexfullscreen.so', 'libdexfullscreen.so'), ('helper.dex', 'helper.dex')]:
        data = (FILES / source).read_bytes()
        encoded = base64.b64encode(data).decode()
        digest = hashlib.sha256(data).hexdigest()
        parts.append(f'''base64 -d <<'DEX_PAYLOAD' | run-as {APP} sh -c 'cat > files/{NAME}/{payload_id()}/{name}.new'
{encoded}
DEX_PAYLOAD
actual=$(run-as {APP} sha256sum files/{NAME}/{payload_id()}/{name}.new)
[ "${{actual%% *}}" = {shlex.quote(digest)} ] || {{ echo 'Helper checksum mismatch' >&2; exit 1; }}
run-as {APP} chmod 444 files/{NAME}/{payload_id()}/{name}.new
run-as {APP} mv files/{NAME}/{payload_id()}/{name}.new files/{NAME}/{payload_id()}/{name}
''')
    return ''.join(parts)


def probe():
    output = shell(guard() + f'''printf 'DEXPID=%s\\n' "$(pidof {APP} || true)"
run-as {APP} cat files/{NAME}/status.json 2>/dev/null || true
''')
    pid = None
    for line in output.splitlines():
        if line.startswith('DEXPID='):
            value = line.partition('=')[2].strip()
            if value:
                if not value.isdigit():
                    raise RuntimeError('Ambiguous Termux:X11 process ID')
                pid = int(value)
    try:
        status = record(output)
    except RuntimeError:
        status = None
    return pid, status


def attach(pid):
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError('Invalid app PID')
    payload = f'{APPDIR}/{payload_id()}'
    output = shell(guard() + f'''run-as {APP} touch files/{NAME}/stop
sleep 0.4
run-as {APP} rm -f files/{NAME}/stop files/{NAME}/status.json
am attach-agent {pid} {payload}/libdexfullscreen.so={payload}/helper.dex
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if run-as {APP} test -f files/{NAME}/status.json; then break; fi
    sleep 0.1
done
run-as {APP} cat files/{NAME}/status.json
''')
    status = record(output)
    if status['pid'] != pid or status['phase'] != 'running':
        raise RuntimeError('Runtime helper refused this app/framework: ' + json.dumps(status))
    return status


def detach():
    # Files and loaded agent stay available for a later start; scheduled work stops.
    shell(guard() + f'run-as {APP} touch files/{NAME}/stop\n', timeout=4)


def write_state(data):
    path = STATE / 'session.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data))
    temporary.chmod(0o600)
    temporary.replace(path)


def run():
    if not supported():
        raise RuntimeError('Supported only on Samsung Android 11 ARM64 devices')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('The DeX fullscreen controller is already running')
        stopping = False

        def stop(*_):
            nonlocal stopping
            stopping = True
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        data = {'pid': os.getpid(), 'start': identity(os.getpid())[1], 'phase': 'starting'}
        write_state(data)
        attached = None
        try:
            shell(staging())
            while not stopping:
                pid, current = probe()
                if pid is not None and pid != attached:
                    current = attach(pid)
                    attached = pid
                if pid is None:
                    attached = None
                    current = {'phase': 'waiting-for-termux-x11', 'active': False}
                elif current is None or current.get('pid') != pid or current.get('phase') != 'running':
                    raise RuntimeError('Attached helper stopped: ' + json.dumps(current))
                data.update(phase='ready', helper=current, app_pid=pid)
                write_state(data)
                # Only PID/restart supervision crosses Shizuku; the UI helper runs in-app.
                for _ in range(50):
                    if stopping:
                        break
                    time.sleep(0.1)
        except BaseException as error:
            data.update(phase='failed', error=str(error))
            write_state(data)
            raise
        finally:
            if attached is not None:
                try:
                    detach()
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    print('Could not request helper shutdown: ' + str(error), file=sys.stderr)
            if data['phase'] != 'failed':
                data['phase'] = 'stopped'
                write_state(data)


def start():
    if owner():
        print(json.dumps(owner()))
        return
    if not supported():
        raise RuntimeError('Supported only on Samsung Android 11 ARM64 devices')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'controller.log').open('a') as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run'],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        data = owner()
        if data and data['pid'] == process.pid and data['phase'] == 'ready':
            print(json.dumps(data))
            return
        if process.poll() is not None:
            raise RuntimeError('DeX fullscreen helper failed; see ' + str(STATE / 'controller.log'))
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError('Timed out attaching DeX fullscreen helper; see ' + str(STATE / 'controller.log'))


def stop():
    data = owner()
    if data:
        os.kill(data['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 13
        while owner() and time.monotonic() < deadline:
            time.sleep(0.1)
        if owner():
            raise RuntimeError('Controller shutdown did not finish; check controller.log')
    else:
        # Also allow stopping an agent whose supervisor was killed.
        detach()
    print(json.dumps({'phase': 'stopped'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'start', 'run', 'stop', 'status'])
    args = parser.parse_args()
    try:
        if args.command == 'check':
            if not supported():
                return 1
            shell(guard())
            print(json.dumps({'supported': True}))
        elif args.command == 'status':
            print(json.dumps(owner() or {'phase': 'stopped'}))
        else:
            globals()[args.command]()
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'{NAME}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
