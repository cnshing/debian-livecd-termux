#!/data/data/com.termux/files/usr/bin/python
"""Real native terminal identity, literal paths, shell exit and WM close."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path.home() / '.local/lib/livecd-native'))
from desktop import STATE, request, process_identity


def windows():
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--class', 'ghostty'], text=True, capture_output=True)
    return set(result.stdout.splitlines())


def wait(predicate):
    for _ in range(100):
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError('Terminal did not reach the expected state')


def gone(pid):
    try:
        return process_identity(pid)[0] == 'Z'
    except FileNotFoundError:
        return True


def main():
    folder = Path.home() / "Documents/Termux 漢字 'quotes' $(touch LIVECD_SHOULD_NOT_EXIST)"
    folder.mkdir(exist_ok=True)
    records = []
    for action in ('exit', 'windowquit'):
        before = windows()
        result = request('terminal', cwd=str(folder))
        window = next(iter(wait(lambda: windows() - before)))
        subprocess.run(['xdotool', 'windowactivate', '--sync', window], check=True)
        marker = STATE / ('terminal-' + action + '.json')
        marker.unlink(missing_ok=True)
        command = 'python -c ' + __import__('shlex').quote(
            'import json,os,pathlib;pathlib.Path(' + repr(str(marker)) + ').write_text(json.dumps({"cwd":os.getcwd(),"uid":os.getuid(),"shell":os.getppid()}))')
        subprocess.run(['xdotool', 'type', '--clearmodifiers', '--delay', '1', command], check=True)
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        wait(marker.exists)
        identity = json.loads(marker.read_text())
        assert identity['cwd'] == str(folder) and identity['uid'] == os.getuid(), identity
        if action == 'exit':
            subprocess.run(['xdotool', 'type', '--clearmodifiers', 'exit'], check=True)
            subprocess.run(['xdotool', 'key', 'Return'], check=True)
        else:
            subprocess.run(['xdotool', 'windowquit', window], check=True)
        wait(lambda: window not in windows())
        wait(lambda: gone(result['pid']))
        wait(lambda: gone(identity['shell']))
        assert not (Path.home() / 'LIVECD_SHOULD_NOT_EXIST').exists()
        records.append({'action': action, 'identity': identity, 'window_closed': True, 'launcher_exited': True, 'shell_exited': True})
    print(json.dumps({'ok': True, 'checks': records}, indent=2))


if __name__ == '__main__':
    main()
