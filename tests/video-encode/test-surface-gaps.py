#!/data/data/com.termux/files/usr/bin/python
"""Fd-transport cases that the startup proof does not cover, on a private daemon.

decode: H.264 160x90 and odd-sized VP8/VP9 pictures through the decoder
  dma-buf path. The daemon must return an even buffer of at least 96x96 with
  the picture at its origin, bit-exact against FFmpeg's software decoder,
  instead of aborting the session. Older daemons fail here.
colour: every surface-capable encoder (default, Baseline, Main and High
  H.264; HEVC), untagged and tagged, encodes solid colour bars once by copy
  and once through the surface. Each stream is decoded to RGB as its own
  signalling says. A surface session must signal the same colour as copy and
  decode no more than COLOUR_MARGIN worse. Sessions the daemon keeps on copy
  are reported as such. The control run sets TVA_TEST_SURFACE_ANY_COLOUR,
  which lifts the daemon's colour exclusions, and must catch the known-bad
  full-range and untagged Baseline surface sessions, or the check is blind.

Usage: test-surface-gaps.py --daemon PATH --out NEW_DIRECTORY [--only decode|colour]
Needs Android API 29+, stock gralloc and an FFmpeg with libx264 and libvpx.
"""
import argparse
import array
import ctypes as C
import fcntl
import json
import mmap
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import encode_oracle as oracle  # noqa: E402

MAGIC, VERSION = 0x444D4400, 3
DMABUF_FRAME = 0xFFFFFFFD
ENC_UNIT_FORCE_KEY, ENC_UNIT_DMABUF = 0x80000000, 0x20000000
ENC_XFER_COLOR, ENC_XFER_FULL_RANGE = 0x80000000, 0x40000000
NV12 = 0x3231564E
DMA_BUF_IOCTL_SYNC = 0x40086200
SYNC_READ, SYNC_WRITE, SYNC_START, SYNC_END = 1, 2, 0, 4
COLOUR_MARGIN = 4
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + (': ' + detail if detail else ''), flush=True)
    return ok


def receive(sock, count):
    data = b''
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise EOFError(f'daemon closed after {len(data)} of {count} bytes')
        data += part
    return data


class Daemon:
    def __init__(self, binary, directory, env=None):
        self.socket = directory.resolve() / 'daemon.sock'
        self.log_path = directory / 'daemon.log'
        environment = os.environ.copy()
        for key in list(environment):
            if key.startswith(('TVA_', 'TERMUX_VA')) or key in ('LD_PRELOAD', 'LD_LIBRARY_PATH'):
                environment.pop(key)
        environment.update(env or {})
        self.log = self.log_path.open('w')
        self.proc = subprocess.Popen([str(binary.resolve()), '--sock', str(self.socket), '-v', '-t'],
                                     env=environment, stdout=self.log, stderr=self.log)
        for _ in range(600):
            if self.socket.exists():
                return
            if self.proc.poll() is not None:
                break
            time.sleep(.1)
        self.close()
        raise RuntimeError('daemon did not start: ' + self.log_path.read_text()[-2000:])

    def connect(self, words):
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(20)
        sock.connect(str(self.socket))
        sock.sendall(struct.pack(f'!{len(words)}I', *words))
        status, mode, length = struct.unpack('!3I', receive(sock, 12))
        if status:
            sock.close()
            raise RuntimeError(f'handshake status {status}')
        if length >> 31:
            receive(sock, 16)
        receive(sock, length & 0x7FFFFFFF)
        return sock, mode

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()


# ---------------------------------------------------------------- decode

