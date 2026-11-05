#!/usr/bin/env python3
"""Colloid also names a few full-color icons -symbolic. GTK paints a symbolic icon in one color,
which turns those into solid squares, as with elementary Code's menu button, so leave the name
to Colloid's real symbolic icon.  Usage: symbolic.py ICONS_DIRECTORY"""
from pathlib import Path
import re
import sys

for link in Path(sys.argv[1]).glob('Colloid*/*/*/*-symbolic.svg'):
    if not link.is_symlink() or link.parent.name == 'symbolic':
        continue
    twin = link.parent.parent / 'symbolic' / link.name
    if twin.exists() and re.search(r'<image|<rect[^>]*fill="#', link.resolve().read_text()):
        link.unlink()
