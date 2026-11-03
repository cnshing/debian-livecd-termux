#!/usr/bin/env python3
"""PC-side acceptance: real native Rust transport, idle blocking and reconnect.

Requires the established SSH/ADB rig, authorized rish and installed reader.
Build source-probe with cargo build in tests/mission-center/source on the phone.
Only the test's own reader is killed; Shizuku and other applications stay up.
"""
from datetime import datetime, timezone
import os
import re
import subprocess
import time

host = os.environ.get('TERMUX_SSH_HOST', 'termux')
serial = os.environ.get('PHONE_SERIAL') or os.environ.get('ANDROID_SERIAL')
adb_command = ['adb'] + (['-s', serial] if serial else [])


def adb(command):
    return subprocess.check_output(adb_command + ['shell', command], text=True).strip()


def readers():
    result = subprocess.run(adb_command + ['shell', 'pidof stat-reader-v1'], capture_output=True, text=True)
    return set(result.stdout.split())


print('Collected', datetime.now(timezone.utc).isoformat(), flush=True)
assert not readers(), 'Stop Mission Center before running this isolated reader test'
reference_before = adb('head -1 /proc/stat')
command = 'cd ~/debian-livecd-termux; echo native_uid=$(id -u); exec tests/mission-center/source/target/debug/source-probe 6'
proc = subprocess.Popen(['ssh', host, command], stdout=subprocess.PIPE, text=True)
lines = []
try:
    for line in proc.stdout:
        print(line.rstrip(), flush=True)
        lines.append(line)
        if line.startswith('request=1 '):
            reference_after = adb('head -1 /proc/stat')
            counters = lambda row: sum(map(int, row.split()[1:9]))
            sample = line[line.index('cpu  '):]
            assert counters(reference_before) <= counters(sample) <= counters(reference_after)
            print('reference_before=' + reference_before, flush=True)
            print('reference_after=' + reference_after, flush=True)
            pids = readers()
            assert len(pids) == 1
            pid = pids.pop()
            identity = adb(f'ps -AZ -p {pid}')
            print(identity, flush=True)
            assert 'shell' in identity
            before = adb(f'cat /proc/{pid}/io')
            time.sleep(0.7)
            after = adb(f'cat /proc/{pid}/io')
            assert before == after, 'reader performed I/O without a refresh request'
            print(f'idle_reader_pid={pid} io_unchanged=true wait={adb(f"cat /proc/{pid}/wchan")}', flush=True)
        if line.startswith('request=2 '):
            assert readers() == {pid}, 'reader was not persistent'
            adb(f'kill -TERM {pid}')
            print(f'injected_disconnect_pid={pid}', flush=True)
    assert proc.wait(timeout=10) == 0
finally:
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=10)
samples = [line for line in lines if line.startswith('request=')]
assert len(samples) == 6
assert 'error=' in samples[2], 'disconnect was not surfaced'
assert all('latency_us=' in samples[i] for i in [0, 1, 3, 4, 5]), 'reconnect failed'
assert all(re.search(r'cores=[1-9]', samples[i]) for i in [0, 1, 3, 4, 5])
for _ in range(30):
    if not readers():
        break
    time.sleep(0.1)
assert not readers(), 'reader leaked after client exit'
print('PASS real counters, persistent reader, idle blocking, explicit error, reconnect and cleanup')
