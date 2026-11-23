#!/usr/bin/env python3
"""Check large Main10 inputs against a private Termux:VA daemon.

No display or camera is used. Run on Android with the installed ffmpeg:
  python test-main10-4k.py --daemon /path/to/termux-va --out NEW_DIRECTORY
Use --expect-size-rejection with a daemon predating the Main10 frame-cap fix.
That control passes only if its log explicitly rejects the raw frame size.
"""
import argparse
import array
import json
from pathlib import Path
import re
import socket
import struct
import subprocess
import time


FRAME_COUNT = 4


def recv_exact(sock, count):
    result = bytearray()
    while len(result) < count:
        part = sock.recv(count - len(result))
        if not part:
            raise ConnectionError('daemon closed the connection')
        result.extend(part)
    return result


def make_frame(width, height, index):
    # Wide luma bands change each picture, exposing crop, precision and order.
    luma = array.array('H',
                       (((128 + (x * 8 // width) * 96 + index * 64) % 768 + 64) << 6
                        for x in range(width)))
    chroma = array.array('H', ((384 if x % 2 == 0 else 640) << 6
                               for x in range(width)))
    if struct.pack('=H', 1) != b'\x01\x00':
        luma.byteswap()
        chroma.byteswap()
    return luma.tobytes() * height + chroma.tobytes() * (height // 2)


def psnr(out, width, height, swap=False):
    stats = out / ('swapped-psnr.txt' if swap else 'psnr.txt')
    graph = ('[0:v]swapuv[decoded];[decoded][1:v]' if swap else '[0:v][1:v]')
    graph += f'psnr=stats_file={stats.name}:shortest=1'
    subprocess.run([
        'ffmpeg', '-v', 'error', '-c:v', 'hevc', '-i', 'encoded.hevc',
        '-f', 'rawvideo', '-pixel_format', 'p010le', '-video_size', f'{width}x{height}',
        '-i', 'source.p010', '-filter_complex', graph, '-f', 'null', '-'
    ], cwd=out, check=True, stdin=subprocess.DEVNULL)
    values = re.findall(r'psnr_avg:([\d.]+|inf)', stats.read_text())
    assert len(values) == FRAME_COUNT, f'expected four compared pictures: {values}'
    return [float(value) for value in values]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daemon', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--width', type=int, default=3840)
    parser.add_argument('--height', type=int, default=2160)
    parser.add_argument('--expect-size-rejection', action='store_true')
    args = parser.parse_args()
    width, height = args.width, args.height
    if min(width, height) < 96 or (width | height) & 1:
        parser.error('dimensions must be even and at least 96')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    endpoint = out / 'codec.sock'
    if len(str(endpoint).encode()) >= 108:
        parser.error('output path is too long for a Unix socket')
    daemon = args.daemon.resolve()
    flags = []
    rejected = False
    with (out / 'daemon.log').open('w') as log:
        process = subprocess.Popen([str(daemon), '--sock', str(endpoint)],
                                   stdout=log, stderr=log, stdin=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 15
            while not endpoint.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('private daemon did not start; see daemon.log')
                time.sleep(0.1)
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(30)
                sock.connect(str(endpoint))
                sock.sendall(struct.pack('!9I', 0x444D4400, 3, 13, width, height,
                                         0, 40_000_000, 60, 1))
                status, mode, name_length = struct.unpack('!3I', recv_exact(sock, 12))
                assert status == 0, f'handshake refused: {status}'
                recv_exact(sock, (16 if name_length & 0x80000000 else 0)
                           + (name_length & 0x7FFFFFFF))
                with (out / 'source.p010').open('wb') as source, \
                     (out / 'encoded.hevc').open('wb') as encoded:
                    for index in range(FRAME_COUNT):
                        frame = make_frame(width, height, index)
                        source.write(frame)
                        try:
                            sock.sendall(struct.pack('!I', len(frame)
                                                     | (0x80000000 if index in (0, 2) else 0)))
                            sock.sendall(frame)
                            size, flag, unit = struct.unpack('!3I', recv_exact(sock, 12))
                            assert 0 < size <= 8 * 1024 * 1024, size
                            encoded.write(recv_exact(sock, size))
                            flags.append(bool(flag & 1))
                        except (BrokenPipeError, ConnectionError):
                            if not args.expect_size_rejection:
                                raise
                            rejected = True
                            break
                    if not rejected:
                        sock.sendall(struct.pack('!I', 0))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if args.expect_size_rejection:
        expected = f'invalid encoder input frame size: {width * height * 3}'
        assert rejected and not flags and expected in (out / 'daemon.log').read_text()
        print('PASS: old daemon explicitly rejected the large Main10 frame')
        return
    assert flags == [True, False, True, False], flags
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_frames', '-of', 'json',
        str(out / 'encoded.hevc')
    ]))
    stream = probe['streams'][0]
    assert (stream['width'], stream['height'], stream['profile']) == (width, height, 'Main 10')
    assert [bool(frame['key_frame']) for frame in probe['frames']] == flags
    scores = psnr(out, width, height)
    control = psnr(out, width, height, swap=True)
    assert min(scores) > 40, scores
    assert max(control) < 30, control
    result = dict(width=width, height=height, frames=FRAME_COUNT,
                  keyframes=flags, psnr=scores, swapped_chroma_psnr=control)
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS:', json.dumps(result))


if __name__ == '__main__':
    main()
