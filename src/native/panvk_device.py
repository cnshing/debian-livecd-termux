"""Identify the x1s kernel interface used by desktop qualification."""
import fcntl
import os
import struct
import subprocess
import sys


def qualified():
    try:
        uname = os.uname()
        if uname.machine != 'aarch64' or not uname.release.startswith('4.19.87'):
            return False
        device = subprocess.check_output(['/system/bin/getprop', 'ro.product.device'],
                                         text=True, timeout=5).strip()
        if device != 'x1s':
            return False
        fd = os.open('/dev/mali0', os.O_RDWR | os.O_CLOEXEC)
        try:
            version = bytearray(4)
            fcntl.ioctl(fd, (3 << 30) | (4 << 16) | 0x8000, version, True)
            return struct.unpack('HH', version) == (11, 35)
        finally:
            os.close(fd)
    except (OSError, subprocess.SubprocessError):
        return False


if __name__ == '__main__':
    sys.exit(0 if qualified() else 1)
