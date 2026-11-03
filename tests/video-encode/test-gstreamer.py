#!/data/data/com.termux/files/usr/bin/python
"""GStreamer VA-API encoding, as Serein and other GStreamer programs use it.

Serein's Linux camera encoder (crates/discord-voice/src/camera/encode_linux.rs
at v1.0.0-nightly.20261028.68) is reproduced element for element: appsrc with
packed RGB, videoconvert, vah264enc set only through properties it declares,
h264parse with config-interval=-1 and an appsink that demands Constrained
Baseline. Like Serein it rejects any access unit that is a delta unit, lacks
an IDR or lacks parameter sets. Its screen-share pipeline, which keeps
pictures in VA memory through vapostproc, is checked too, and both outputs are
compared with the source frame by frame.

The encoder is found the way GStreamer finds it everywhere: the va plugin
scans /dev/dri/renderD128 upward. Nothing here names a device or a driver.

Usage: test-gstreamer.py --out NEW_DIRECTORY
"""
import argparse
from pathlib import Path
import subprocess
import sys

import encode_oracle as oracle
from serein_encoder import SereinCameraEncoder, drain, rejected  # sets the GStreamer version
from gi.repository import Gst  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (': ' + detail if detail else ''), flush=True)
    return ok


def serein_camera(out, key_interval, label, bit_rate=600_000):
    width, height, fps, count = 640, 480, 15, 60
    nv12, rgb = out / f'{label}.nv12', out / f'{label}.rgb'
    oracle.make_source(nv12, width, height, count, rate=fps)
    oracle.run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'nv12', '-s', f'{width}x{height}',
                '-i', nv12, '-f', 'rawvideo', '-pix_fmt', 'rgb24', rgb])
    data = rgb.read_bytes()
    size = width * height * 3
    encoder = SereinCameraEncoder(width, height, fps, bit_rate, key_interval)
    units, bad = [], []
    try:
        for index in range(count):
            result = encoder.encode(data[index * size:(index + 1) * size])
            if result is None:
                continue
            unit, delta = result
            if rejected(unit, delta):
                bad.append(len(units))
            units.append(unit)
        units += drain(encoder)
    finally:
        encoder.close()
    stream = out / f'{label}.h264'
    stream.write_bytes(b''.join(units))
    return count, units, bad, stream, nv12


def screen_share(out):
    """Serein's Mode::Va: VA memory from vapostproc straight into vah264enc."""
    width, height, fps, count = 1280, 720, 30, 90
    source = out / 'screen.nv12'
    oracle.make_source(source, width, height, count, rate=fps)
    stream = out / 'screen.h264'
    pipeline = (f'filesrc location={source} ! rawvideoparse format=nv12 width={width} height={height} '
                f'framerate={fps}/1 ! vapostproc add-borders=true ! '
                f'video/x-raw(memory:VAMemory),format=NV12,width={width},height={height} ! '
                f'vah264enc name=encoder rate-control=cbr bitrate=4000 key-int-max={fps * 2} b-frames=0 ! '
                f'h264parse config-interval=-1 ! '
                f'video/x-h264,stream-format=byte-stream,alignment=au,profile=constrained-baseline ! '
                f'filesink location={stream}')
    run = subprocess.run(['gst-launch-1.0', '-q', *pipeline.split()], capture_output=True, text=True, timeout=120)
    return run, source, stream, count


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True)
    Gst.init(None)
    factory = Gst.ElementFactory.find('vah264enc')
    check('vah264enc is registered', factory is not None,
          factory.get_metadata('long-name') if factory else 'missing')
    if not factory:
        return 1

    count, units, rejected, stream, source = serein_camera(args.out, 1, 'serein-camera')
    check('Serein camera: one access unit per picture', len(units) == count, f'{len(units)} of {count}')
    check('Serein camera: every unit is an IDR with parameter sets, under 128 KiB', not rejected,
          f'rejected units {rejected[:5]}' if rejected else f'{len(units)} accepted')
    found = oracle.sps_profile(stream.read_bytes())
    check('Serein camera: Constrained Baseline', found and found[0] == 66 and found[1] & 0x40, f'{found}')
    rate = stream.stat().st_size * 8 / (count / 15)
    check('Serein camera: 600 kb/s target within 20%', abs(rate - 600_000) < 120_000, f'{rate / 1000:.0f} kb/s')
    # Pixels are judged at a rate where coding loss cannot hide a conversion
    # error: all-intra 640x480 at 600 kb/s scores barely 30 dB on testsrc2.
    count, units, unused, stream, source = serein_camera(args.out, 1, 'serein-camera-8m', 8_000_000)
    scores = oracle.psnr(stream, source, 640, 480, rate=15)
    bad = oracle.psnr_failures(scores, count)
    check('Serein camera at 8 Mb/s: pixels match the source', not bad,
          oracle.summary(scores) + ('; ' + bad[0] if bad else ''))

    unused, units, rejected, unused, unused = serein_camera(args.out, 30, 'control-gop30')
    check('control: Serein\'s check rejects delta pictures when key-int-max is 30', len(rejected) > len(units) // 2,
          f'{len(rejected)} of {len(units)} rejected')

    run, source, stream, count = screen_share(args.out)
    check('Serein screen share (VA memory) runs', run.returncode == 0, run.stderr.strip()[-300:])
    if run.returncode == 0:
        report = oracle.idr_report(stream.read_bytes(), 'h264')
        check('screen share: IDR every key-int-max pictures', report['idr'] == list(range(0, count, 60)),
              f"IDR at {report['idr']} of {report['pictures']}")
        scores = oracle.psnr(stream, source, 1280, 720)
        bad = oracle.psnr_failures(scores, count, oracle.VPP_FLOORS)
        check('screen share: pixels match the source within VA post-processing loss', not bad,
              oracle.summary(scores) + ('; ' + bad[0] if bad else ''))
        size = 1280 * 720 * 3 // 2
        frames = source.read_bytes()
        delayed = args.out / 'screen-delayed.nv12'
        delayed.write_bytes(frames[:size] + frames[:-size])
        bad = oracle.psnr_failures(oracle.psnr(stream, delayed, 1280, 720), count, oracle.VPP_FLOORS)
        check('control: a one-frame delay fails the same tolerance', len(bad) > count // 2, f'{len(bad)} frames fail')

    failed = results.count(False)
    print(f'{len(results) - failed} passed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
