"""Checks shared by the hardware encoding tests.

Needs only Python's standard library and an FFmpeg with software H.264/HEVC
decoders, such as Termux's. The source pictures are FFmpeg's moving testsrc2
pattern, so a repeated, dropped or reordered frame lowers the per-frame PSNR,
and its saturated colors make swapped chroma planes fail the U and V scores.
Each check has a negative control in the tests that call it.
"""
from pathlib import Path
import json
import re
import subprocess

# Per-frame PSNR floors. Hardware encodes of testsrc2 at the tested rates
# score 35-50 dB; a one-frame shift or swapped chroma scores far below these.
MIN_PSNR_Y = 30.0
MIN_PSNR_UV = 32.0
# Mesa's VA post-processing converts through RGB, so saturated chroma edges
# bleed: NV12 to NV12 through vapostproc measured Y 40, U 32.7, V 30.6 dB at
# 20 Mb/s, against 50 dB on every plane without it. A one-frame delay scores
# Y 25 dB.
VPP_FLOORS = (35.0, 28.0)


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, capture_output=True, **kwargs)


def make_source(path, width, height, frames, rate=30, noise=0):
    """Raw NV12 frames of testsrc2; noise makes the pictures expensive to code."""
    graph = f'testsrc2=size={width}x{height}:rate={rate}'
    if noise:
        graph += f',noise=alls={noise}:allf=t'
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', graph, '-frames:v', frames,
         '-pix_fmt', 'nv12', '-f', 'rawvideo', path])
    size = width * height * 3 // 2
    if Path(path).stat().st_size != size * frames:
        raise RuntimeError('Short source clip: ' + str(path))
    return size


def swap_chroma(data, width, height):
    """NV12 to NV21 bytes: the negative control for chroma handling."""
    luma = width * height
    out = bytearray(data)
    out[luma::2], out[luma + 1::2] = data[luma + 1::2], data[luma::2]
    return bytes(out)


def nal_units(data, codec):
    """(type, start) for each Annex B NAL unit of 'h264' or 'hevc'."""
    units = []
    for match in re.finditer(b'\x00\x00\x01', data):
        start = match.end()
        if start < len(data):
            header = data[start]
            units.append((header & 0x1f if codec == 'h264' else (header >> 1) & 0x3f, start))
    return units


def is_vcl(kind, codec):
    return 1 <= kind <= 5 if codec == 'h264' else kind <= 31


def is_idr(kind, codec):
    return kind == 5 if codec == 'h264' else kind in (19, 20)


PARAMETER_SETS = {'h264': {7, 8}, 'hevc': {32, 33, 34}}


def idr_report(data, codec):
    """Index of each coded picture that is an IDR, and those IDRs that lack
    the full parameter sets since the previous picture."""
    pictures, idrs, bare = 0, [], []
    seen = set()
    for kind, start in nal_units(data, codec):
        if kind in PARAMETER_SETS[codec]:
            seen.add(kind)
        elif is_vcl(kind, codec):
            first_slice = data[start + (1 if codec == 'h264' else 2)] & 0x80
            if first_slice:
                if is_idr(kind, codec):
                    idrs.append(pictures)
                    if seen != PARAMETER_SETS[codec]:
                        bare.append(pictures)
                pictures += 1
                seen = set()
    return {'pictures': pictures, 'idr': idrs, 'idr_without_parameter_sets': bare}


def sps_profile(data):
    """(profile_idc, constraint flags) of the first H.264 SPS."""
    for kind, start in nal_units(data, 'h264'):
        if kind == 7 and start + 2 < len(data):
            return data[start + 1], data[start + 2]
    return None


def psnr(encoded, source, width, height, rate=30, raw=False):
    """Per-frame PSNR of a decoded stream, or raw NV12 frames, against raw NV12
    frames, by index. Returns dicts with n, y, u and v; FFmpeg reports
    identical planes as inf. Both inputs receive matching metadata before comparison
    so automatic conversion does not change samples based on stream signalling.
    Colour signalling is tested separately by the colour-bar checks."""
    stats = Path(f'{encoded}.{Path(source).stem}.psnr.log')
    stats.unlink(missing_ok=True)
    decoded = ['-f', 'rawvideo', '-pix_fmt', 'nv12', '-s', f'{width}x{height}'] if raw else []
    run(['ffmpeg', '-v', 'error', '-nostdin', *decoded, '-i', encoded,
         '-f', 'rawvideo', '-pix_fmt', 'nv12', '-s', f'{width}x{height}', '-r', rate, '-i', source,
         '-lavfi', f'[0:v]format=yuv420p,setparams=range=limited:colorspace=bt709,setpts=N/({rate}*TB)[a];'
                   f'[1:v]format=yuv420p,setparams=range=limited:colorspace=bt709,setpts=N/({rate}*TB)[b];'
                   f'[a][b]psnr=stats_file={stats}:eof_action=endall',
         '-f', 'null', '-'])
    frames = []
    for line in stats.read_text().splitlines():
        fields = dict(part.split(':', 1) for part in line.split())
        frames.append({'n': int(fields['n']) - 1,
                       **{k: float(fields['psnr_' + k]) for k in ('y', 'u', 'v')}})
    return frames