DECODE_CASES = [
    # name, codec id, encoder, visible size, session size the VA client opens
    ('h264-160x90', 0, ['libx264', '-bf', '0', '-g', '10'], (160, 90), (160, 96)),
    ('vp9-161x97', 2, ['libvpx-vp9', '-auto-alt-ref', '0', '-lag-in-frames', '0', '-g', '10'],
     (161, 97), (162, 98)),
    ('vp8-161x95', 3, ['libvpx', '-auto-alt-ref', '0', '-lag-in-frames', '0', '-g', '10'],
     (161, 95), (162, 96)),
    # Unchanged path: an ordinary even picture larger than the minimum.
    ('h264-640x360', 0, ['libx264', '-bf', '0', '-g', '10'], (640, 360), (640, 368)),
]
DECODE_FRAMES = 30
# Snapdragon 855's VP9 decoder rejects pictures under 96 lines in either
# transport (MediaCodec error -10000 before any output). The fd transport
# must fail or succeed exactly as copy does there, not differently.
SAME_AS_COPY = [('vp9-161x95', 2, ['libvpx-vp9', '-auto-alt-ref', '0', '-lag-in-frames', '0', '-g', '10'],
                 (161, 95), (162, 96))]
FMTDESC, SHMFRAME, CAP_FRAME_PTS = 0xFFFFFFFF, 0xFFFFFFFE, 1


def h264_units(data):
    """Picture units with parameter sets split off, as the daemon requires."""
    starts = [match.start() for match in re.finditer(b'\x00\x00\x01', data)]
    starts = [start - 1 if start and data[start - 1] == 0 else start for start in starts]
    nals = [data[left:right] for left, right in zip(starts, starts[1:] + [len(data)])]
    units, picture = [], []
    for nal in nals:
        header = 4 if nal[:4] == b'\0\0\0\1' else 3
        kind = nal[header] & 31
        if kind in (7, 8):
            units.append(('config', nal))
        elif kind != 9:
            # first_mb_in_slice == 0 (ue(v) "1") starts the next picture.
            if kind in (1, 5) and nal[header + 1] & 0x80 and any(
                    (n[4 if n[:4] == b'\0\0\0\1' else 3] & 31) in (1, 5) for n in picture):
                units.append(('picture', b''.join(picture)))
                picture = []
            picture.append(nal)
    if picture:
        units.append(('picture', b''.join(picture)))
    return units


def ivf_units(data):
    header = struct.unpack('<H', data[6:8])[0]
    offset, units = header, []
    while offset + 12 <= len(data):
        size = struct.unpack('<I', data[offset:offset + 4])[0]
        units.append(('picture', data[offset + 12:offset + 12 + size]))
        offset += 12 + size
    return units


def make_clip(out, name, codec, encoder, visible):
    vw, vh = visible
    source = out / f'{name}.{"h264" if codec == 0 else "ivf"}'
    if not source.exists():
        oracle.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'testsrc2=size={(vw + 15) // 16 * 16}x{(vh + 15) // 16 * 16}:rate=30',
                    '-vf', f'crop={vw}:{vh}:0:0:exact=1', '-frames:v', DECODE_FRAMES, '-pix_fmt', 'yuv420p',
                    '-c:v', *encoder, '-f', 'h264' if codec == 0 else 'ivf', source])
    data = source.read_bytes()
    return source, h264_units(data) if codec == 0 else ivf_units(data)


def inline_frames(daemon, codec, session_size, units, pictures):
    """Pictures the copy transport returns for the same units."""
    sock, mode = daemon.connect([MAGIC, VERSION, codec, *session_size, 0])
    caps, frames = 0, 0
    try:
        for _, unit in units:
            sock.sendall(struct.pack('!I', len(unit)) + unit)
        sock.sendall(b'\0' * 4)
        while frames < pictures:
            width, height, size = struct.unpack('!3I', receive(sock, 12))
            if size == FMTDESC:
                caps = height
                receive(sock, 32)
                continue
            if caps & CAP_FRAME_PTS:
                receive(sock, 4)
            receive(sock, size)
            frames += 1
    except (EOFError, OSError):
        pass
    finally:
        sock.close()
    return mode, frames


