#!/usr/bin/env python3
"""x1s uAPI 11.35 fixture: pending sync file without running a GPU job."""
import argparse
import ctypes
import fcntl
import mmap
import os
import select
import struct
import subprocess


def ioctl(fd, number, payload, direction=1):
    fcntl.ioctl(fd, (direction << 30) | (len(payload) << 16) | 0x8000 | number, payload, True)
    return payload


def atom(jc, number, core, dependency=0):
    data = bytearray(56)
    struct.pack_into('Q', data, 0, jc)
    struct.pack_into('BBBB', data, 36, dependency, 1 if dependency else 0, 0, 0)
    struct.pack_into('B', data, 40, number)
    struct.pack_into('I', data, 44, core)
    return data


def submit(fd, atoms):
    packed = ctypes.create_string_buffer(b''.join(atoms))
    ioctl(fd, 2, bytearray(struct.pack('QII', ctypes.addressof(packed), len(atoms), 56)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('probe')
    parser.add_argument('driver')
    args = parser.parse_args()
    fd = os.open('/dev/mali0', os.O_RDWR | os.O_CLOEXEC)
    version = ioctl(fd, 0, bytearray(4), 3)
    if struct.unpack('HH', version) != (11, 35):
        raise RuntimeError('fixture requires the verified x1s JM uAPI 11.35 / 56-byte v2 layout')
    ioctl(fd, 1, bytearray(4))
    tracking = mmap.mmap(fd, 4096, flags=mmap.MAP_SHARED, prot=0, offset=3 << 12)
    alloc = ioctl(fd, 5, bytearray(struct.pack('QQQQ', 1, 1, 0, 0x200f)), 3)
    _, cookie = struct.unpack_from('QQ', alloc)
    event = mmap.mmap(fd, 4096, flags=mmap.MAP_SHARED,
                      prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=cookie)
    event[0] = 0
    address = ctypes.addressof(ctypes.c_char.from_buffer(event))
    fence = (ctypes.c_int * 2)(-1, -1)
    submit(fd, [atom(address, 1, 0x205), atom(ctypes.addressof(fence), 2, 0x202, 1)])
    sync_fd = fence[0]
    if sync_fd < 0:
        raise RuntimeError('kernel did not return a sync file')
    poll = select.poll()
    poll.register(sync_fd, select.POLLIN)
    try:
        if poll.poll(0):
            raise RuntimeError('fixture already signalled; layout or soft-event control failed')
        result = subprocess.run([args.probe, args.driver, '--pending-fd', str(sync_fd)],
                                pass_fds=(sync_fd,), timeout=2)
        if result.returncode:
            raise RuntimeError(f'pending import probe exited {result.returncode}')
    finally:
        submit(fd, [atom(address, 3, 0x206)])
        events = poll.poll(1000)
        os.close(sync_fd)
        event.close()
        tracking.close()
        os.close(fd)
        if events != [(sync_fd, select.POLLIN)]:
            raise RuntimeError(f'fixture did not signal cleanly after release: {events}')
    print('PASS pending-fence fixture: unsignalled control, import timeout, release control')


if __name__ == '__main__':
    main()
