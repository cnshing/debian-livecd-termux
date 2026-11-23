#!/usr/bin/env python3
"""Prepare reproducible decoder fd-transport fixtures from synthetic clips.

Usage: prepare-surface-fixtures.py --h264 chart.mp4 --hevc chart-hevc.mp4
                                  --out NEW_DIRECTORY [--frames 120]
Run on a host with FFmpeg/FFprobe, then copy the output to the Android test
phone and pass it as test-surface-transport.py --decoder-assets DIRECTORY.
"""
import argparse
import json
from pathlib import Path
import subprocess


def run(*args):
    return subprocess.check_output([str(arg) for arg in args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--h264', type=Path, required=True)
    parser.add_argument('--hevc', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.frames <= 10000:
        parser.error('--frames must be between 1 and 10000')
    args.out.mkdir(parents=True, exist_ok=False)
    for codec, source in [('h264', args.h264), ('hevc', args.hevc)]:
        target = args.out / f'{codec}.bin'
        run('ffmpeg', '-v', 'error', '-i', source, '-frames:v', args.frames,
            '-c:v', 'copy', '-bsf:v', f'{codec}_mp4toannexb', '-f', codec, target)
        packets = json.loads(run('ffprobe', '-v', 'error', '-show_packets',
                                 '-show_entries', 'packet=pos,size', '-of', 'json',
                                 '-f', codec, target))['packets']
        units = [(int(packet['pos']), int(packet['size'])) for packet in packets]
        (args.out / f'{codec}.json').write_text(json.dumps(units))
        positions = {offset: index + 1 for index, (offset, _) in enumerate(units)}
        frames = json.loads(run('ffprobe', '-v', 'error', '-show_frames',
                                '-show_entries', 'frame=pkt_pos', '-of', 'json',
                                '-f', codec, target))['frames']
        hashes = run('ffmpeg', '-v', 'error', '-i', target, '-pix_fmt', 'yuv420p',
                     '-f', 'framemd5', '-').decode()
        (args.out / f'{codec}.framemd5').write_text(hashes)
        hashes = [line.rsplit(',', 1)[1].strip() for line in hashes.splitlines()
                  if line and not line.startswith('#')]
        assert len(frames) == len(units) == len(hashes) == args.frames
        expected = {positions[int(frame['pkt_pos'])]: digest
                    for frame, digest in zip(frames, hashes)}
        assert len(expected) == args.frames
        (args.out / f'{codec}-expected.json').write_text(json.dumps(expected))
        print(f'{codec}: {len(expected)} reference frames indexed by input picture')


if __name__ == '__main__':
    main()