def dmabuf_frames(daemon, codec, session_size, units, pictures):
    sock, mode = daemon.connect([MAGIC, VERSION, codec, *session_size, 2])
    frames = 0
    try:
        for _, unit in units:
            sock.sendall(struct.pack('!I', len(unit)) + unit)
        sock.sendall(b'\0' * 4)
        while frames < pictures:
            _, _, kind, _ = struct.unpack('!4I', receive(sock, 16))
            _, ancillary, _, _ = sock.recvmsg(1, socket.CMSG_SPACE(4))
            for level, kind_, content in ancillary:
                if level == socket.SOL_SOCKET and kind_ == socket.SCM_RIGHTS:
                    for fd in array.array('i', content):
                        os.close(fd)
            receive(sock, 32)
            frames += 1
    except (EOFError, OSError):
        pass
    finally:
        sock.close()
    return mode, frames


def same_as_copy_case(daemon, out, name, codec, encoder, visible, session_size):
    _, units = make_clip(out, name, codec, encoder, visible)
    pictures = sum(kind == 'picture' for kind, _ in units)
    copy_mode, copy_frames = inline_frames(daemon, codec, session_size, units, pictures)
    fd_mode, fd_frames = dmabuf_frames(daemon, codec, session_size, units, pictures)
    check(f'{name} fd transport matches the copy outcome', copy_mode == 0 and fd_mode == 2 and
          fd_frames == copy_frames, f'copy {copy_frames}/{pictures} frames, fd {fd_frames}/{pictures}')


def decode_case(daemon, out, name, codec, encoder, visible, session_size):
    vw, vh = visible
    source = out / f'{name}.{"h264" if codec == 0 else "ivf"}'
    # crop exact=1 keeps odd sizes; testsrc2 alone rounds them to even.
    oracle.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                f'testsrc2=size={(vw + 15) // 16 * 16}x{(vh + 15) // 16 * 16}:rate=30',
                '-vf', f'crop={vw}:{vh}:0:0:exact=1', '-frames:v', DECODE_FRAMES, '-pix_fmt', 'yuv420p',
                '-c:v', *encoder, '-f', 'h264' if codec == 0 else 'ivf', source])
    reference = oracle.run(['ffmpeg', '-v', 'error', '-i', source, '-f', 'rawvideo',
                            '-pix_fmt', 'yuv420p', '-']).stdout
    cw, ch = (vw + 1) // 2, (vh + 1) // 2
    frame_size = vw * vh + 2 * cw * ch
    if not check(f'{name} software reference', len(reference) == frame_size * DECODE_FRAMES,
                 f'{len(reference)} bytes'):
        return
    data = source.read_bytes()
    units = h264_units(data) if codec == 0 else ivf_units(data)
    pictures = sum(kind == 'picture' for kind, _ in units)
    sock, mode = daemon.connect([MAGIC, VERSION, codec, *session_size, 2])
    if not check(f'{name} negotiates the fd transport', mode == 2, f'mode {mode}'):
        sock.close()
        return
    try:
        for _, unit in units:
            sock.sendall(struct.pack('!I', len(unit)) + unit)
        sock.sendall(b'\0' * 4)
        frames, layouts, mismatches, worst = 0, set(), [], 0
        for _ in range(pictures):
            width, height, kind, pts = struct.unpack('!4I', receive(sock, 16))
            if kind != DMABUF_FRAME:
                raise RuntimeError(f'unexpected frame header {width}x{height} {kind:#x}')
            _, ancillary, flags, _ = sock.recvmsg(1, socket.CMSG_SPACE(4))
            fds = array.array('i')
            for level, kind_, content in ancillary:
                if level == socket.SOL_SOCKET and kind_ == socket.SCM_RIGHTS:
                    fds.frombytes(content)
            if flags & socket.MSG_CTRUNC or len(fds) != 1:
                raise RuntimeError('frame descriptor missing')
            fd = fds[0]
            try:
                meta = struct.unpack('!8I', receive(sock, 32))
                layouts.add((width, height, meta[3]))
                ok_layout = (meta[0] == NV12 and meta[1] == width and meta[2] == height and
                             width >= max(96, vw) and height >= max(96, vh) and not (width | height) & 1)
                if not ok_layout:
                    mismatches.append((pts, 'layout', width, height, meta))
                    continue
                view = mmap.mmap(fd, meta[5], prot=mmap.PROT_READ)
                fcntl.ioctl(fd, DMA_BUF_IOCTL_SYNC, struct.pack('Q', SYNC_START | SYNC_READ))
                try:
                    y = b''.join(view[r * meta[3]:r * meta[3] + vw] for r in range(vh))
                    uv = [view[meta[4] + r * meta[3]:meta[4] + r * meta[3] + 2 * cw] for r in range(ch)]
                finally:
                    fcntl.ioctl(fd, DMA_BUF_IOCTL_SYNC, struct.pack('Q', SYNC_END | SYNC_READ))
                    view.close()
                got = y + b''.join(row[0::2] for row in uv) + b''.join(row[1::2] for row in uv)
                index = pts - 1
                want = reference[index * frame_size:(index + 1) * frame_size]
                frames += 1
                if got != want:
                    diff = max(abs(a - b) for a, b in zip(got, want)) if len(want) == len(got) else 255
                    worst = max(worst, diff)
                    mismatches.append((pts, 'pixels', diff))
            finally:
                os.close(fd)
    finally:
        sock.close()
    check(f'{name} returns every picture bit-exact in a padded buffer',
          frames == pictures and not mismatches,
          f'{frames}/{pictures} frames, buffers {sorted(layouts)}, '
          f'{len(mismatches)} mismatches (worst {worst}) {mismatches[:3]}')


