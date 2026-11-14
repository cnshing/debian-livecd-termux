#!/usr/bin/env python3
"""Check Firefox's private FFmpeg runtime without starting a browser.

Run with the session's VA driver/preload and a private daemon socket. Each child
loads the codec libraries locally, as Firefox does, opens an I420 VAAPI encoder,
and drains it without submitting a picture. Firefox does this after recreating
an encoder at flush. A failed VA display or a signal is a failed check.

The rate checks encode the same pictures with the frame rates Firefox declares
and the timestamps it sends. Firefox's WebRTC declares the H.264 level's limit
(450 fps at 320x180) for a 30 fps capture, and WebCodecs may declare none. The
stream's bitrate over its own timestamps must stay near the plain 30 fps run.
"""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys

EOF = -541478725  # AVERROR_EOF
EAGAIN = -11
WIDTH, HEIGHT, BITRATE, PICTURES = 640, 360, 2000000, 120
# (label, declared frame rate or 0 for none, microseconds between pictures)
RATES = [('30 fps declared and sent', 30, 33333),
         ('450 fps declared, 30 sent', 450, 33333),
         ('no rate declared, 30 sent', 0, 33333),
         ('30 fps declared, 15 sent', 30, 66667)]


class Frame(C.Structure):  # The start of AVFrame, libavutil 61.
    _fields_ = [('data', C.c_void_p * 8), ('linesize', C.c_int * 8), ('extended_data', C.c_void_p),
                ('width', C.c_int), ('height', C.c_int), ('nb_samples', C.c_int), ('format', C.c_int),
                ('pict_type', C.c_int), ('sample_aspect_ratio', C.c_int * 2), ('pts', C.c_int64)]


class Packet(C.Structure):  # The start of AVPacket, libavcodec 63.
    _fields_ = [('buf', C.c_void_p), ('pts', C.c_int64), ('dts', C.c_int64),
                ('data', C.c_void_p), ('size', C.c_int)]


def probe(directory, name, rate=None):
    util = C.CDLL(str(directory / 'libavutil.so.61'), mode=C.RTLD_LOCAL)
    codec = C.CDLL(str(directory / 'libavcodec.so.63'), mode=C.RTLD_LOCAL)
    codec.avcodec_find_encoder_by_name.argtypes = [C.c_char_p]
    codec.avcodec_find_encoder_by_name.restype = C.c_void_p
    codec.avcodec_alloc_context3.argtypes = [C.c_void_p]
    codec.avcodec_alloc_context3.restype = C.c_void_p
    codec.avcodec_open2.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p]
    codec.avcodec_send_frame.argtypes = [C.c_void_p, C.c_void_p]
    codec.avcodec_receive_packet.argtypes = [C.c_void_p, C.c_void_p]
    codec.avcodec_free_context.argtypes = [C.POINTER(C.c_void_p)]
    codec.av_packet_alloc.restype = C.c_void_p
    codec.av_packet_free.argtypes = [C.POINTER(C.c_void_p)]
    util.av_opt_set.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_int]
    encoder = codec.avcodec_find_encoder_by_name(name.encode())
    if not encoder:
        raise RuntimeError('encoder missing: ' + name)
    context = C.c_void_p(codec.avcodec_alloc_context3(encoder))
    packet = C.c_void_p(codec.av_packet_alloc())
    if not context or not packet:
        raise MemoryError('codec context/packet')
    try:
        options = {'video_size': f'{WIDTH}x{HEIGHT}', 'pixel_format': 'yuv420p',
                   'time_base': '1/1000000' if rate else '1/30', 'b': str(BITRATE), 'bf': '0', 'g': '30'}
        if name == 'h264_vaapi':
            options['profile'] = '66'
        for key, value in options.items():
            ret = util.av_opt_set(context, key.encode(), value.encode(), 1)
            if ret < 0:
                raise RuntimeError(f'{key}: {ret}')
        if rate and rate[0]:
            # AVCodecContext has no option for framerate. It follows time_base and
            # pkt_timebase, three AVRationals in a row; AVOption's offset is its third field.
            util.av_opt_find.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_int, C.c_int]
            util.av_opt_find.restype = C.c_void_p
            option = util.av_opt_find(context, b'time_base', None, 0, 0)
            offset = C.c_int.from_address(option + 2 * C.sizeof(C.c_void_p)).value
            (C.c_int * 2).from_address(context.value + offset + 16)[:] = [rate[0], 1]
        ret = codec.avcodec_open2(context, encoder, None)
        if ret < 0:
            raise RuntimeError(f'open: {ret}')
        if rate:
            print(json.dumps(encode(util, codec, context, packet, rate[1])))
            return
        ret = codec.avcodec_send_frame(context, None)
        if ret not in (0, EOF):
            raise RuntimeError(f'empty drain send: {ret}')
        ret = codec.avcodec_receive_packet(context, packet)
        if ret != EOF:
            raise RuntimeError(f'empty drain receive: {ret}, expected EOF')
    finally:
        codec.av_packet_free(C.byref(packet))
        codec.avcodec_free_context(C.byref(context))


