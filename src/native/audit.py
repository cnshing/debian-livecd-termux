#!/data/data/com.termux/files/usr/bin/python
"""Recursively audit every private ELF's interpreter and DT_NEEDED closure."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

# Termux's binutils names GNU readelf greadelf.
READELF = shutil.which('readelf') or 'greadelf'


def audit(root, prefix, extra_roots=()):
    roots = [root, *extra_roots]
    directories = [root / 'lib', root / 'lib/mutter-16', root / 'lib/gnome-shell',
                   prefix / 'lib', Path('/system/lib64'), Path('/apex/com.android.runtime/lib64/bionic')]
    visited = set()
    records = []
    missing = set()
    queue = [p for base in roots for p in base.rglob('*') if p.is_file() and not p.is_symlink() and p.open('rb').read(4) == b'\x7fELF']
    while queue:
        path = queue.pop()
        if path.resolve() in visited:
            continue
        visited.add(path.resolve())
        details = subprocess.check_output([READELF, '-d', '-l', str(path)], text=True)
        needed = re.findall(r'\(NEEDED\).*?\[(.*?)\]', details)
        interpreter = re.findall(r'Requesting program interpreter: (.*?)\]', details)
        if interpreter and interpreter != ['/system/bin/linker64']:
            missing.add('non-Android interpreter: ' + str(path))
        dependencies = {}
        for name in needed:
            candidate = next((d / name for d in [path.parent, *directories] if (d / name).is_file()), None)
            dependencies[name] = str(candidate) if candidate else None
            if candidate is None:
                missing.add(name)
            elif str(candidate).startswith(tuple(str(p) for p in [*roots, prefix])):
                queue.append(candidate)
        records.append({'path': str(path), 'interpreter': interpreter, 'needed': dependencies})
    return {'ok': not missing, 'missing': sorted(missing), 'elf_count': len(records), 'files': records}


if __name__ == '__main__':
    gpu = Path.home() / '.local/opt/livecd-native/gpu'
    result = audit(Path.home() / '.local/opt/livecd-native/gnome-48', Path(os.environ['PREFIX']),
                   [gpu.resolve()] if gpu.is_dir() else [])
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['ok'] else 1)