def run_decode(args):
    out = args.out / 'decode'
    out.mkdir()
    daemon = Daemon(args.daemon, out)
    try:
        log = daemon.log_path.read_text()
        for runner, case in [(decode_case, c) for c in DECODE_CASES] + [(same_as_copy_case, c) for c in SAME_AS_COPY]:
            try:
                runner(daemon, out, *case)
            except Exception as error:  # a crashed session is a failed case
                check(f'{case[0]} session', False, f'{type(error).__name__}: {error}')
            if daemon.proc.poll() is not None:
                check('daemon survives', False, f'exit {daemon.proc.returncode}')
                break
        time.sleep(.5)
        log = daemon.log_path.read_text()
        check('VP8/VP9 decoders earn their own startup proof',
              'surface decoder pixel qualification: VP8=pass VP9=pass' in log,
              next((line for line in log.splitlines() if 'decoder pixel qualification' in line), 'no line'))
    finally:
        daemon.close()


# ---------------------------------------------------------------- colour

WIDTH, HEIGHT, COLOUR_FRAMES = 640, 384, 8
ENCODERS = [(5, 'h264', 'h264-default'), (8, 'h264', 'h264-baseline'), (9, 'h264', 'h264-main'),
            (10, 'h264', 'h264-high'), (6, 'hevc', 'hevc-main')]
# name, source matrix, full range, transport-word colour bits
TAGS = [('untagged', 'bt601', False, 0),
        ('bt709-limited', 'bt709', False, ENC_XFER_COLOR | (1 << 22) | (1 << 14) | (1 << 6)),
        ('bt709-full', 'bt709', True,
         ENC_XFER_COLOR | ENC_XFER_FULL_RANGE | (1 << 22) | (1 << 14) | (1 << 6))]
# The daemon keeps these on copy: full range failed browser colour checks,
# untagged Baseline failed them too, and this test measured every other
# untagged profile 24 codes off through the surface (2026-11-24).
KNOWN_BAD = {(name, tag) for _, _, name in ENCODERS for tag in ('untagged', 'bt709-full')}
# BT.709 and SMPTE 170M transfer functions are the same curve, and decoding to
# RGB ignores the transfer: compare the fields that change the picture.
SIGNALLED = ('color_range', 'color_space', 'color_primaries')


