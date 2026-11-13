#!/usr/bin/env python3
"""Check Firefox's private FFmpeg runtime without starting a browser.

Run with the session's VA driver/preload and a private daemon socket. Each child
loads the codec libraries locally, as Firefox does, opens an I420 VAAPI encoder,
and drains it without submitting a picture. Firefox does this after recreating
an encoder at flush. A failed VA display or a signal is a failed check.
"""
import argparse
import ctypes as C
from pathlib import Path
import subprocess
import sys

EOF = -541478725  # AVERROR_EOF


def probe(directory, name):
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
        options = {'video_size': '640x360', 'pixel_format': 'yuv420p',
                   'time_base': '1/30', 'b': '2000000', 'bf': '0', 'g': '30'}
        if name == 'h264_vaapi':
            options['profile'] = '66'
        for key, value in options.items():
            ret = util.av_opt_set(context, key.encode(), value.encode(), 1)
            if ret < 0:
                raise RuntimeError(f'{key}: {ret}')
        ret = codec.avcodec_open2(context, encoder, None)
        if ret < 0:
            raise RuntimeError(f'open: {ret}')
        ret = codec.avcodec_send_frame(context, None)
        if ret not in (0, EOF):
            raise RuntimeError(f'empty drain send: {ret}')
        ret = codec.avcodec_receive_packet(context, packet)
        if ret != EOF:
            raise RuntimeError(f'empty drain receive: {ret}, expected EOF')
    finally:
        codec.av_packet_free(C.byref(packet))
        codec.avcodec_free_context(C.byref(context))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-dir', required=True, type=Path)
    parser.add_argument('--codec', choices=['h264_vaapi', 'hevc_vaapi', 'vp9_vaapi'])
    args = parser.parse_args()
    if args.codec:
        probe(args.library_dir, args.codec)
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
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
