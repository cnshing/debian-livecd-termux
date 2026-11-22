#!/usr/bin/env python3
"""PulseAudio capture probe: stdin u/c/q resumes, corks, or quits; PCM is discarded."""
import ctypes as c
import ctypes.util
import json
import select
import sys
import time


def main():
    pulse = c.CDLL(ctypes.util.find_library('pulse') or 'libpulse.so')

    def function(name, result, *arguments):
        target = getattr(pulse, name)
        target.restype = result
        target.argtypes = arguments
        return target

    pointer = c.c_void_p
    new_loop = function('pa_mainloop_new', pointer)
    api = function('pa_mainloop_get_api', pointer, pointer)
    iterate = function('pa_mainloop_iterate', c.c_int, pointer, c.c_int, pointer)
    new_context = function('pa_context_new', pointer, pointer, c.c_char_p)
    connect = function('pa_context_connect', c.c_int, pointer, c.c_char_p, c.c_int, pointer)
    context_state = function('pa_context_get_state', c.c_int, pointer)
    new_stream = function('pa_stream_new', pointer, pointer, c.c_char_p, pointer, pointer)
    record = function('pa_stream_connect_record', c.c_int, pointer, c.c_char_p, pointer, c.c_int)
    stream_state = function('pa_stream_get_state', c.c_int, pointer)
    cork = function('pa_stream_cork', pointer, pointer, c.c_int, pointer, pointer)
    operation_state = function('pa_operation_get_state', c.c_int, pointer)
    unref_operation = function('pa_operation_unref', None, pointer)
    peek = function('pa_stream_peek', c.c_int, pointer, pointer, pointer)
    drop = function('pa_stream_drop', c.c_int, pointer)
    read_callback = c.CFUNCTYPE(None, pointer, c.c_size_t, pointer)
    set_read = function('pa_stream_set_read_callback', None, pointer, read_callback, pointer)
    total = 0

    @read_callback
    def received(stream, length, userdata):
        nonlocal total
        data = pointer()
        size = c.c_size_t()
        if peek(stream, c.byref(data), c.byref(size)) == 0:
            total += size.value
            drop(stream)

    class SampleSpec(c.Structure):
        _fields_ = [('format', c.c_int), ('rate', c.c_uint32), ('channels', c.c_uint8)]

    loop = new_loop()
    context = new_context(api(loop), b'Bluetooth cork probe')
    stream = None

    def pump_until(check):
        deadline = time.monotonic() + 10
        while not check():
            if time.monotonic() > deadline or iterate(loop, 0, None) < 0:
                raise RuntimeError('PulseAudio operation timed out')
            time.sleep(0.005)

    try:
        if connect(context, None, 0, None) < 0:
            raise RuntimeError('PulseAudio connection failed')
        pump_until(lambda: context_state(context) == 4)
        spec = SampleSpec(3, 48000, 1)
        stream = new_stream(context, b'Bluetooth capture probe', c.byref(spec), None)
        set_read(stream, received, None)
        if record(stream, sys.argv[1].encode(), None, 1) < 0:
            raise RuntimeError('PulseAudio capture failed')
        pump_until(lambda: stream_state(stream) == 2)
        print(json.dumps({'ready': True, 'corked': True}), flush=True)
        while True:
            if iterate(loop, 0, None) < 0:
                raise RuntimeError('PulseAudio mainloop failed')
            if select.select([sys.stdin], [], [], 0.01)[0]:
                command = sys.stdin.readline().strip()
                if command not in ('c', 'u'):
                    return
                operation = cork(stream, int(command == 'c'), None, None)
                if not operation:
                    raise RuntimeError('PulseAudio cork request failed')
                pump_until(lambda: operation_state(operation) != 0)
                unref_operation(operation)
                print(json.dumps({'corked': command == 'c', 'bytes': total}), flush=True)
    finally:
        if stream:
            function('pa_stream_disconnect', c.c_int, pointer)(stream)
            function('pa_stream_unref', None, pointer)(stream)
        function('pa_context_disconnect', None, pointer)(context)
        function('pa_context_unref', None, pointer)(context)
        function('pa_mainloop_free', None, pointer)(loop)


if __name__ == '__main__':
    main()