class Gralloc:
    """One linear NV12 AHardwareBuffer exported as a dma-buf, like a VA surface."""

    class Desc(C.Structure):
        _fields_ = [('width', C.c_uint32), ('height', C.c_uint32), ('layers', C.c_uint32),
                    ('format', C.c_uint32), ('usage', C.c_uint64), ('stride', C.c_uint32),
                    ('rfu0', C.c_uint32), ('rfu1', C.c_uint64)]

    class Plane(C.Structure):
        _fields_ = [('data', C.c_void_p), ('pixel', C.c_uint32), ('row', C.c_uint32)]

    def __init__(self, width, height):
        Plane = self.Plane

        class Planes(C.Structure):
            _fields_ = [('count', C.c_uint32), ('planes', Plane * 4)]
        android = C.CDLL('/system/lib64/libandroid.so')
        window = C.CDLL('/system/lib64/libnativewindow.so')
        android.AHardwareBuffer_allocate.argtypes = [C.POINTER(self.Desc), C.POINTER(C.c_void_p)]
        android.AHardwareBuffer_lockPlanes.argtypes = [C.c_void_p, C.c_uint64, C.c_int, C.c_void_p,
                                                       C.POINTER(Planes)]
        android.AHardwareBuffer_unlock.argtypes = [C.c_void_p, C.c_void_p]
        android.AHardwareBuffer_release.argtypes = [C.c_void_p]
        window.AHardwareBuffer_getNativeHandle.argtypes = [C.c_void_p]
        window.AHardwareBuffer_getNativeHandle.restype = C.POINTER(C.c_int)
        desc = self.Desc(width, height, 1, 35, 0x100 | 0x200 | 3 | 0x30)
        buffer = C.c_void_p()
        assert android.AHardwareBuffer_allocate(C.byref(desc), C.byref(buffer)) == 0
        planes = Planes()
        assert android.AHardwareBuffer_lockPlanes(buffer, 0x30, -1, None, C.byref(planes)) == 0
        self.pitch = planes.planes[0].row
        self.uv = min(planes.planes[1].data, planes.planes[2].data) - planes.planes[0].data
        assert android.AHardwareBuffer_unlock(buffer, None) == 0
        self.fd = os.dup(window.AHardwareBuffer_getNativeHandle(buffer)[3])
        android.AHardwareBuffer_release(buffer)
        self.size = os.lseek(self.fd, 0, 2)
        self.map = mmap.mmap(self.fd, self.size)
        self.width, self.height = width, height

    def fill(self, nv12):
        w, h = self.width, self.height
        fcntl.ioctl(self.fd, DMA_BUF_IOCTL_SYNC, struct.pack('Q', SYNC_START | SYNC_WRITE))
        for row in range(h):
            self.map[row * self.pitch:row * self.pitch + w] = nv12[row * w:(row + 1) * w]
        for row in range(h // 2):
            start = w * h + row * w
            self.map[self.uv + row * self.pitch:self.uv + row * self.pitch + w] = nv12[start:start + w]
        fcntl.ioctl(self.fd, DMA_BUF_IOCTL_SYNC, struct.pack('Q', SYNC_END | SYNC_WRITE))

    def metadata(self):
        return [NV12, self.width, self.height, self.pitch, self.uv, self.size, 0, 0]

    def close(self):
        self.map.close()
        os.close(self.fd)


def encode(daemon, codec, colour_bits, surface, picture, gralloc, target):
    words = [MAGIC, VERSION, codec, WIDTH, HEIGHT, colour_bits | (2 if surface else 0),
             8_000_000, 30, 1]
    sock, mode = daemon.connect(words)
    packets = []
    try:
        if mode == 2:
            gralloc.fill(picture)
        for index in range(COLOUR_FRAMES):
            key = ENC_UNIT_FORCE_KEY if index == 0 else 0
            if mode == 2:
                sock.sendall(struct.pack('!I', ENC_UNIT_DMABUF | key | 32))
                sock.sendmsg([b'F'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                       array.array('i', [gralloc.fd]))])
                sock.sendall(struct.pack('!8I', *gralloc.metadata()))
            else:
                sock.sendall(struct.pack('!I', key | len(picture)) + picture)
            length, _, _ = struct.unpack('!3I', receive(sock, 12))
            packets.append(receive(sock, length))
        sock.sendall(b'\0' * 4)
    finally:
        sock.close()
    target.write_bytes(b''.join(packets))
    return mode