def psnr_failures(frames, count=None, floors=(MIN_PSNR_Y, MIN_PSNR_UV)):
    """Frames below the floors, and a frame-count mismatch, as readable strings."""
    bad = [f"frame {f['n']}: Y {f['y']:.1f} U {f['u']:.1f} V {f['v']:.1f} dB" for f in frames
           if f['y'] < floors[0] or min(f['u'], f['v']) < floors[1]]
    if count is not None and len(frames) != count:
        bad.insert(0, f'{len(frames)} frames compared, expected {count}')
    return bad


def summary(frames):
    if not frames:
        return 'no frames'
    low = {k: min(f[k] for f in frames) for k in 'yuv'}
    return f"{len(frames)} frames, minimum Y {low['y']:.1f} U {low['u']:.1f} V {low['v']:.1f} dB"


def probe_frames(path):
    """Key-frame flag and picture type per decoded frame, from ffprobe."""
    out = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
               'frame=key_frame,pict_type', '-of', 'json', path]).stdout
    return [(f.get('key_frame') == 1, f.get('pict_type')) for f in json.loads(out)['frames']]


# Colour signalling. Four solid bars whose colours move far apart between
# BT.601 and BT.709 and between full and limited range, so a stream that
# signals anything other than what its samples are in decodes visibly wrong.
COLOR_BARS = ((220, 40, 40), (40, 200, 60), (40, 60, 220), (230, 200, 60))
# (primaries, transfer, matrix) VUI code points (ITU-T H.273).
COLOR_SPACES = {'bt601': (6, 6, 6), 'bt709': (1, 1, 1)}
COLOR_TOLERANCE = 10


def rgb_to_yuv(rgb, matrix, full):
    kr, kb = (0.299, 0.114) if matrix == 'bt601' else (0.2126, 0.0722)
    r, g, b = (v / 255 for v in rgb)
    y = kr * r + (1 - kr - kb) * g + kb * b
    cb, cr = (b - y) / (2 * (1 - kb)), (r - y) / (2 * (1 - kr))
    scale_y, scale_c, base = (255, 255, 0) if full else (219, 224, 16)
    clip = lambda v: max(0, min(255, round(v)))
    return clip(base + scale_y * y), clip(128 + scale_c * cb), clip(128 + scale_c * cr)


def color_bars_nv12(width, height, matrix, full):
    """One NV12 picture of COLOR_BARS, its samples in the given matrix and range."""
    bar = width // len(COLOR_BARS)
    yuv = [rgb_to_yuv(rgb, matrix, full) for rgb in COLOR_BARS]
    luma = bytes(yuv[min(x // bar, len(yuv) - 1)][0] for x in range(width))
    chroma = b''.join(bytes(yuv[min(2 * x // bar, len(yuv) - 1)][1:]) for x in range(width // 2))
    return luma * height + chroma * (height // 2)


def stream_color(path):
    """The colour signalling FFmpeg reads from a stream or file."""
    out = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
               'stream=color_range,color_space,color_primaries,color_transfer', '-of', 'json', path]).stdout
    return (json.loads(out).get('streams') or [{}])[0]


def bar_errors(path, width, height, frame=5):
    """Decode one picture to RGB as its signalling says and return each bar's
    centre colour and the largest channel error against COLOR_BARS."""
    raw = run(['ffmpeg', '-v', 'error', '-nostdin', '-i', path, '-vf', f'select=eq(n\\,{frame})',
               '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']).stdout
    if len(raw) != width * height * 3:
        return None, None
    bar = width // len(COLOR_BARS)
    found, worst = [], 0
    for index, want in enumerate(COLOR_BARS):
        x, y = index * bar + bar // 2, height // 2
        got = tuple(raw[(y * width + x) * 3:(y * width + x) * 3 + 3])
        found.append(got)
        worst = max(worst, *(abs(a - b) for a, b in zip(got, want)))
    return found, worst
