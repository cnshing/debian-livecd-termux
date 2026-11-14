#!/usr/bin/env python3
"""Launch only Ghostty with a privately extracted experimental GTK library.

Copy beside gtk-dmabuf/lib/ on the device and pass this file as
panvk-desktop.py --ghostty-launcher. PANVK_GTK_LIB_DIR overrides that directory.
The surrounding test supplies the private Mesa/ICD and display environment.
"""
import os
from pathlib import Path
import sys

library_dir = Path(os.environ.get('PANVK_GTK_LIB_DIR',
                                 str(Path(__file__).resolve().parent / 'gtk-dmabuf/lib'))).resolve(strict=True)
(library_dir / 'libgtk-4.so.1').resolve(strict=True)
os.environ['LD_LIBRARY_PATH'] = ':'.join(filter(None, (
    str(library_dir), os.environ.get('LD_LIBRARY_PATH', ''))))
os.environ['GDK_DEBUG'] = ','.join(filter(None, (os.environ.get('GDK_DEBUG', ''), 'dmabuf')))
ghostty = str(Path(os.environ['PREFIX']) / 'bin/ghostty')
os.execv(ghostty, [ghostty, *sys.argv[1:]])
