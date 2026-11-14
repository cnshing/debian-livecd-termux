#!/usr/bin/env python3
"""Decode numbered PC fixtures using native Termux FFmpeg's NDK MediaCodec path."""
import argparse
import json
from pathlib import Path
import subprocess
import re

from video_oracle import compare, contact_sheet, frame_number, rgb, sha256


def colour_tags(log):
    found = re.search(r'color_range:(\S+) color_space:(\S+)', log)
    return list(found.groups()) if found else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('fixtures', type=Path)
    p.add_argument('out', type=Path)
    args = p.parse_args()
    args.fixtures = args.fixtures.resolve()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.fixtures / 'manifest.json').read_text())
    report = {'ffmpeg': subprocess.check_output(['ffmpeg', '-version'], text=True), 'cases': []}
    for fixture in manifest['fixtures']:
        name = fixture['name']
        folder = args.out / name
        folder.mkdir()
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'verbose', '-c:v', fixture['codec'] + '_mediacodec',
                   '-ndk_codec', '1', '-i', str(args.fixtures / name), '-an', '-fps_mode', 'passthrough',
                   '-vf', 'showinfo', '-pix_fmt', 'rgb24', '-threads', '1', '-start_number', '0', str(folder / '%03d.png')]
        result = {'name': name, 'command': command, 'samples': [], 'ok': False}
        report['cases'].append(result)
        if sha256(args.fixtures / name) != fixture['sha256']:
            result['error'] = 'Fixture hash mismatch'
            continue
        with (folder / 'decode.log').open('w') as log:
            process = subprocess.run(command, stdout=log, stderr=log, timeout=120)
        frames = sorted(folder.glob('[0-9][0-9][0-9].png'))
        result['exit_code'], result['frames'] = process.returncode, len(frames)
        log_text = (folder / 'decode.log').read_text()
        codec_name = re.search(r'MediaCodec started successfully: codec = ([\w.]+)', log_text)
        result['android_codec'] = codec_name[1] if codec_name else None
        result['hardware_codec'] = bool(codec_name and not any(
            name in codec_name[1].lower() for name in ('omx.google.', 'c2.android.')))
        # The colour tags must match FFmpeg's software decoder, or RGB conversion
        # shifts colours (Exynos VP8 reported BT.709 instead of VP8's BT.601).
        result['colour'], result['software_colour'] = (colour_tags(log_text), colour_tags(subprocess.run(
            ['ffmpeg', '-hide_banner', '-i', str(args.fixtures / name), '-frames:v', '1',
             '-vf', 'showinfo', '-f', 'null', '-'], capture_output=True, text=True, timeout=120).stderr))
        if result['colour'] != result['software_colour']:
            result['error'] = 'Colour matrix or range differs from the software decoder'
            continue
        if process.returncode or len(frames) != fixture['frames']:
            result['error'] = 'Decode failed or frame count differs'
            continue
        result['frame_sequence'] = []
        try:
            result['frame_sequence'] = [frame_number(rgb(image), fixture['width'], fixture['height']) for image in frames]
        except ValueError as error:
            result['error'] = str(error)
            continue
        sheet = []
        for number in (0, fixture['frames'] // 2, fixture['frames'] - 1):
            image = folder / f'{number:03d}.png'
            try:
                result['samples'].append(compare(image, {'left': 0, 'top': 0,
                    'width': fixture['width'], 'height': fixture['height']}, args.fixtures,
                    fixture, folder / f'{number:03d}-normalized.png', number))
            except (ValueError, subprocess.CalledProcessError) as error:
                result['samples'].append({'ok': False, 'error': str(error)})
            sheet.extend([args.fixtures / fixture['references'] / f'{number:03d}.png', image, image])
        contact_sheet(sheet, folder / 'contact-sheet.png')
        result['ok'] = (result['hardware_codec'] and result['frame_sequence'] == list(range(fixture['frames']))
                        and all(sample['ok'] for sample in result['samples']))
        print(name, 'PASS' if result['ok'] else 'FAIL', flush=True)
    report['ok'] = bool(report['cases']) and all(c['ok'] for c in report['cases'])
    (args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