def encode(util, codec, context, packet, interval):
    """Encode PICTURES pictures of fresh 8x8 blocks, which cost bits at any quantizer."""
    util.av_frame_alloc.restype = C.c_void_p
    util.av_frame_get_buffer.argtypes = [C.c_void_p, C.c_int]
    util.av_frame_unref.argtypes = [C.c_void_p]
    util.av_frame_free.argtypes = [C.POINTER(C.c_void_p)]
    codec.av_packet_unref.argtypes = [C.c_void_p]
    pointer = C.c_void_p(util.av_frame_alloc())
    if not pointer:
        raise MemoryError('frame')
    frame, output = Frame.from_address(pointer.value), Packet.from_address(packet.value)
    size = packets = 0

    def receive():
        nonlocal size, packets
        while True:
            ret = codec.avcodec_receive_packet(context, packet)
            if ret in (EAGAIN, EOF):
                return ret
            if ret < 0:
                raise RuntimeError(f'receive: {ret}')
            size += output.size
            packets += 1
            codec.av_packet_unref(packet)

    try:
        for index in range(PICTURES):
            util.av_frame_unref(pointer)
            frame.width, frame.height, frame.format = WIDTH, HEIGHT, 0  # AV_PIX_FMT_YUV420P
            ret = util.av_frame_get_buffer(pointer, 0)
            if ret < 0:
                raise RuntimeError(f'frame buffer: {ret}')
            for block in range(HEIGHT // 8):
                row = b''.join(bytes([value]) * 8 for value in os.urandom(WIDTH // 8))
                for line in range(8):
                    C.memmove(frame.data[0] + (block * 8 + line) * frame.linesize[0], row, WIDTH)
            for plane in (1, 2):
                C.memset(frame.data[plane], 128, frame.linesize[plane] * (HEIGHT // 2))
            frame.pts = index * interval
            ret = codec.avcodec_send_frame(context, pointer)
            if ret < 0:
                raise RuntimeError(f'send {index}: {ret}')
            receive()
        codec.avcodec_send_frame(context, None)
        if receive() != EOF:
            raise RuntimeError('drain did not end')
    finally:
        util.av_frame_free(C.byref(pointer))
    return {'packets': packets, 'bytes': size,
            'kbps': round(size * 8 / (PICTURES * interval / 1e6) / 1000, 1)}


def rates(directory, name):
    """Run every rate case in a child and compare each with the plain 30 fps stream."""
    measured, failed = [], 0
    for index, (label, _, _) in enumerate(RATES):
        result = subprocess.run([sys.executable, __file__, '--library-dir', str(directory),
                                 '--codec', name, '--rate', str(index)],
                                capture_output=True, text=True, timeout=180)
        try:
            measured.append(json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else None)
        except (IndexError, ValueError):
            measured.append(None)
        if measured[-1] is None:
            failed += 1
            print(f'FAIL {name}: {label}: exit {result.returncode}\n{result.stderr[-2000:]}', flush=True)
    if failed:
        return failed
    plain = measured[0]['kbps']
    for (label, _, _), item in zip(RATES, measured):
        # The first case is held to the requested bitrate, the others to the first.
        target, what = (BITRATE / 1000, 'requested') if item is measured[0] else (plain, 'plain 30 fps')
        ok = item['packets'] == PICTURES and 0.6 * target <= item['kbps'] <= 1.6 * target
        failed += not ok
        print(f'{"PASS" if ok else "FAIL"} {name}: {label}: {item["kbps"]} kb/s in {item["packets"]} packets, '
              f'{what} {target:g} kb/s', flush=True)
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', required=True, type=Path)
    parser.add_argument('--codec', choices=['h264_vaapi', 'hevc_vaapi', 'vp9_vaapi'])
    parser.add_argument('--rate', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.codec:
        probe(args.library_dir, args.codec, None if args.rate is None else RATES[args.rate][1:])
        return 0
    failed = 0
    for name in ['h264_vaapi', 'hevc_vaapi', 'vp9_vaapi']:
        result = subprocess.run([sys.executable, __file__, '--library-dir',
                                 str(args.library_dir), '--codec', name],
                                capture_output=True, text=True, timeout=30)
        ok = result.returncode == 0
        failed += not ok
        print(f'{"PASS" if ok else "FAIL"} {name}: local loading and empty drain', flush=True)
        if not ok:
            print(f'exit {result.returncode}\n{result.stderr[-4000:]}', flush=True)
        else:
            failed += rates(args.library_dir, name)
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
