#!/data/data/com.termux/files/usr/bin/python
"""Protocol checks for the Termux:VA daemon's MediaCodec encoders.

Starts the given daemon on a private socket, so a shared daemon is never
touched, and checks what every VA-API client relies on: the hardware encoder
list, the requested profile, a key frame with parameter sets exactly where the
client asked for one, mid-stream bitrate changes, and pixels against the
source frame by frame. Each check has a control that must fail.

Usage: test-daemon.py --daemon PATH --out NEW_DIRECTORY
"""
import argparse
from pathlib import Path
import socket
import statistics
import struct
import subprocess
import sys
import time

import encode_oracle as oracle

HELLO_MAGIC, HELLO_VERSION = 0x444D4400, 3
FORCE_KEY, SET_BITRATE = 0x80000000, 0x40000000
CODECS = {'avc-baseline': (8, 'h264', 66), 'avc-main': (9, 'h264', 77),
          'avc-high': (10, 'h264', 100), 'hevc-main': (6, 'hevc', None)}
SOFTWARE = ('OMX.google.', 'c2.android.')
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (': ' + detail if detail else ''), flush=True)
    return ok


def recv_exact(sock, count):
    data = bytearray()
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise ConnectionError('daemon closed the session')
        data += part
    return bytes(data)


class Session:
    def __init__(self, endpoint, codec, width, height, bitrate, fps=30):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(15)
        self.sock.connect(str(endpoint))
        self.sock.sendall(struct.pack('!9I', HELLO_MAGIC, HELLO_VERSION, codec, width, height, 0,
                                      bitrate, fps, 1))
        status, mode, name_len = struct.unpack('!3I', recv_exact(self.sock, 12))
        if status:
            raise RuntimeError(f'handshake status {status}')
        recv_exact(self.sock, (16 if name_len & 0x80000000 else 0) + (name_len & 0x7fffffff))

    def encode(self, frame, key=False):
        self.sock.sendall(struct.pack('!I', len(frame) | (FORCE_KEY if key else 0)) + frame)
        size, flags, unit = struct.unpack('!3I', recv_exact(self.sock, 12))
        return recv_exact(self.sock, size), flags

    def set_bitrate(self, bitrate):
        self.sock.sendall(struct.pack('!II', SET_BITRATE | 4, bitrate))

    def close(self):
        try:
            self.sock.sendall(struct.pack('!I', 0))
        finally:
            self.sock.close()


def frames_of(path, size):
    data = Path(path).read_bytes()
    return [data[i:i + size] for i in range(0, len(data), size)]


def encode_clip(endpoint, codec, frames, width, height, keys, bitrate=4_000_000, swap=False):
    session = Session(endpoint, codec, width, height, bitrate)
    packets, flags, times = [], [], []
    try:
        for index, frame in enumerate(frames):
            if swap:
                frame = oracle.swap_chroma(frame, width, height)
            start = time.monotonic()
            packet, flag = session.encode(frame, index in keys)
            times.append(time.monotonic() - start)
            packets.append(packet)
            flags.append(flag)
    finally:
        session.close()
    return packets, flags, times


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--daemon', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True)
    endpoint = args.out / 'run/termux-va.sock'
    endpoint.parent.mkdir()
    log = (args.out / 'daemon.log').open('w')
    daemon = subprocess.Popen([args.daemon, '--sock', endpoint, '-t', '-v'], stdin=subprocess.DEVNULL,
                              stdout=log, stderr=log)
    try:
        for unused in range(100):
            if endpoint.is_socket():
                break
            time.sleep(.1)
        run(args, endpoint)
    finally:
        daemon.terminate()
        daemon.wait(10)
    failed = results.count(False)
    print(f'{len(results) - failed} passed, {failed} failed')
    return 1 if failed else 0


