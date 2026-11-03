#!/usr/bin/env python3
"""Preserve each input's attribution under a distinct package license filename."""
import json
from pathlib import Path
import shutil
import sys


def main():
    source, builder = map(Path, sys.argv[1:])
    licenses = source / 'licenses'
    licenses.mkdir(exist_ok=True)
    for item in json.loads((builder / 'sources.json').read_text()):
        if item['package'] == 'arcmenu-icons':
            continue  # The ArcMenu copyright already covers its icons.
        shutil.copy2(source / 'usr/share/doc' / item['package'] / 'copyright',
                     licenses / (item['package'] + '.copyright'))


if __name__ == '__main__':
    main()
