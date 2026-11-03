#!/data/data/com.termux/files/usr/bin/python
"""Give the desktop's Firefox profile a pinned, signed uBlock Origin. Firefox then updates it."""
from pathlib import Path
import shutil

from prepare import fetch

VERSION = '1.67.0'
addon = fetch({'url': 'https://addons.mozilla.org/firefox/downloads/file/4598854/ublock_origin-1.67.0.xpi',
               'sha256': 'b83c6ec49f817a8d05d288b53dbc7005cceccf82e9490d8683b3120aab3c133a'},
              'ublock-origin-' + VERSION + '.xpi')
addons = Path.home() / '.config/livecd-native/firefox/extensions'
addons.mkdir(parents=True, exist_ok=True)
shutil.copy2(addon, addons / 'uBlock0@raymondhill.net.xpi')
