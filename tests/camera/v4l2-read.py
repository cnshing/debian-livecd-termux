#!/usr/bin/env python3
"""Stream from /dev/videoN with plain V4L2 ioctls, as a C webcam program would.

Run it under the libandroid-v4l2.so preload against camera-node:
    python v4l2-read.py /dev/video0 YUYV 1280 720 150 [expected-card]

It reports the last frame only as luma levels (mean, spread, and the share of
distinct values), never the picture. With camera-node --stamp, the first 8
bytes of each frame hold the sensor timestamp, so this reports
exposure-start-to-application latency. V4L2_READ_TIMEOUT is how many seconds
to wait for a frame, 5 by default.
"""
import ctypes
import fcntl
import os
import resource
import select
import statistics
import struct
import sys
import time


def ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("V") << 8) | nr


QUERYCAP, ENUM_FMT, S_FMT = ioc(2, 0, 104), ioc(3, 2, 64), ioc(3, 5, 208)
REQBUFS, QUERYBUF, QBUF, DQBUF = ioc(3, 8, 20), ioc(3, 9, 88), ioc(3, 15, 88), ioc(3, 17, 88)
STREAMON, STREAMOFF = ioc(1, 18, 4), ioc(1, 19, 4)
CAPTURE, MMAP = 1, 1

libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]


def fourcc(code):
    return struct.unpack("<I", code.encode())[0]


def name(value):
    return struct.pack("<I", value).decode(errors="replace")


def cpu():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def main(dev, want, width, height, frames, expected_card=None):
    fd = os.open(dev, os.O_RDWR)
    cap = bytearray(104)
    fcntl.ioctl(fd, QUERYCAP, cap)
    card = cap[16:48].rstrip(bytes(1)).decode()
    print(f"driver {cap[:16].rstrip(bytes(1)).decode()!r}, card {card!r}, "
          f"caps 0x{struct.unpack_from('<I', cap, 84)[0]:08x}")
    if expected_card and card != expected_card:
        print(f"wrong device: expected {expected_card!r}")
        return 1

    formats = []
    for index in range(32):
        desc = bytearray(64)
        struct.pack_into("<II", desc, 0, index, CAPTURE)
        try:
            fcntl.ioctl(fd, ENUM_FMT, desc)
        except OSError:
            break
        formats.append(name(struct.unpack_from("<I", desc, 44)[0]))
    print("formats:", " ".join(formats))

    fmt = bytearray(208)
    struct.pack_into("<I", fmt, 0, CAPTURE)
    struct.pack_into("<IIII", fmt, 8, width, height, fourcc(want), 1)
    fcntl.ioctl(fd, S_FMT, fmt)
    w, h, pix, _, stride, size = struct.unpack_from("<IIIIII", fmt, 8)
    print(f"set {name(pix)} {w}x{h}, stride {stride}, size {size}")

    req = bytearray(20)
    struct.pack_into("<III", req, 0, 4, CAPTURE, MMAP)
    fcntl.ioctl(fd, REQBUFS, req)
    maps = []
    for index in range(struct.unpack_from("<I", req, 0)[0]):
        buf = bytearray(88)
        struct.pack_into("<II", buf, 0, index, CAPTURE)
        struct.pack_into("<I", buf, 60, MMAP)
        fcntl.ioctl(fd, QUERYBUF, buf)
        offset, length = struct.unpack_from("<I", buf, 64)[0], struct.unpack_from("<I", buf, 72)[0]
        addr = libc.mmap(None, length, 1, 1, fd, offset)  # PROT_READ, MAP_SHARED
        if addr in (None, ctypes.c_void_p(-1).value):
            raise OSError(ctypes.get_errno(), "mmap failed")
        maps.append(addr)
        fcntl.ioctl(fd, QBUF, buf)

    fcntl.ioctl(fd, STREAMON, struct.pack("<I", CAPTURE))
    poller = select.poll()
    poller.register(fd, select.POLLIN)
    latencies, got, first, levels = [], 0, None, None
    cpu0 = cpu()
    while got < frames:
        if not poller.poll(int(float(os.environ.get("V4L2_READ_TIMEOUT", "5")) * 1000)):
            print("timed out waiting for a frame")
            break
        buf = bytearray(88)
        struct.pack_into("<II", buf, 0, 0, CAPTURE)
        struct.pack_into("<I", buf, 60, MMAP)
        fcntl.ioctl(fd, DQBUF, buf)
        now = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        index, _, used = struct.unpack_from("<III", buf, 0)
        stamp = struct.unpack("<q", ctypes.string_at(maps[index], 8))[0]
        if 0 < now - stamp < 10**9:
            latencies.append((now - stamp) / 1e6)
        if first is None:
            first = time.monotonic()
        if got == frames - 1:
            frame = ctypes.string_at(maps[index], used)
            luma = frame[8:2 * w * h:2] if name(pix) == "YUYV" else frame[8:w * h]
            sample = luma[::97]
            levels = (statistics.fmean(sample), statistics.pstdev(sample), len(set(luma)))
        fcntl.ioctl(fd, QBUF, buf)
        got += 1
    elapsed = time.monotonic() - first if first else 0
    used_cpu = cpu() - cpu0
    fcntl.ioctl(fd, STREAMOFF, struct.pack("<I", CAPTURE))
    os.close(fd)

    print(f"frames {got}, {(got - 1) / elapsed:.1f} fps" if got > 1 else f"frames {got}")
    if latencies:
        latencies.sort()
        print(f"exposure start to application: median {latencies[len(latencies) // 2]:.1f} ms, "
              f"min {latencies[0]:.1f}, max {latencies[-1]:.1f}")
    if levels:
        print(f"luma levels: mean {levels[0]:.1f}, spread {levels[1]:.1f}, {levels[2]} distinct values")
    if elapsed:
        print(f"this process CPU: {100 * used_cpu / elapsed:.1f}% of one core")
    return 0 if got == frames else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0], a[1], int(a[2]), int(a[3]), int(a[4]), a[5] if len(a) > 5 else None))
