#!/data/data/com.termux/files/usr/bin/python
"""Control the focused Termux:X11 DeX window through shell Binder APIs."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
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
REMOTE_PREFIX = f'/data/local/tmp/{NAME}.'
HELPER_CLASS = 'org.livecd.dexfullscreen.Helper'


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
    return """set -eu
[ "$(id -u)" = 2000 ] || { echo 'Shizuku must run as Android shell UID 2000' >&2; exit 1; }
"""


def remote_path(directory):
    if not isinstance(directory, str) or not re.fullmatch(re.escape(REMOTE_PREFIX) + r'[A-Za-z0-9]+', directory):
        raise ValueError('Invalid remote helper session directory')
    return shlex.quote(directory)


def staging():
    """Only public DEX bytes cross rish; no app-private access or attachment."""
    data = (FILES / 'helper.dex').read_bytes()
    encoded = base64.b64encode(data).decode()
    digest = hashlib.sha256(data).hexdigest()
    return guard() + f'''umask 077
directory=$(mktemp -d {REMOTE_PREFIX}XXXXXXXX)
trap 'rm -rf "$directory"' EXIT
base64 -d > "$directory/helper.dex" <<'DEX_PAYLOAD'
{encoded}
DEX_PAYLOAD
actual=$(sha256sum "$directory/helper.dex")
[ "${{actual%% *}}" = {digest} ] || {{ echo 'Helper checksum mismatch' >&2; exit 1; }}
chmod 444 "$directory/helper.dex"
touch "$directory/lease"
printf '{{"pid":0,"phase":"staged","directory":"%s"}}\\n' "$directory"
trap - EXIT
'''


def stage():
    data = record(shell(staging()))
    remote_path(data.get('directory'))
    return data['directory']


def launch(directory):
    path = remote_path(directory)
    shell(guard() + f'''touch {path}/lease
CLASSPATH={path}/helper.dex app_process / {HELPER_CLASS} spawn {path}
''')


def probe(directory):
    path = remote_path(directory)
    output = shell(guard() + f'''touch {path}/lease
if test -f {path}/status.json; then
    if grep -q '\"phase\":\"running\"' {path}/status.json; then
        pid=$(sed -n 's/.*"pid":\\([0-9][0-9]*\\).*/\\1/p' {path}/status.json)
        birth=$(sed -n 's/.*"start":"\\([0-9][0-9]*\\)".*/\\1/p' {path}/status.json)
        proc=$(cat /proc/$pid/stat 2>/dev/null || true)
        proc=${{proc##*) }}
        set -- $proc
        if [ -z "$birth" ] || [ "$#" -lt 20 ] || [ "${{1:-Z}}" = Z ] || [ "${{20:-}}" != "$birth" ]; then
            printf '{{"pid":0,"phase":"failed","detail":"shell-helper-exited"}}\\n'
            exit 0
        fi
    fi
    cat {path}/status.json
else
    printf '{{"pid":0,"phase":"starting"}}\\n'
fi
''')
    return record(output)


def detach(directory):
    path = remote_path(directory)
    output = shell(guard() + f'''if ! test -d {path}; then
    printf '{{"pid":0,"phase":"stopped"}}\\n'
    exit 0
fi
touch {path}/stop
for attempt in $(seq 1 40); do
    if test -f {path}/status.json && grep -q '\"phase\":\"stopped\"' {path}/status.json; then
        cat {path}/status.json
        rm -rf {path}
        exit 0
    fi
    sleep 0.25
done
cat {path}/status.json 2>/dev/null || true
tail -c 2000 {path}/helper.log >&2 || true
exit 1
''', timeout=13)
    status = record(output)
    if status['phase'] != 'stopped':
        raise RuntimeError('Window restoration did not finish: ' + json.dumps(status))


def check():
    directory = stage()
    path = remote_path(directory)
    try:
        status = record(shell(guard() + f'CLASSPATH={path}/helper.dex app_process / {HELPER_CLASS} check\n', timeout=12))
        if status['phase'] != 'checked':
            raise RuntimeError('Window Binder capability check failed')
        return status
    finally:
        shell(guard() + f'rm -rf {path}\n')


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
        directory = None
        try:
            directory = stage()
            data['shell_dir'] = directory
            write_state(data)
            launch(directory)
            deadline = time.monotonic() + 15
            while not stopping:
                current = probe(directory)
                if current['phase'] == 'starting' and time.monotonic() < deadline:
                    time.sleep(0.2)
                    continue
                if current['phase'] != 'running':
                    path = remote_path(directory)
                    detail = shell(guard() + f'tail -c 2000 {path}/helper.log\n')
                    raise RuntimeError('Window Binder helper stopped: ' + json.dumps(current) + '\n' + detail)
                data.update(phase='ready', helper=current)
                write_state(data)
                # The shell helper handles focus/window changes. Renew its lease every 3 s.
                for _ in range(30):
                    if stopping:
                        break
                    time.sleep(0.1)
        except BaseException as error:
            data.update(phase='failed', error=str(error))
            write_state(data)
            raise
        finally:
            restored = True
            if directory is not None:
                try:
                    detach(directory)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    restored = False
                    data.update(phase='failed', error='Window restoration unconfirmed: ' + str(error))
                    write_state(data)
                    print(data['error'], file=sys.stderr)
            if data['phase'] != 'failed' and restored:
                data.update(phase='stopped', helper={'phase': 'stopped', 'active': False})
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
    raise RuntimeError('Timed out starting DeX fullscreen helper; see ' + str(STATE / 'controller.log'))


def stop():
    data = owner()
    if data:
        os.kill(data['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 28
        while owner() and time.monotonic() < deadline:
            time.sleep(0.1)
        if owner():
            raise RuntimeError('Controller shutdown did not finish; check controller.log')
    else:
        # A killed supervisor leaves its directory for explicit cleanup; the lease also expires.
        try:
            previous = json.loads((STATE / 'session.json').read_text())
        except (OSError, ValueError):
            previous = {}
        if previous.get('shell_dir'):
            detach(previous['shell_dir'])
            previous.update(phase='stopped', helper={'phase': 'stopped', 'active': False})
            previous.pop('error', None)
            write_state(previous)
    try:
        final = json.loads((STATE / 'session.json').read_text())
    except (OSError, ValueError):
        final = {}
    if final.get('phase') == 'failed':
        raise RuntimeError(final.get('error', 'Window restoration unconfirmed'))
    print(json.dumps({'phase': 'stopped'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'start', 'run', 'stop', 'status'])
    args = parser.parse_args()
    try:
        if args.command == 'check':
            if not supported():
                return 1
            current = owner()
            print(json.dumps({'supported': True, 'helper': current.get('helper')
                              if current and current['phase'] == 'ready' else check()}))
        elif args.command == 'status':
            data = owner()
            if data is None:
                try:
                    previous = json.loads((STATE / 'session.json').read_text())
                except (OSError, ValueError):
                    previous = {}
                if previous.get('phase') == 'failed':
                    data = previous
                elif previous.get('phase') in ('ready', 'starting'):
                    data = {'phase': 'controller-not-running', 'detail': 'Shell helper lease expires within 15 seconds'}
            print(json.dumps(data or {'phase': 'stopped'}))
        else:
            globals()[args.command]()
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'{NAME}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
