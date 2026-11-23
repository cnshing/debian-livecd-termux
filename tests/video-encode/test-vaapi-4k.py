#!/data/data/com.termux/files/usr/bin/python
"""Installed default VA encoders: changing 4K pictures, timing, keys and pixels.

Run through livecd exec. TVA_ZEROCOPY=0 supplies the copy-path control.
No private driver/library path or daemon socket is selected by this test.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time


def run(command, log=None):
    started = time.monotonic()
    result = subprocess.run([str(x) for x in command], capture_output=True,
                            text=True, timeout=300)
    elapsed = time.monotonic() - started
    if log:
        log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return result.stdout, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=120)
    parser.add_argument('--require-fps', type=float, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    graph = 'testsrc2=size=3840x2160:rate=60'
    results = []
    for codec, extension, profile in [('h264_vaapi', 'h264', 'high'),
                                       ('hevc_vaapi', 'hevc', 'main')]:
        stream = args.out / f'{codec}.{extension}'
        _, elapsed = run(['ffmpeg', '-hide_banner', '-nostdin',
                          '-init_hw_device', 'vaapi=va', '-filter_hw_device', 'va',
                          '-f', 'lavfi', '-i', graph, '-frames:v', args.frames,
                          '-vf', 'format=nv12,hwupload', '-c:v', codec,
                          '-profile:v', profile, '-b:v', '40M', '-maxrate', '40M',
                          '-g', '60', '-bf', '0', '-f', extension, stream],
                         args.out / f'{codec}.log')
        probe, _ = run(['ffprobe', '-v', 'error', '-show_frames', '-show_entries',
                        'frame=width,height,key_frame', '-of', 'json', stream])
        frames = json.loads(probe)['frames']
        keys = [i for i, frame in enumerate(frames) if frame['key_frame']]
        assert len(frames) == args.frames, len(frames)
        assert keys == list(range(0, args.frames, 60)), keys
        assert all((frame['width'], frame['height']) == (3840, 2160) for frame in frames)
        psnr = args.out / f'{codec}.psnr'
        ssim = args.out / f'{codec}.ssim'
        run(['ffmpeg', '-v', 'error', '-r', '60', '-i', stream,
             '-f', 'lavfi', '-i', graph, '-filter_complex',
             '[0:v]format=yuv420p,setparams=range=limited:colorspace=bt709[a];'
             '[1:v]format=yuv420p,setparams=range=limited:colorspace=bt709,split[b][d];'
             f'[a][b]psnr=stats_file={psnr}:eof_action=endall[p];'
             f'[p][d]ssim=stats_file={ssim}:eof_action=endall', '-f', 'null', '-'],
            args.out / f'{codec}.compare.log')
        lines = psnr.read_text().splitlines()
        assert len(lines) == args.frames, len(lines)
        minima = {plane: min(float(re.search(f'psnr_{plane}:([0-9.inf]+)', line)[1])
                             for line in lines) for plane in 'yuv'}
        assert minima['y'] >= 30 and min(minima['u'], minima['v']) >= 32, minima
        lines = ssim.read_text().splitlines()
        assert len(lines) == args.frames, len(lines)
        minimum_ssim = min(float(re.search(r'All:([0-9.]+)', line)[1]) for line in lines)
        assert minimum_ssim > .9, minimum_ssim
        fps = args.frames / elapsed
        result = dict(codec=codec, frames=len(frames), keys=keys, seconds=elapsed,
                      fps=fps, minimum_psnr=minima, minimum_ssim=minimum_ssim,
                      passed=fps >= args.require_fps)
        results.append(result)
        (args.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(result), flush=True)
        for index in [0, args.frames//2]:
            run(['ffmpeg', '-v', 'error', '-i', stream, '-vf',
                 f'select=eq(n\\,{index}),scale=960:-1', '-frames:v', '1',
                 args.out / f'{codec}-{index:03d}.png'])
    assert all(result['passed'] for result in results), results


if __name__ == '__main__':
    main()
