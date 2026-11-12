#!/usr/bin/env python3
"""Check Termux dlopen names and every symbol in the reviewed WSI source."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re

p = argparse.ArgumentParser()
p.add_argument('source', type=Path, help='pinned src/vulkan/wsi/wsi_x11_dlopen.c')
a = p.parse_args()
source = a.source.read_text()
table = source.split('static const char *const wsi_x11_libs[] = {', 1)[1].split('};', 1)[0]
libraries = [re.sub(r'\.so\..*', '.so', name) for name in re.findall(r'"([^"]+)"', table)]
symbols = re.findall(r'^   S\((\w+)\)', source, re.M)
assert libraries and symbols, 'No WSI library/symbol table found'
result = {'libraries': libraries, 'symbols_checked': len(symbols), 'missing': [], 'load_errors': {}}
handles = []
for name in libraries:
    try:
        handles.append(ctypes.CDLL(name, mode=os.RTLD_NOW | os.RTLD_LOCAL))
    except OSError as error:
        result['load_errors'][name] = str(error)
for name in symbols:
    for handle in handles:
        try:
            getattr(handle, name)
            break
        except AttributeError:
            pass
    else:
        result['missing'].append(name)
result['ok'] = not result['missing'] and not result['load_errors']
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['ok'] else 1)
