#!/usr/bin/env python3
"""Generate deterministic charts and software-decoded references with recorded FFmpeg commands.

Default: VP9, H.264 (B frames) and HEVC, BT.709 limited, 640x360, 48 numbered frames.
Use --size and --matrix/--range/--ten-bit for explicit alignment and metadata variants.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from video_oracle import frame_number, rgb, sha256, write_png


def chart(width, height, number):
    data = bytearray(width * height * 3)
    colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255),
              (0, 0, 0), (128, 128, 128), (198, 134, 104), (68, 112, 153))
    def rect(x, y, w, h, color):
        line = bytes(color) * w
        for row in range(y, min(y + h, height)):
            start = (row * width + x) * 3
            data[start:start + len(line)] = line
    for i, color in enumerate(colors):
        left, right = width * i // 8, width * (i + 1) // 8
        rect(left, 0, right - left, height, color)
    # Asymmetric lower chart: moving detail, grid, and one unique corner marker.
    for y in range(height // 2, height):
        for x in range(width):
            if x % 40 < 2 or y % 40 < 2:
                c = (230, 230, 230)
            else:
                v = ((x + number * 7) // 7 ^ (y + number * 3) // 5) & 31
                c = (v * 7, (x * 255 // width), y * 255 // height)
            j = (y * width + x) * 3
            data[j:j + 3] = bytes(c)
    rect(0, height - height // 8, width // 12, height // 8, (255, 0, 255))
    bits = [1, 0] + [(number >> bit) & 1 for bit in range(8)]
    for i, bit in enumerate(bits):
        left, right = round(width * (.05 + i * .09)), round(width * (.05 + (i + 1) * .09))
        for top, value in ((.03, bit), (.13, 1 - bit)):
            rect(left, round(height * top), right - left, round(height * .1), (255 * value,) * 3)
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out', type=Path)
    p.add_argument('--codecs', nargs='+', choices=('vp9', 'h264', 'hevc', 'av1', 'vp8', 'mpeg4'), default=['vp9', 'h264', 'hevc'])
    p.add_argument('--size', default='640x360')
    p.add_argument('--frames', type=int, default=48)
    p.add_argument('--matrix', choices=('bt709', 'smpte170m'), default='bt709')
    p.add_argument('--range', choices=('tv', 'pc'), default='tv')
    p.add_argument('--ten-bit', action='store_true')
    args = p.parse_args()
    width, height = map(int, args.size.split('x'))
    if min(width, height) < 128 or width % 2 or height % 2 or not 2 <= args.frames <= 256:
        p.error('Use even dimensions >=128 and 2..256 frames')
    if args.ten_bit and set(args.codecs) & {'h264', 'vp8', 'mpeg4'}:
        p.error('10-bit H.264, VP8 and MPEG-4 are outside the hardware test scope; select vp9/hevc/av1')
    args.out.mkdir(parents=True, exist_ok=False)
    commands = []
    def run(command):
        commands.append([str(x) for x in command])
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    manifest = {'ffmpeg': subprocess.check_output(['ffmpeg', '-version'], text=True),
                'fps': 12, 'commands': commands, 'fixtures': []}
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / 'source.rgb'
        with source.open('wb') as output:
            for number in range(args.frames):
                output.write(chart(width, height, number))
        manifest['source_sha256'] = sha256(source)
        for codec in args.codecs:
            ext = 'webm' if codec in ('vp9', 'av1', 'vp8') else 'mp4'
            name = f'chart-{codec}.{ext}'
            encoder = {'vp9': ['libvpx-vp9', '-deadline', 'good', '-cpu-used', '4', '-crf', '18', '-b:v', '0'],
                       'h264': ['libx264', '-preset', 'medium', '-crf', '18', '-bf', '3'],
                       'hevc': ['libx265', '-preset', 'fast', '-crf', '18', '-x265-params', 'pools=none:frame-threads=1'],
                       'av1': ['libaom-av1', '-cpu-used', '8', '-crf', '18', '-b:v', '0'],
                       'vp8': ['libvpx', '-deadline', 'good', '-cpu-used', '4', '-crf', '8', '-b:v', '4M'],
                       'mpeg4': ['mpeg4', '-q:v', '2', '-bf', '0']}[codec]
            matrix = 'bt601' if args.matrix == 'smpte170m' else args.matrix
            run(['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', args.size,
                 '-framerate', '12', '-i', str(source), '-an', '-vf',
                 f'scale=out_color_matrix={matrix}:out_range={args.range},'
                 f'format={"yuv420p10le" if args.ten_bit else "yuv420p"},'
                 f'setparams=colorspace={args.matrix}:color_primaries={args.matrix}:'
                 f'color_trc={args.matrix}:range={args.range}', '-filter_threads', '1',
                 '-c:v', *encoder, '-threads', '1', '-pix_fmt', 'yuv420p10le' if args.ten_bit else 'yuv420p',
                 '-colorspace', args.matrix, '-color_primaries', args.matrix, '-color_trc', args.matrix,
                 '-color_range', args.range, str(args.out / name)])
            metadata = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=color_space,color_range,color_primaries,color_transfer', '-of', 'json',
                str(args.out / name)], text=True))['streams'][0]
            expected_metadata = {'color_space': args.matrix, 'color_range': args.range,
                                 'color_primaries': args.matrix, 'color_transfer': args.matrix}
            if metadata != expected_metadata:
                raise RuntimeError(f'Encoded metadata differs: {metadata} != {expected_metadata}')
            reference = args.out / (name + '-reference')
            reference.mkdir()
            run(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(args.out / name), '-fps_mode', 'passthrough',
                 '-pix_fmt', 'rgb24', '-threads', '1', '-start_number', '0', str(reference / '%03d.png')])
            frames = sorted(reference.glob('*.png'))
            if len(frames) != args.frames:
                raise RuntimeError('Reference frame count mismatch')
            for i, image in enumerate(frames):
                if frame_number(rgb(image), width, height) != i:
                    raise RuntimeError('Reference barcode is not readable: ' + str(image))
            manifest['fixtures'].append({'name': name, 'codec': codec, 'width': width, 'height': height,
                'frames': args.frames, 'matrix': args.matrix, 'range': args.range, 'bit_depth': 10 if args.ten_bit else 8,
                'sha256': sha256(args.out / name), 'metadata': metadata, 'references': reference.name,
                'reference_sha256': [sha256(f) for f in frames]})
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(args.out / 'manifest.json')


if __name__ == '__main__':
    main()
