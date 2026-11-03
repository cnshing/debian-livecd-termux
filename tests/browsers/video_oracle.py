"""Pixel oracle shared by the fixture generator and native browser tests.

Only Python's standard library and FFmpeg are required, on either PC or Termux.
Frame identity comes from pixels, never the player's clock or decoder status.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import zlib


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, capture_output=True, **kwargs)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_png(path, width, height, pixels):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    stride = width * 3
    raw = b''.join(b'\0' + pixels[y * stride:(y + 1) * stride] for y in range(height))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' +
        chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
        chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def rgb(path, width=None, height=None, box=None):
    command = ['ffmpeg', '-v', 'error', '-threads', '1', '-i', path]
    filters = []
    if box:
        # CSS object-fit can land on half pixels. Round halves upward, matching the
        # rasterized content origin, rather than Python's ties-to-even rounding.
        x, y, w, h = (math.floor(box[k] + .5) for k in ('left', 'top', 'width', 'height'))
        if min(w, h) <= 0 or min(x, y) < 0:
            raise ValueError('Video crop is outside capture: ' + str(box))
        filters.append(f'crop={w}:{h}:{x}:{y}:exact=1')
    if width and height:
        filters.append(f'scale={width}:{height}:flags=area')
    if filters:
        command += ['-vf', ','.join(filters), '-filter_threads', '1']
    return run([*command, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-threads', '1', '-']).stdout


def pixel(data, width, x, y):
    i = (y * width + x) * 3
    return tuple(data[i:i + 3])


def frame_number(data, width, height):
    """Eight bits and their complements; two fixed sync cells reject blank frames."""
    bits = []
    for cell in range(10):
        x = round(width * (.05 + (cell + .5) * .09))
        values = [sum(pixel(data, width, x, round(height * y))) / 3 for y in (.08, .18)]
        if not (max(values) > 190 and min(values) < 65):
            raise ValueError(f'Invalid frame barcode cell {cell}: {values}')
        bits.append(int(values[0] > values[1]))
    if bits[:2] != [1, 0]:
        raise ValueError('Frame barcode sync is wrong')
    return sum(bit << i for i, bit in enumerate(bits[2:]))


def compare(capture, box, fixture_dir, fixture, destination, expected_frame=None):
    width, height = fixture['width'], fixture['height']
    data = rgb(capture, width, height, box)
    if len(data) != width * height * 3:
        raise ValueError('Incomplete RGB capture')
    write_png(destination, width, height, data)
    number = frame_number(data, width, height)
    if expected_frame is not None and number != expected_frame:
        raise ValueError(f'Wrong frame: expected {expected_frame}, saw {number}')
    if number >= fixture['frames']:
        raise ValueError(f'Frame barcode out of range: {number}')
    reference = Path(fixture_dir) / fixture['references'] / f'{number:03d}.png'
    if sha256(reference) != fixture['reference_sha256'][number]:
        raise ValueError('Reference hash mismatch: ' + str(reference))
    reference_rgb = rgb(reference)
    color_errors = []
    for i in range(8):
        x, y = width * (2 * i + 1) // 16, height * 3 // 8
        actual, expected = pixel(data, width, x, y), pixel(reference_rgb, width, x, y)
        color_errors.append(max(abs(a - b) for a, b in zip(actual, expected)))
    # Browser and FFmpeg use different chroma reconstruction/scaling filters. Measure
    # the whole frame at half resolution to suppress that subpixel difference; the
    # independently checked barcode still comes from the full normalized capture.
    metric_width, metric_height = width // 2, height // 2
    metrics = run(['ffmpeg', '-hide_banner', '-threads', '1', '-i', destination,
        '-threads', '1', '-i', reference, '-filter_complex_threads', '1', '-lavfi',
        f'[0:v]scale={metric_width}:{metric_height}:flags=area,split[a][b];'
        f'[1:v]scale={metric_width}:{metric_height}:flags=area,split[c][d];'
        '[a][c]psnr[p];[b][d]ssim[s]',
        '-map', '[p]', '-map', '[s]', '-f', 'null', '-']).stderr.decode()
    psnr = float(re.search(r'average:([\d.inf]+)', metrics)[1])
    ssim = float(re.search(r'All:([\d.]+)', metrics)[1])
    return {'frame': number, 'psnr_db': psnr if math.isfinite(psnr) else 'inf', 'ssim': ssim,
            'ok': psnr >= 28 and ssim >= .90 and max(color_errors) <= 16,
            'metric_size': [metric_width, metric_height], 'color_errors': color_errors,
            'thresholds': {'psnr_db': 28, 'ssim': .90, 'color_channel_error': 16}, 'reference': str(reference),
            'normalized': str(destination), 'capture': str(capture), 'box': box}


def contact_sheet(paths, destination):
    """Columns: reference, browser capture, compositor capture. Sidecar names every tile."""
    if not paths:
        return
    w, h, columns = 256, 144, 3
    rows = (len(paths) + columns - 1) // columns
    canvas = bytearray(w * columns * h * rows * 3)
    for i, path in enumerate(paths):
        data = rgb(path, w, h)
        for y in range(h):
            start = (((i // columns) * h + y) * w * columns + (i % columns) * w) * 3
            canvas[start:start + w * 3] = data[y * w * 3:(y + 1) * w * 3]
    write_png(destination, w * columns, h * rows, canvas)
    Path(destination).with_suffix('.json').write_text(json.dumps([str(p) for p in paths], indent=2) + '\n')
