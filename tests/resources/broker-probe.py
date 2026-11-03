#!/usr/bin/env python3
"""Interactive native client for the PC-side broker lifecycle test."""
import ctypes
import json
import os
import sys
import time

library = ctypes.CDLL('liblivecd_resources.so')
library.livecd_resources_snapshot.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t)]
library.livecd_resources_free.argtypes = [ctypes.c_void_p]


def sample(category):
    data, length = ctypes.c_void_p(), ctypes.c_size_t()
    started = time.monotonic()
    error = library.livecd_resources_snapshot(category.encode(), ctypes.byref(data), ctypes.byref(length))
    payload = ctypes.string_at(data, length.value) if data.value else b''
    library.livecd_resources_free(data)
    result = {'category': category, 'error': error, 'bytes': len(payload),
              'latency_ms': round((time.monotonic() - started) * 1000, 3)}
    if category == 'stat' and not error:
        result['ticks'] = sum(map(int, payload.splitlines()[0].split()[1:9]))
    return result


print(json.dumps(dict(sample('stat'), pid=os.getpid(), uid=os.getuid())), flush=True)
for line in sys.stdin:
    category = line.strip()
    if category == 'quit':
        break
    print(json.dumps(sample(category)), flush=True)
