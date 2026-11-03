#!/data/data/com.termux/files/usr/bin/python
"""On-device native lifecycle, unrelated-process survival, recovery and exclusion."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from desktop import BASE, STATE, RUNTIME, tagged_processes
from graphics import preferred_renderer

COMMAND = [sys.executable, str(BASE / 'desktop.py')]


def call(*args):
    return json.loads(subprocess.check_output([*COMMAND, *args], text=True))


def stopped(tag):
    assert not tagged_processes(tag), tagged_processes(tag)
    assert not (RUNTIME / 'control.sock').exists()
    assert not (STATE / 'session.json').exists()


def main():
    unrelated = subprocess.Popen(['sleep', '600'])
    try:
        for index in range(10):
            start = time.monotonic()
            status = call('start')
            assert status['backend'] == 'native'
            assert status['renderer'] == preferred_renderer()
            assert call('start')['owner'] == status['owner']
            # Setup uses exactly this shared lock. It must fail while running.
            lock_probe = subprocess.run(['flock', '-n', str(Path.home() / '.local/state/livecd/session.lock'), 'true'])
            assert lock_probe.returncode != 0
            call('stop')
            stopped(status['tag'])
            assert unrelated.poll() is None
            print(json.dumps({'cycle': index + 1, 'renderer': status['renderer'], 'seconds': round(time.monotonic() - start, 3), 'ok': True}), flush=True)
        status = call('start')
        os.kill(status['shell'], signal.SIGKILL)
        for _ in range(200):
            if not (RUNTIME / 'control.sock').exists():
                break
            time.sleep(0.1)
        stopped(status['tag'])
        recovery = call('start', '--safe')
        assert recovery['safe'] and recovery['renderer'] == 'software'
        safe_validation = call('validate')
        assert safe_validation['ok'] and safe_validation['renderer'] == 'software'
        call('stop')
        stopped(recovery['tag'])
        normal = call('start')
        assert not normal['safe'] and normal['renderer'] == preferred_renderer()
        normal_validation = call('validate')
        assert normal_validation['ok']
        call('stop')
        stopped(normal['tag'])
        assert unrelated.poll() is None
        print(json.dumps({'crash_recovery': True, 'safe_normal': True, 'safe_renderer': recovery['renderer'],
            'normal_renderer': normal['renderer'], 'unrelated_process_survived': True}), flush=True)
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


if __name__ == '__main__':
    main()
