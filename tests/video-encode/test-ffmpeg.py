#!/data/data/com.termux/files/usr/bin/python
"""FFmpeg's VA-API encoders, the library path behind OBS and the ffmpeg command.

OBS's FFmpeg VAAPI encoder opens a VA device on a render node, uploads
system-memory pictures into VA surfaces and drives libavcodec's h264_vaapi or
hevc_vaapi with a profile, a bitrate and a key-frame interval; that is what
these cases do through the ffmpeg command. The device is left for FFmpeg to
find, as it does on any Linux system. Each output is checked for frame count,
key frames, parameter sets, profile, bitrate and pixels against the source,
and an MP4 is seeked as a player would. Controls must fail.

Usage: test-ffmpeg.py --out NEW_DIRECTORY
"""
import argparse
from pathlib import Path
import re
import sys

import encode_oracle as oracle

results = []
WIDTH, HEIGHT, COUNT, GOP = 1280, 720, 120, 30


def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (': ' + detail if detail else ''), flush=True)
    return ok


def ffmpeg(*args):
    return oracle.subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-y', *map(str, args)],
                                 capture_output=True, text=True, timeout=300)


def upload_encode(source, output, codec, profile, bitrate='4M', pixel_format='nv12', size=(WIDTH, HEIGHT)):
    # OBS: a VAAPI device, NV12 frames uploaded into VA surfaces, no B-frames.
    return ffmpeg('-init_hw_device', 'vaapi=va', '-filter_hw_device', 'va',
                  '-f', 'rawvideo', '-pix_fmt', pixel_format, '-s', f'{size[0]}x{size[1]}', '-r', 30, '-i', source,
                  '-vf', 'format=nv12,hwupload', '-c:v', codec, '-profile:v', profile, '-b:v', bitrate,
                  '-maxrate', bitrate, '-g', GOP, '-bf', 0, output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True)
    source = args.out / 'source.nv12'
    size = oracle.make_source(source, WIDTH, HEIGHT, COUNT)

    run = ffmpeg('-v', 'verbose', '-init_hw_device', 'vaapi=va', '-f', 'lavfi', '-i', 'nullsrc', '-frames:v', 1,
                 '-f', 'null', '-')
    device = re.search(r'(?:Opened|Trying to use) DRM render node for device \d+\.?|/dev/dri/renderD\d+', run.stderr)
    driver = re.search(r'VAAPI driver: (.*)', run.stderr)
    check('FFmpeg finds the VA device on its own', run.returncode == 0 and driver is not None,
          f"{device.group(0) if device else 'no render node message'}; driver {driver.group(1) if driver else 'none'}")

    expected_keys = list(range(0, COUNT, GOP))
    cases = [('h264_vaapi', 'constrained_baseline', 'h264', 66), ('h264_vaapi', 'main', 'h264', 77),
             ('h264_vaapi', 'high', 'h264', 100), ('hevc_vaapi', 'main', 'hevc', None)]
    for codec, profile, kind, profile_idc in cases:
        name = f'{codec} {profile}'
        stream = args.out / f'{codec}-{profile}.{kind}'
        run = upload_encode(source, stream, codec, profile)
        if not check(f'{name}: encodes uploaded pictures', run.returncode == 0, run.stderr.strip()[-300:]):
            continue
        data = stream.read_bytes()
        report = oracle.idr_report(data, kind)
        check(f'{name}: {COUNT} pictures, IDR every {GOP}', report['pictures'] == COUNT and report['idr'] == expected_keys,
              f"{report['pictures']} pictures, IDR at {report['idr']}")
        check(f'{name}: parameter sets with every IDR', not report['idr_without_parameter_sets'],
              f"bare IDR at {report['idr_without_parameter_sets']}")
        if profile_idc:
            found = oracle.sps_profile(data)
            check(f'{name}: SPS profile_idc {profile_idc}', found and found[0] == profile_idc, f'{found}')
        scores = oracle.psnr(stream, source, WIDTH, HEIGHT)
        bad = oracle.psnr_failures(scores, COUNT)
        check(f'{name}: pixels match the source', not bad, oracle.summary(scores) + ('; ' + bad[0] if bad else ''))

    # Sizes that are not multiples of 16, such as WebRTC's 640x360 layer:
    # the encoder must code the visible picture, not the aligned surface.
    for width, height in ((640, 360), (854, 480)):
        small = args.out / f'source-{width}x{height}.nv12'
        oracle.make_source(small, width, height, 30)
        for codec, kind in (('h264_vaapi', 'h264'), ('hevc_vaapi', 'hevc')):
            stream = args.out / f'{codec}-{width}x{height}.{kind}'
            run = upload_encode(small, stream, codec, 'high' if kind == 'h264' else 'main', '2M', size=(width, height))
            if not check(f'{codec} {width}x{height}: encodes', run.returncode == 0, run.stderr.strip()[-300:]):
                continue
            probe = oracle.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                                stream]).stdout.decode().strip()
            check(f'{codec} {width}x{height}: decodes at that size', probe == f'{width},{height}', probe)
            scores = oracle.psnr(stream, small, width, height)
            bad = oracle.psnr_failures(scores, 30)
            check(f'{codec} {width}x{height}: pixels match the source', not bad,
                  oracle.summary(scores) + ('; ' + bad[0] if bad else ''))

    # Containers: FFmpeg's own key-frame flags and stream headers must agree
    # with what the driver coded, or players seek to undecodable frames.
    for codec, kind in (('h264_vaapi', 'h264'), ('hevc_vaapi', 'hevc')):
        mp4 = args.out / f'{codec}.mp4'
        run = upload_encode(source, mp4, codec, 'high' if kind == 'h264' else 'main')
        if not check(f'{codec} MP4: encodes', run.returncode == 0, run.stderr.strip()[-300:]):
            continue
        flags = [i for i, (key, unused) in enumerate(oracle.probe_frames(mp4)) if key]
        check(f'{codec} MP4: key-frame flags at every IDR', flags == expected_keys, f'{flags}')
        for second in (1, 3):
            seek = args.out / f'{codec}-seek{second}.nv12'
            oracle.run(['ffmpeg', '-v', 'error', '-y', '-ss', second, '-i', mp4, '-frames:v', 1,
                        '-f', 'rawvideo', '-pix_fmt', 'nv12', seek])
            reference = args.out / f'reference{second}.nv12'
            reference.write_bytes(source.read_bytes()[second * 30 * size:(second * 30 + 1) * size])
            scores = oracle.psnr(seek, reference, WIDTH, HEIGHT, raw=True)
            check(f'{codec} MP4: seeking to {second} s decodes the right picture',
                  not oracle.psnr_failures(scores, 1), oracle.summary(scores))

    # Transcoding on the GPU: hardware decode, VA scaling, hardware encode, as
    # ffmpeg -hwaccel vaapi users and media servers do.
    hd = args.out / 'h264_vaapi-high.h264'
    scaled = args.out / 'transcode.hevc'
    run = ffmpeg('-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi', '-i', hd,
                 '-vf', 'scale_vaapi=w=640:h=360', '-c:v', 'hevc_vaapi', '-b:v', '2M', '-g', GOP, scaled)
    if check('GPU transcode H.264 to HEVC with scale_vaapi', run.returncode == 0, run.stderr.strip()[-300:]):
        small = args.out / 'source-640.nv12'
        oracle.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'nv12', '-s', f'{WIDTH}x{HEIGHT}',
                    '-i', source, '-vf', 'scale=640:360', '-f', 'rawvideo', '-pix_fmt', 'nv12', small])
        scores = oracle.psnr(scaled, small, 640, 360)
        bad = oracle.psnr_failures(scores, COUNT, oracle.VPP_FLOORS)
        check('GPU transcode: pixels match the scaled source within VA post-processing loss', not bad,
              oracle.summary(scores) + ('; ' + bad[0] if bad else ''))

    # Bitrate targets.
    for rate in (1, 6):
        stream = args.out / f'rate-{rate}M.h264'
        run = upload_encode(source, stream, 'h264_vaapi', 'high', f'{rate}M')
        if run.returncode == 0:
            actual = stream.stat().st_size * 8 / (COUNT / 30) / 1e6
            check(f'{rate} Mb/s target', abs(actual - rate) < rate * 0.25, f'{actual:.2f} Mb/s')

    # Controls: chroma read with U and V swapped, and a reference one frame
    # later, must both fail the pixel check.
    swapped = args.out / 'swapped.h264'
    upload_encode(source, swapped, 'h264_vaapi', 'high', pixel_format='nv21')
    bad = oracle.psnr_failures(oracle.psnr(swapped, source, WIDTH, HEIGHT))
    check('control: U and V swapped fails', len(bad) > COUNT // 2, f'{len(bad)} frames fail')
    later = args.out / 'source-later.nv12'
    later.write_bytes(source.read_bytes()[size:] + source.read_bytes()[-size:])
    bad = oracle.psnr_failures(oracle.psnr(args.out / 'h264_vaapi-high.h264', later, WIDTH, HEIGHT))
    check('control: a one-frame shift fails', len(bad) > COUNT // 2, f'{len(bad)} frames fail')

    failed = results.count(False)
    print(f'{len(results) - failed} passed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
