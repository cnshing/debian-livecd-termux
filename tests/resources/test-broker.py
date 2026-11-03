#!/usr/bin/env python3
"""PC-side real-device test: sharing, zero idle work, recovery and cleanup."""
import json
import os
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


def client():
    child = subprocess.Popen(['ssh', host, 'exec python3 -u ~/debian-livecd-termux/tests/resources/broker-probe.py'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    first = json.loads(child.stdout.readline())
    assert first['error'] == 0, first
    return child, first


def request(child, category):
    child.stdin.write(category + '\n')
    child.stdin.flush()
    result = json.loads(child.stdout.readline())
    print(json.dumps(result), flush=True)
    return result


def stop(child):
    child.stdin.write('quit\n')
    child.stdin.flush()
    assert child.wait(timeout=10) == 0


assert not readers(), 'Stop other Mission Center/resource clients before this isolated test'
clients = []
try:
    first, initial = client()
    clients.append(first)
    second, other = client()
    clients.append(second)
    print(json.dumps({'first': initial, 'second': other}), flush=True)
    pids = readers()
    assert len(pids) == 1, pids
    pid = pids.pop()
    identity = adb(f'ps -AZ -p {pid}')
    assert 'shell' in identity
    print(identity, flush=True)
    for category in ['stat', 'processes', 'processes-v2', 'threads', 'telemetry']:
        assert request(first, category)['error'] == 0
    # The C reader scrubs its token and the Java client has already exited.
    command = adb(f'cat /proc/{pid}/cmdline')
    assert '--connect' in command
    assert not __import__('re').search(r'\b[0-9a-f]{64}\b', command)
    java = adb('ps -A -o PID,ARGS | grep "[s]hizuku.shell.ShizukuShellLoader" || true')
    assert not java, java
    before = adb(f'cat /proc/{pid}/stat; cat /proc/{pid}/io')
    time.sleep(5)
    after = adb(f'cat /proc/{pid}/stat; cat /proc/{pid}/io')
    # stat includes state and scheduling fields that may change independently;
    # CPU ticks and every I/O counter must remain unchanged without a request.
    ticks = lambda text: text.splitlines()[0].rsplit(')', 1)[1].split()[11:13]
    assert ticks(before) == ticks(after)
    assert before.splitlines()[1:] == after.splitlines()[1:]
    print(json.dumps({'idle_seconds': 5, 'reader_cpu_ticks_added': 0, 'reader_io_unchanged': True,
                      'wait': adb(f'cat /proc/{pid}/wchan'), 'java_client_remaining': False}), flush=True)
    for item in ['VmRSS', 'VmSize']:
        print(adb(f'grep {item} /proc/{pid}/status'), flush=True)
    adb(f'kill -TERM {pid}')
    assert request(first, 'stat')['error'] != 0
    time.sleep(1.1)
    assert request(second, 'stat')['error'] == 0
    replacement = readers()
    assert len(replacement) == 1 and replacement != {pid}
    stop(first)
    clients.remove(first)
    assert readers() == replacement
    assert request(second, 'stat')['error'] == 0
    stop(second)
    clients.remove(second)
    for _ in range(30):
        if not readers():
            break
        time.sleep(0.1)
    assert not readers(), 'reader survived its last client'
    print('PASS one shared native reader, Java client exit, zero idle CPU/I/O, reconnect and last-client cleanup')
finally:
    for child in clients:
        child.terminate()
        child.wait(timeout=10)
