#!/usr/bin/env python3
"""Measure only the supplied native Mission Center process group via the rig.

Pass GUI, Magpie, rish shell/app_process and reader PIDs explicitly. ADB is
needed for the shell reader's /proc metadata. RSS sums include shared pages.
"""
import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds', type=float, default=60)
parser.add_argument('pids', nargs='+', type=int)
args = parser.parse_args()
serial = os.environ.get('PHONE_SERIAL') or os.environ.get('ANDROID_SERIAL')
adb_command = ['adb'] + (['-s', serial] if serial else [])


def adb(command):
    return subprocess.check_output(adb_command + ['shell', command], text=True).strip()


hz = int(adb('getconf CLK_TCK'))
page_size = int(adb('getconf PAGESIZE'))


def sample():
    result = {}
    for pid in args.pids:
        text = adb(f'cat /proc/{pid}/stat')
        values = text[text.rfind(')') + 2:].split()
        result[pid] = {'name': text[text.find('(') + 1:text.rfind(')')],
                       'birth': int(values[19]), 'ticks': int(values[11]) + int(values[12]),
                       'rss_bytes': int(values[21]) * page_size}
    return result


before = sample()
started = time.monotonic()
time.sleep(args.seconds)
after = sample()
elapsed = time.monotonic() - started
rows = []
for pid in args.pids:
    assert before[pid]['birth'] == after[pid]['birth'], 'Process restarted during measurement'
    rows.append(dict(pid=pid, **after[pid], cpu_percent_one_core=
                     (after[pid]['ticks'] - before[pid]['ticks']) / hz / elapsed * 100))
print(json.dumps({'collected_utc': datetime.now(timezone.utc).isoformat(),
                  'elapsed_seconds': elapsed,
                  'cpu_percent_one_core': sum(row['cpu_percent_one_core'] for row in rows),
                  'rss_bytes_sum': sum(row['rss_bytes'] for row in rows), 'processes': rows}, indent=2))
