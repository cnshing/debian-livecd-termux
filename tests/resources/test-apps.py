#!/usr/bin/env python3
"""Native Termux integration: plain tools under android-procfs-run, no GUI needed."""
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time

cache = Path.home() / '.cache/android-procfs'
cache.mkdir(parents=True, exist_ok=True)

result = subprocess.run(['android-procfs-run', 'ps', '-A', '-o', 'pid,ppid,user,comm'],
                        capture_output=True, text=True, timeout=30, check=True)
assert re.search(r'^\s*1\s+0\s+root\s+', result.stdout, re.M)
assert 'system_server' in result.stdout
processes = len(result.stdout.splitlines()) - 1
assert processes > 100
print(f'PASS stock procps ps: {processes} processes, init and system_server', flush=True)

result = subprocess.run(['android-procfs-run', 'top', '-b', '-n', '2', '-d', '1'],
                        capture_output=True, text=True, timeout=40, check=True)
totals = re.findall(r'Tasks:\s+(\d+) total', result.stdout)
assert len(totals) >= 2 and all(int(value) > 100 for value in totals)
assert 'system_server' in result.stdout
(cache / 'top.txt').write_text(result.stdout)
print(f'PASS stock Android top: {totals} processes across refreshes', flush=True)

# htop is interactive. Give it a private PTY and fresh settings, then quit normally.
with tempfile.TemporaryDirectory(prefix='resources-htop-') as config:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 140, 0, 0))
    env = dict(os.environ, TERM='xterm-256color', XDG_CONFIG_HOME=config)
    child = subprocess.Popen(['android-procfs-run', 'htop', '-d', '10'],
                             stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    output = bytearray()
    started = time.monotonic()
    quit_sent = False
    try:
        while child.poll() is None and time.monotonic() - started < 30:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
            if not quit_sent and time.monotonic() - started > 8:
                os.write(master, b'q')
                quit_sent = True
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
    (cache / 'htop.ansi').write_bytes(output)
    text = re.sub(rb'\x1b(?:\[[0-?]*[ -/]*[@-~]|\([AB0]|[=>])', b'', output).decode(errors='replace')
    assert child.returncode == 0, (child.returncode, text[-1000:])
    assert 'Tasks:' in text and 'thr' in text, text[-1000:]
    assert re.search(r'Tasks:\s*([1-9]\d{2,})', text), text[-1000:]
    assert 'offline' not in text, text[:500]
    print('PASS stock htop: process/thread list, multiple refreshes, clean exit', flush=True)

print(json.dumps({'ps_processes': processes, 'top_processes': totals, 'htop': 'passed'}))
