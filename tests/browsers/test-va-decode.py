#!/usr/bin/env python3
"""Decode fixtures with FFmpeg through the VA-API driver and compare every frame with software.

A hang counts as a failure: the old H.264 PPS guess makes vaSyncSurface wait forever. Run it with
the driver environment already set (LIBVA_DRIVERS_PATH, LIBVA_DRIVER_NAME, TERMUX_VA_*), and an
ffmpeg built with VA-API on PATH.

Usage: test-va-decode.py --out NEW_DIRECTORY FIXTURE...
"""
import argparse
import json
import subprocess
from pathlib import Path


def frames(command, timeout):
    """Return (per-frame hashes, stderr) of a decode to NV12, or (None, reason) on a hang."""
    try:
        run = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'verbose', *command,
                              '-pix_fmt', 'nv12', '-f', 'framemd5', '-'],
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return None, f'timed out after {timeout} s\n' + (error.stderr or b'').decode(errors='replace')[-4000:]
    if run.returncode:
        return None, run.stderr[-4000:]
    return [line.split(',')[-1].strip() for line in run.stdout.splitlines() if line and line[0] != '#'], run.stderr


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=60)
    p.add_argument('--png', type=int, nargs='*', default=[12, 36], help='hardware frames to save for viewing')
    p.add_argument('fixtures', type=Path, nargs='+')
    args = p.parse_args()
    args.out.mkdir(parents=True)
    results = []
    for fixture in args.fixtures:
        software, _ = frames(['-threads', '1', '-i', fixture], args.timeout)
        hardware, log = frames(['-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi', '-i', fixture,
                                '-vf', 'hwdownload,format=nv12'], args.timeout)
        (args.out / (fixture.name + '.log')).write_text(log)
        result = {'fixture': fixture.name, 'software_frames': len(software or [])}
        if hardware is None:
            result.update(passed=False, error=log.splitlines()[0] if log else 'failed')
        else:
            same = sum(a == b for a, b in zip(software, hardware))
            result.update(hardware_frames=len(hardware), identical=same,
                          passed=bool(software) and hardware == software)
            for number in args.png:
                subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-hwaccel', 'vaapi', '-hwaccel_output_format',
                                'vaapi', '-i', fixture, '-vf', f'hwdownload,format=nv12,select=eq(n\\,{number})',
                                '-frames:v', '1', args.out / f'{fixture.name}-{number:03d}.png'],
                               timeout=args.timeout, check=False)
        results.append(result)
        print(json.dumps(result), flush=True)
    (args.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)


if __name__ == '__main__':
    main()
