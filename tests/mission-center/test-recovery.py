#!/usr/bin/env python3
"""PC-side GUI recovery test; temporarily disables the shared resource reader.

Start an isolated native GUI and pass its PID and X11 window ID. The helper
must be idle outside that GUI, and rish must already be authorized.
"""
import argparse
import json
import os
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('gui_pid', type=int)
parser.add_argument('window_id', type=int)
parser.add_argument('--display', default=':9', choices=[':9'])
args = parser.parse_args()
host = os.environ.get('TERMUX_SSH_HOST', 'termux')
serial = os.environ.get('PHONE_SERIAL') or os.environ.get('ANDROID_SERIAL')
adb_command = ['adb'] + (['-s', serial] if serial else [])


def adb(command):
    return subprocess.check_output(adb_command + ['shell', command], text=True).strip()


def ssh(command):
    return subprocess.check_output(['ssh', host, command], text=True).strip()


uid = int(ssh('id -u'))
directory = f'/data/local/tmp/livecd-resources-{uid}'
reader = directory + '/stat-reader-v1'
disabled = directory + '/reader.test-disabled'
pids = adb('pidof stat-reader-v1').split()
assert len(pids) == 1, 'Stop other resource clients before running this isolated test'
before = int(pids[0])
assert 'stat-reader-v1' in adb(f'cat /proc/{before}/comm')


def capture(name):
    ssh(f'DISPLAY={args.display} python3 ~/debian-livecd-termux/tests/mission-center/capture-window.py {args.window_id} "$HOME/.cache/livecd-mission-center/{name}.png"')


ssh(f'DISPLAY={args.display} xdotool windowfocus --sync {args.window_id} key --clearmodifiers alt+1')
adb(f'test ! -e {disabled} && mv {reader} {disabled}')
try:
    adb(f'kill -TERM {before}')
    time.sleep(5)
    capture('unavailable')
    log = ssh('cat ~/.cache/livecd-mission-center/gui-final.log')
    assert 'CPU counters unavailable' in log
    ssh(f'kill -0 {args.gui_pid}')
finally:
    adb(f'mv {disabled} {reader}')
time.sleep(6)
after = adb('pidof stat-reader-v1').split()
assert len(after) == 1 and int(after[0]) != before
ssh(f'kill -0 {args.gui_pid}')
capture('recovered')
print(json.dumps({'gui_pid_unchanged': args.gui_pid, 'reader_before': before,
                  'reader_after': int(after[0]), 'unavailable_state_recorded': True,
                  'reconnected': True}, indent=2))
