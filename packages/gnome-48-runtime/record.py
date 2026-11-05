#!/usr/bin/env python3
"""Record recipe inputs for device diagnostics and application GPU selection."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    name, prefix, builder, version, url, checksum = sys.argv[1:]
    patches = sorted(Path(builder).glob('*.patch'))
    record = {
        'package': 'livecd-' + name, 'version': version, 'url': url,
        'sha256': checksum, 'build_system': 'termux-packages',
        'patches': [path.name for path in patches],
        'patches_sha256': hashlib.sha256(b''.join(
            path.name.encode() + path.read_bytes() for path in patches)).hexdigest(),
    }
    destination = Path(prefix) / 'share/doc' / name
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'build-source.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
