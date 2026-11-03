#!/data/data/com.termux/files/usr/bin/python
"""The phone camera into the hardware encoder, as Linux programs do it.

Run by test-camera-encode.sh with the camera published as /dev/video0 and the
encoder reachable as /dev/dri/renderD128. FFmpeg, whose libavcodec VA-API
encoders OBS and other programs use, reads the camera in real time and writes
the hardware-encoded stream and the raw camera frames side by side, so each
encoded frame is compared with the very frame the camera gave. Serein's
encoder is then fed camera frames as Serein would feed them.

Usage: test-camera.py --out DIRECTORY
"""
import argparse
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
import time

import encode_oracle as oracle
from serein_encoder import SereinCameraEncoder, drain, rejected

results = []
WIDTH, HEIGHT, FPS, SECONDS = 1280, 720, 30, 10


def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (': ' + detail if detail else ''), flush=True)
    return ok


def is_device(path, major):
    try:
        st = os.stat(path)
        return stat.S_ISCHR(st.st_mode) and os.major(st.st_rdev) == major
    except OSError:
        return False


def live_encode(out, codec, profile):
    """Camera to hardware encoder and to raw frames, in one real-time run."""
    encoded, raw = out / f'camera-{codec}.mp4', out / f'camera-{codec}.nv12'
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    run = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-init_hw_device', 'vaapi=va', '-filter_hw_device', 'va',
         # -t before -i ends the input, and so both outputs.
         '-f', 'v4l2', '-input_format', 'nv12', '-framerate', str(FPS), '-video_size', f'{WIDTH}x{HEIGHT}',
         '-t', str(SECONDS), '-i', '/dev/video0',
         '-filter_complex', '[0:v]split[a][b];[a]hwupload[h]',
         # Passthrough keeps both outputs frame for frame; by default the raw
         # output repeats or drops frames on timestamp jitter.
         '-map', '[h]', '-fps_mode', 'passthrough', '-c:v', codec, '-profile:v', profile, '-b:v', '4M',
         '-g', str(FPS), encoded,
         '-map', '[b]', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'nv12', raw],
        capture_output=True, text=True, timeout=SECONDS * 6)
    wall = time.monotonic() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) / wall * 100
    (out / f'camera-{codec}.log').write_text(run.stderr)
    return run, encoded, raw, wall, cpu


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args()
    check('camera is /dev/video0', is_device('/dev/video0', 81))
    check('encoder is /dev/dri/renderD128', is_device('/dev/dri/renderD128', 226))

    frame = WIDTH * HEIGHT * 3 // 2
    for codec, profile, kind in (('h264_vaapi', 'high', 'h264'), ('hevc_vaapi', 'main', 'hevc')):
        run, encoded, raw, wall, cpu = live_encode(args.out, codec, profile)
        if not check(f'{codec}: live camera encode runs', run.returncode == 0, run.stderr.strip()[-400:]):
            continue
        captured = raw.stat().st_size // frame
        frames = oracle.probe_frames(encoded)
        drops = re.findall(r'drop=\s*(\d+)', run.stderr)
        check(f'{codec}: keeps up with the camera', captured >= SECONDS * FPS * 0.95 and len(frames) == captured,
              f'{captured} frames captured, {len(frames)} encoded in {wall:.1f} s, '
              f'ffmpeg dropped {drops[-1] if drops else "?"}, ffmpeg CPU {cpu:.0f}% of one core')
        keys = [i for i, (key, unused) in enumerate(frames) if key]
        check(f'{codec}: a key frame every {FPS} frames', keys == list(range(0, len(frames), FPS)), f'{keys}')
        scores = oracle.psnr(encoded, raw, WIDTH, HEIGHT)
        bad = oracle.psnr_failures(scores, captured)
        check(f'{codec}: each encoded frame matches the camera frame', not bad,
              oracle.summary(scores) + ('; ' + bad[0] if bad else ''))
        # A player that seeks starts at a later key frame.
        seek = args.out / f'seek-{codec}.nv12'
        oracle.run(['ffmpeg', '-v', 'error', '-y', '-ss', '5', '-i', encoded, '-frames:v', '1',
                    '-f', 'rawvideo', '-pix_fmt', 'nv12', seek])
        reference = args.out / f'reference-{codec}.nv12'
        with raw.open('rb') as f:
            f.seek(5 * FPS * frame)
            reference.write_bytes(f.read(frame))
        scores = oracle.psnr(seek, reference, WIDTH, HEIGHT, raw=True)
        check(f'{codec}: seeking to 5 s decodes the camera frame there', not oracle.psnr_failures(scores, 1),
              oracle.summary(scores))
    # The pixel check must be able to fail on camera content too.
    raw = args.out / 'camera-h264_vaapi.nv12'
    if raw.is_file():
        shifted = args.out / 'camera-shifted.nv12'
        data = raw.read_bytes()
        shifted.write_bytes(data[frame * 15:] + data[-frame * 15:])
        bad = oracle.psnr_failures(oracle.psnr(args.out / 'camera-h264_vaapi.mp4', shifted, WIDTH, HEIGHT))
        check('control: camera frames half a second apart fail the pixel check', len(bad) > 0, f'{len(bad)} frames fail')

    # Serein: camera pictures fitted to 640x480 RGB, encoded at 15 fps.
    rgb = args.out / 'serein-camera.rgb'
    oracle.run(['ffmpeg', '-v', 'error', '-y', '-f', 'v4l2', '-input_format', 'nv12', '-framerate', '30',
                '-video_size', f'{WIDTH}x{HEIGHT}', '-t', '4', '-i', '/dev/video0', '-r', '15',
                '-vf', 'scale=640:360,pad=640:480:0:60', '-f', 'rawvideo', '-pix_fmt', 'rgb24', rgb])
    data, size = rgb.read_bytes(), 640 * 480 * 3
    pictures = [data[i:i + size] for i in range(0, len(data) - size + 1, size)]
    for bit_rate in (600_000, 8_000_000):
        encoder = SereinCameraEncoder(640, 480, 15, bit_rate)
        units, bad = [], []
        try:
            for picture in pictures:
                start = time.monotonic()
                result = encoder.encode(picture)
                if result:
                    if rejected(*result):
                        bad.append(len(units))
                    units.append(result[0])
                time.sleep(max(0, 1 / 15 - (time.monotonic() - start)))
            units += drain(encoder)
        finally:
            encoder.close()
        stream = args.out / f'serein-camera-{bit_rate // 1000}k.h264'
        stream.write_bytes(b''.join(units))
        label = f'Serein camera encoder at {bit_rate // 1000} kb/s'
        check(f'{label}: every camera picture coded, all accepted', len(units) == len(pictures) and not bad,
              f'{len(units)} of {len(pictures)}, {len(bad)} rejected')
        if bit_rate > 1_000_000:
            reference = args.out / 'serein-camera.nv12'
            oracle.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '640x480',
                        '-i', rgb, '-f', 'rawvideo', '-pix_fmt', 'nv12', reference])
            scores = oracle.psnr(stream, reference, 640, 480, rate=15)
            bad = oracle.psnr_failures(scores, len(pictures))
            check(f'{label}: pixels match the camera pictures', not bad,
                  oracle.summary(scores) + ('; ' + bad[0] if bad else ''))

    failed = results.count(False)
    print(f'{len(results) - failed} passed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
