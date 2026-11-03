#!/usr/bin/env python3
"""Capture a Cairo-rendered X11 client independently of the compositor."""
import sys
import gi

gi.require_version('Gdk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Gdk, GdkX11

window = GdkX11.X11Window.foreign_new_for_display(Gdk.Display.get_default(), int(sys.argv[1]))
_, _, width, height = window.get_geometry()
pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, width, height)
pixbuf.savev(sys.argv[2], 'png', [], [])
