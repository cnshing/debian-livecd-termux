#!/usr/bin/env python3
"""Check the API-24 rename shim's exclusive-publish behavior on real files."""
import ctypes
import errno
from pathlib import Path
import sys
import tempfile

library = ctypes.CDLL(str(Path(sys.argv[1]).resolve()), use_errno=True)
rename = library.renameat2
rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
rename.restype = ctypes.c_int

with tempfile.TemporaryDirectory(prefix='serein-rename-') as temporary:
    root = Path(temporary)
    source, destination = root / 'partial', root / 'attachment'
    source.write_bytes(b'complete')
    assert rename(-100, bytes(source), -100, bytes(destination), 1) == 0
    assert not source.exists() and destination.read_bytes() == b'complete'
    source.write_bytes(b'replacement')
    assert rename(-100, bytes(source), -100, bytes(destination), 1) == -1
    assert ctypes.get_errno() == errno.EEXIST
    assert source.read_bytes() == b'replacement' and destination.read_bytes() == b'complete'
    link = root / 'existing-link'
    link.symlink_to(destination)
    assert rename(-100, bytes(source), -100, bytes(link), 1) == -1
    assert ctypes.get_errno() == errno.EEXIST
    assert link.is_symlink() and destination.read_bytes() == b'complete'
print('Exclusive publish passed: new file published; existing file and symlink preserved')
