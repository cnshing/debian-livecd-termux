#!/data/data/com.termux/files/usr/bin/python
"""Private-daemon startup pixel proof, opt-out and setup-failure negotiation."""
import argparse
import array
import os
from pathlib import Path
import socket
import struct
import subprocess
import time


def receive(sock, count):
    result = b''
    while len(result) < count:
        part = sock.recv(count - len(result))
        if not part:
            raise EOFError('daemon closed during negotiation')
        result += part
    return result


def negotiate(endpoint, codec, requested, full_range=False):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        sock.connect(str(endpoint))
        if codec == 5 and full_range:
            requested |= 0xC0000000 | (1 << 22) | (13 << 14) | (1 << 6)
        words = [0x444D4400, 3, codec, 3840, 2160, requested]
        if codec in (5, 8):
            words += [40_000_000, 60, 1]
        sock.sendall(struct.pack(f'!{len(words)}I', *words))
        status, mode, length = struct.unpack('!3I', receive(sock, 12))
        assert status == 0, status
        if length >> 31:
            receive(sock, 16)
        name = receive(sock, length & 0x7FFFFFFF)
        if mode == 1:
            with socket.socket(socket.AF_UNIX) as pickup:
                pickup.settimeout(5)
                pickup.connect(b'\0' + name)
                data, ancillary, flags, _ = pickup.recvmsg(12, socket.CMSG_SPACE(4))
                descriptors = []
                for level, kind, content in ancillary:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        values = array.array('i')
                        values.frombytes(content)
                        descriptors += values.tolist()
                try:
                    assert not flags & socket.MSG_CTRUNC and len(descriptors) == 1
                    receive(pickup, 12-len(data))
                finally:
                    for fd in descriptors:
                        os.close(fd)
        return mode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daemon', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    # name, environment, requested transport, codecs (encoders H.264 5 or
    # Baseline 8, decoders H.264 0, VP9 2, VP8 3), expected modes, log proofs
    both = ['AVC=pass HEVC=pass', 'VP8=pass VP9=pass']
    cases = [
        ('qualified', {}, 2, [5, 0, 2, 3], [2, 2, 2, 2], both),
        ('opt-out', {'TVA_SURFACE': '0'}, 2, [5, 0, 2, 3], [0, 1, 1, 1],
         ['AVC=copy HEVC=copy', 'VP8=copy VP9=copy']),
        ('bad-import', {'TVA_TEST_SURFACE_BAD_IMPORT': '1'}, 2, [5, 0, 2, 3], [0, 1, 2, 2],
         ['AVC=copy HEVC=copy', 'VP8=pass VP9=pass']),
        # Swapped chroma on the decoder side fails every decode proof.
        ('bad-decode', {'TVA_TEST_SURFACE_BAD_DECODE': '1'}, 2, [5, 0, 2, 3], [0, 1, 1, 1],
         ['AVC=copy HEVC=copy', 'VP8=copy VP9=copy']),
        ('setup-failure', {'TVA_TEST_SURFACE_SETUP_FAIL': '1'}, 2, [5, 0], [0, 1], both),
        ('legacy-client', {}, 0, [5, 0], [0, 0], both),
        ('full-range', {}, 2, [5, 0], [0, 2], both),
        ('untagged-baseline', {}, 2, [8, 0], [0, 2], both),
    ]
    for name, options, requested, codecs, expected, proofs in cases:
        endpoint = args.out.resolve() / f'{name}.sock'
        logfile = args.out / f'{name}.log'
        env = os.environ.copy()
        for key in ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'TVA_SURFACE',
                    'TVA_TEST_SURFACE_BAD_IMPORT', 'TVA_TEST_SURFACE_BAD_DECODE',
                    'TVA_TEST_SURFACE_SETUP_FAIL', 'TVA_TEST_SURFACE_ANY_COLOUR']:
            env.pop(key, None)
        env.update(options)
        with logfile.open('w') as log:
            proc = subprocess.Popen([str(args.daemon.resolve()), '--sock', str(endpoint)],
                                    env=env, stdout=log, stderr=log)
            try:
                for _ in range(300):
                    if endpoint.exists():
                        break
                    assert proc.poll() is None, logfile.read_text()
                    time.sleep(.1)
                actual = [negotiate(endpoint, codec, requested, name == 'full-range') for codec in codecs]
                assert actual == expected, (name, actual, expected)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        log_text = logfile.read_text()
        for proof in proofs:
            assert proof in log_text, (name, proof, log_text)
        print(f'PASS {name}: codecs {codecs} modes {actual}; startup {" / ".join(proofs)}', flush=True)


if __name__ == '__main__':
    main()