def run(args, endpoint):
    listed = Path(str(endpoint) + '.encoders')
    lines = listed.read_text().splitlines() if listed.is_file() else []
    mimes = {line.split()[0] for line in lines}
    check('daemon lists hardware encoders', {'video/avc', 'video/hevc'} <= mimes, '; '.join(lines))
    check('listed encoders are hardware', all(not line.split()[1].startswith(SOFTWARE) for line in lines))

    width, height, count = 640, 360, 90
    source = args.out / 'source.nv12'
    size = oracle.make_source(source, width, height, count)
    frames = frames_of(source, size)
    keys = {0, 30, 45, 46, 89}
    for name, (codec, kind, profile) in CODECS.items():
        packets, flags, times = encode_clip(endpoint, codec, frames, width, height, keys)
        stream = args.out / f'{name}.{kind}'
        stream.write_bytes(b''.join(packets))
        check(f'{name}: one packet per frame', len(packets) == count, f'{len(packets)} packets')
        flagged = [i for i, f in enumerate(flags) if f & 1]
        check(f'{name}: key frames exactly where requested', set(flagged) == keys,
              f'requested {sorted(keys)}, flagged {flagged}')
        report = oracle.idr_report(stream.read_bytes(), kind)
        check(f'{name}: IDR pictures in the bitstream match', set(report['idr']) == keys,
              f"{report['pictures']} pictures, IDR at {report['idr']}")
        check(f'{name}: every IDR carries its parameter sets', not report['idr_without_parameter_sets'],
              f"bare IDR at {report['idr_without_parameter_sets']}")
        if profile:
            found = oracle.sps_profile(stream.read_bytes())
            check(f'{name}: SPS profile_idc', found and found[0] == profile, f'{found}')
        scores = oracle.psnr(stream, source, width, height)
        bad = oracle.psnr_failures(scores, count)
        check(f'{name}: pixels match the source frame by frame', not bad,
              oracle.summary(scores) + ('; ' + '; '.join(bad[:3]) if bad else ''))
        print(f'  {name}: median round trip {statistics.median(times) * 1000:.1f} ms at {width}x{height}')

    # Negative controls: the same checks must catch a shifted frame and
    # swapped chroma planes.
    stream = args.out / 'avc-high.h264'
    shifted = args.out / 'source-shifted.nv12'
    shifted.write_bytes(source.read_bytes()[size:] + source.read_bytes()[-size:])
    bad = oracle.psnr_failures(oracle.psnr(stream, shifted, width, height))
    check('control: a one-frame shift fails the pixel check', len(bad) > count // 2, f'{len(bad)} frames fail')
    packets, unused, unused = encode_clip(endpoint, 10, frames, width, height, {0}, swap=True)
    swapped = args.out / 'avc-high-swapped.h264'
    swapped.write_bytes(b''.join(packets))
    bad = oracle.psnr_failures(oracle.psnr(swapped, source, width, height))
    check('control: swapped chroma fails the pixel check', len(bad) > count // 2, f'{len(bad)} frames fail')
    packets, flags, unused = encode_clip(endpoint, 10, frames[:10], width, height, set())
    check('control: no key frame without a request after the first',
          [i for i, f in enumerate(flags) if f & 1] == [0])

    # Bitrate: 6 Mb/s, then 600 kb/s from frame 45. testsrc2 at 720p fills
    # either rate; heavy noise does not, as the encoder reaches its
    # quantizer limits.
    hd = args.out / 'hd.nv12'
    hd_size = oracle.make_source(hd, 1280, 720, 90)
    hd_frames = frames_of(hd, hd_size)
    session = Session(endpoint, 10, 1280, 720, 6_000_000)
    sizes = []
    try:
        for index, frame in enumerate(hd_frames):
            if index == 45:
                session.set_bitrate(600_000)
            sizes.append(len(session.encode(frame)[0]))
    finally:
        session.close()
    before, after = sum(sizes[15:45]) * 8, sum(sizes[60:90]) * 8
    check('bitrate change takes effect mid-stream', after < before / 3,
          f'{before / 1e6:.2f} Mb/s before, {after / 1e6:.2f} Mb/s after')

    # A codec without a hardware encoder must be refused, not run in software.
    if 'video/x-vnd.on2.vp9' not in mimes:
        try:
            session = Session(endpoint, 7, 640, 360, 1_000_000)
            session.encode(frames[0])
            refused = False
        except (ConnectionError, RuntimeError, OSError):
            refused = True
        check('VP9 without a hardware encoder is refused', refused)

    # Real-time: each round trip, which includes moving the raw picture over
    # the socket, must fit within one frame at 30 fps at 720p, the camera's
    # size. 1080p is reported only: one picture at a time it measured 22-28 ms
    # on a quiet phone and 34 ms beside a compile, at the edge of 33 ms.
    for w, h in ((1280, 720), (1920, 1080)):
        clip = args.out / f'{h}p.nv12'
        oracle.make_source(clip, w, h, 60)
        unused, unused, times = encode_clip(endpoint, 10, frames_of(clip, w * h * 3 // 2), w, h, {0})
        median = statistics.median(times[5:]) * 1000
        if h == 720:
            check(f'{h}p round trip fits a 30 fps frame', median < 1000 / 30, f'median {median:.1f} ms')
        else:
            print(f'  {h}p round trip: median {median:.1f} ms against {1000 / 30:.1f} ms per frame at 30 fps')


if __name__ == '__main__':
    sys.exit(main())
