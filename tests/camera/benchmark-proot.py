#!/usr/bin/env python3
"""Measure path-only PRoot overhead without opening an Android camera.

Run in Termux: python benchmark-proot.py --proot /path/to/proot
Uses a regular-file marker bound over /dev/video0, preserves the rest of /dev,
and verifies that VIDIOC_QUERYCAP still fails: a path mapping is not V4L2.
Results include Python loop overhead. They are not a live-camera benchmark.
An unpacked Termux package may also require PROOT_LOADER pointing at its loader.
"""
import argparse
import array
import errno
import fcntl
import json
import mmap
import os
from pathlib import Path
import select
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


MARKER = b'livecd path translation probe\n'


def worker(path, iterations):
    with open(path, 'rb') as stream:
        assert stream.read() == MARKER, 'Bind did not expose the expected file'
        # Linux's struct v4l2_capability is 104 bytes, including reserved fields.
        try:
            fcntl.ioctl(stream.fileno(), 0x80685600, bytearray(104))
        except OSError as exc:
            # Android SELinux may reject this ioctl before the regular-file
            # implementation can return ENOTTY. PRoot bypasses neither check.
            if exc.errno not in (errno.ENOTTY, errno.EACCES, errno.EPERM):
                raise
            querycap = f'{errno.errorcode[exc.errno]}: no V4L2 device'
        else:
            raise RuntimeError('A plain marker unexpectedly answered VIDIOC_QUERYCAP')

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b'x')
    poller = select.poll()
    poller.register(read_fd, select.POLLIN)
    available = array.array('i', [0])
    frame_size = 1280 * 720 * 3 // 2
    frame = b'\x7f' * frame_size
    target = mmap.mmap(-1, frame_size)
    # Fault pages in before timing, as a running stream would already have done.
    target[:] = frame

    def metadata():
        os.stat(path)
        os.close(os.open(path, os.O_RDONLY))

    def ioctl():
        fcntl.ioctl(read_fd, 0x541B, available)  # FIONREAD: a real kernel ioctl

    def poll():
        poller.poll(0)

    def copy():
        target[:] = frame  # A 720p I420-sized copy, with no per-frame syscall.

    timings = {}
    try:
        for name, operation, count in (
                ('stat_open_close_us', metadata, iterations),
                ('kernel_ioctl_us', ioctl, iterations),
                ('ready_poll_us', poll, iterations),
                ('mapped_720p_copy_us', copy, min(iterations, 1000))):
            start = time.perf_counter_ns()
            for _ in range(count):
                operation()
            timings[name] = (time.perf_counter_ns() - start) / count / 1000
        assert available[0] == 1
        assert target[:16] == frame[:16]
    finally:
        target.close()
        os.close(read_fd)
        os.close(write_fd)
    return {'querycap_control': querycap, **timings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proot', default=shutil.which('proot'))
    parser.add_argument('--iterations', type=int, default=2000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.iterations < 1 or args.repeats < 1:
        parser.error('iterations and repeats must be positive')
    if args.worker:
        print(json.dumps(worker(args.worker, args.iterations)))
        return
    if not args.proot:
        parser.error('PRoot is required; pass --proot for an unpacked binary')
    proot = str(Path(args.proot).resolve())
    version = subprocess.run([proot, '--version'], capture_output=True, text=True,
                             check=True, timeout=10).stdout
    results = {mode: [] for mode in ('native', 'proot', 'proot_no_seccomp')}
    script = str(Path(__file__).resolve())
    with tempfile.TemporaryDirectory(prefix='livecd-path-probe-') as directory:
        marker = Path(directory) / 'video0'
        marker.write_bytes(MARKER)
        for repetition in range(args.repeats):
            # Alternate order to reduce systematic warm-up and temperature bias.
            modes = list(results)
            if repetition % 2:
                modes.reverse()
            for mode in modes:
                env = os.environ.copy()
                env.pop('PROOT_NO_SECCOMP', None)
                path = str(marker) if mode == 'native' else '/dev/video0'
                command = [sys.executable, script, '--worker', path,
                           '--iterations', str(args.iterations)]
                if mode != 'native':
                    command = [proot, '-b', f'{marker}:/dev/video0!', *command]
                if mode == 'proot_no_seccomp':
                    env['PROOT_NO_SECCOMP'] = '1'
                start = time.monotonic()
                completed = subprocess.run(command, env=env, capture_output=True,
                                           text=True, timeout=60)
                if completed.returncode:
                    raise RuntimeError(f'{mode} failed: {completed.stderr[-4000:]}')
                row = json.loads(completed.stdout)
                row['whole_process_ms'] = (time.monotonic() - start) * 1000
                row['stderr'] = completed.stderr
                results[mode].append(row)
                print(f'{mode}: repetition {repetition + 1} complete', file=sys.stderr,
                      flush=True)
    timings = [key for key in results['native'][0] if key.endswith(('_us', '_ms'))]
    medians = {mode: {key: statistics.median(row[key] for row in rows)
                      for key in timings} for mode, rows in results.items()}
    print(json.dumps({'proot_version': version, 'iterations': args.iterations,
                      'repeats': args.repeats, 'medians': medians, 'runs': results},
                     indent=2))


if __name__ == '__main__':
    main()
