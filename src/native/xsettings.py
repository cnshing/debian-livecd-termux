#!/data/data/com.termux/files/usr/bin/python
"""Keep X11 GTK settings in sync with this native profile's GNOME settings."""
import json
from pathlib import Path
import signal
import subprocess
from gi.repository import Gio, GLib

settings = Gio.Settings.new('org.gnome.desktop.interface')
privacy = Gio.Settings.new('org.gnome.desktop.privacy')
path = Path(__file__).resolve().parent / 'xsettingsd.conf'
process = None


def update(*_args):
    global process
    names = {'gtk-theme': 'Net/ThemeName', 'icon-theme': 'Net/IconThemeName',
             'font-name': 'Gtk/FontName', 'cursor-theme': 'Gtk/CursorThemeName'}
    text = ''.join(names[key] + ' ' + json.dumps(settings.get_string(key)) + '\n' for key in names)
    text += 'Xft/Antialias 1\nXft/DPI ' + str(round(settings.get_double('text-scaling-factor') * 96 * 1024)) + '\n'
    # GTK's file history follows Settings > Privacy, as with GNOME's own XSettings daemon.
    text += 'Gtk/RecentFilesEnabled ' + str(int(privacy.get_boolean('remember-recent-files'))) + '\n'
    text += 'Gtk/RecentFilesMaxAge ' + str(privacy.get_int('recent-files-max-age')) + '\n'
    path.write_text(text)
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=3)
    process = subprocess.Popen(['xsettingsd', '-c', str(path)])


for key in ('gtk-theme', 'icon-theme', 'font-name', 'cursor-theme', 'text-scaling-factor'):
    settings.connect('changed::' + key, update)
for key in ('remember-recent-files', 'recent-files-max-age'):
    privacy.connect('changed::' + key, update)
update()
GLib.MainLoop().run()
