#!/usr/bin/env python3
"""Prepare an opt-in GTK artifact; never added to the normal package repository."""
import os
import pathlib
import shutil
import sys

checkout = pathlib.Path(sys.argv[1])
recipe = checkout / 'x11-packages/gtk4'
x11_egl = os.environ.get('GTK_DMABUF_X11_EGL') == '1'
patch = recipe / 'meson.build.patch'
text = patch.read_text()
old = "+cdata.set('HAVE_DMABUF', false)"
assert text.count(old) == 1, 'pinned Termux DMA-BUF disable patch changed'
# Keep the Android/Linux adjustment, UDMABUF disable and X11 EGL workaround.
patch.write_text(text.replace(old, "+cdata.set('HAVE_DMABUF', cc.has_header('linux/dma-buf.h'))"))
build = recipe / 'build.sh'
text = build.read_text()
assert 'TERMUX_PKG_REVISION=' not in text, 'review upstream revision before overriding'
# Separate artifact identity. Extract privately for testing; do not apt-install.
text += f'\nTERMUX_PKG_REVISION={102 if x11_egl else 101}\n'
# Keep GDK_DEBUG=dmabuf diagnostics for positive import/download evidence.
text += '\nTERMUX_PKG_EXTRA_CONFIGURE_ARGS+=" -Ddebug=true"\n'
build.write_text(text)

# Ghostty clears GDK_DEBUG itself. Keep positive diagnostics in this private build.
shutil.copyfile(pathlib.Path(__file__).with_name('gtk-dmabuf-diagnostics.patch'),
                recipe / 'dmabuf-diagnostics.patch')

if x11_egl:
    (recipe / 'no-egl.patch').unlink()
