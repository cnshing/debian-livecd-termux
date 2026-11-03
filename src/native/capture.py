#!/data/data/com.termux/files/usr/bin/python
"""Capture the compositor frame, including GPU buffers absent from X11 readback."""
from pathlib import Path
import sys

from gi.repository import Gio, GLib


def screenshot(destination):
    destination = Path(destination).absolute()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    name = 'org.gnome.Screenshot'
    result = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
        'org.freedesktop.DBus', 'RequestName', GLib.Variant('(su)', (name, 4)),
        None, Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    if result != 1:
        raise RuntimeError('A screenshot application is already using the capture interface')
    try:
        success, path = bus.call_sync('org.gnome.Shell.Screenshot',
            '/org/gnome/Shell/Screenshot', 'org.gnome.Shell.Screenshot', 'Screenshot',
            GLib.Variant('(bbs)', (False, False, str(destination))), None,
            Gio.DBusCallFlags.NONE, 20000, None).unpack()
        if not success or not Path(path).is_file():
            raise RuntimeError('GNOME compositor capture failed')
        return Path(path)
    finally:
        bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
            'org.freedesktop.DBus', 'ReleaseName', GLib.Variant('(s)', (name,)),
            None, Gio.DBusCallFlags.NONE, 5000, None)


if __name__ == '__main__':
    print(screenshot(sys.argv[1]))