def colour_run(args, out, env, label):
    out.mkdir()
    daemon = Daemon(args.daemon, out, env)
    gralloc = Gralloc(WIDTH, HEIGHT)
    rows = []
    try:
        for codec, ext, profile in ENCODERS:
            for tag, matrix, full, bits in TAGS:
                picture = oracle.color_bars_nv12(WIDTH, HEIGHT, matrix, full)
                row = {'profile': profile, 'codec': ext, 'tag': tag}
                for transport in ('copy', 'surface'):
                    stream = out / f'{profile}-{tag}-{transport}.{ext}'
                    try:
                        mode = encode(daemon, codec, bits, transport == 'surface', picture, gralloc, stream)
                        _, worst = oracle.bar_errors(stream, WIDTH, HEIGHT)
                        signalled = oracle.stream_color(stream)
                    except Exception as error:
                        mode, worst, signalled = None, None, {'error': f'{type(error).__name__}: {error}'}
                    row[transport] = {'mode': mode, 'worst': worst, 'signalled': signalled}
                rows.append(row)
                copy, surface = row['copy'], row['surface']
                summary = (f"copy error {copy['worst']} {copy['signalled']}, surface mode {surface['mode']} "
                           f"error {surface['worst']} {surface['signalled']}")
                row['same'] = (surface['mode'] == 2 and copy['worst'] is not None and
                               surface['worst'] is not None and
                               surface['worst'] <= copy['worst'] + COLOUR_MARGIN and
                               all(surface['signalled'].get(k) == copy['signalled'].get(k) for k in SIGNALLED))
                row['summary'] = summary
                print(f'{label} {profile} {tag}: {summary}', flush=True)
    finally:
        gralloc.close()
        daemon.close()
    (out / 'results.json').write_text(json.dumps(rows, indent=1))
    return rows


def run_colour(args):
    rows = colour_run(args, args.out / 'colour', {}, 'default')
    for row in rows:
        name = f"colour {row['profile']} {row['tag']}"
        copy, surface = row['copy'], row['surface']
        if copy['worst'] is None:
            check(name, False, 'copy encode failed: ' + row['summary'])
        elif surface['mode'] == 2:
            check(name + ' surface matches copy', row['same'], row['summary'])
        else:
            check(name + ' stays on copy', surface['mode'] == 0 and surface['worst'] is not None,
                  row['summary'])
    controls = colour_run(args, args.out / 'colour-control', {'TVA_TEST_SURFACE_ANY_COLOUR': '1'}, 'control')
    caught = [f"{row['profile']} {row['tag']}" for row in controls
              if (row['profile'], row['tag']) in KNOWN_BAD and not row['same']]
    check('control: lifting the exclusions exposes the known-bad sessions', len(caught) > 0,
          f'caught {caught}')
    unexcluded_bad = [f"{row['profile']} {row['tag']}" for row in controls
                      if (row['profile'], row['tag']) not in KNOWN_BAD and not row['same']]
    print('control: other sessions that differ with exclusions lifted:', unexcluded_bad or 'none', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--daemon', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--only', choices=['decode', 'colour'])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    if args.only in (None, 'decode'):
        run_decode(args)
    if args.only in (None, 'colour'):
        run_colour(args)
    print(f'RESULT {sum(results)}/{len(results)} passed', flush=True)
    sys.exit(0 if results and all(results) else 1)


if __name__ == '__main__':
    main()
