#!/usr/bin/env python3
"""Generate the schemas needed by Shell without installing desktop daemons."""
from pathlib import Path
import re
import sys


def main():
    source, prefix = map(Path, sys.argv[1:])
    schemas = prefix / 'share/glib-2.0/schemas'
    schemas.mkdir(parents=True, exist_ok=True)
    color = (source / 'data/org.gnome.settings-daemon.plugins.color.gschema.xml.in').read_text()
    (schemas / 'org.gnome.settings-daemon.plugins.color.gschema.xml').write_text(
        color.replace('@GETTEXT_PACKAGE@', 'gnome-settings-daemon'))
    peripherals = (source / 'data/org.gnome.settings-daemon.peripherals.gschema.xml.in').read_text()
    touchscreen = re.search(r'<schema [^>]*id="org\.gnome\.settings-daemon\.peripherals\.touchscreen".*?</schema>',
                            peripherals, re.DOTALL).group()
    (schemas / 'org.gnome.settings-daemon.peripherals.touchscreen.gschema.xml').write_text(
        '<schemalist>' + touchscreen.replace('@GETTEXT_PACKAGE@', 'gnome-settings-daemon') + '</schemalist>\n')
    search = (source / 'localsearch-3.9.0/data/org.freedesktop.Tracker.Miner.Files.gschema.xml').read_text()
    (schemas / 'org.freedesktop.Tracker3.Miner.Files.gschema.xml').write_text(
        search.replace('@INDEX_RECURSIVE_DIRS@', '').replace('@INDEX_SINGLE_DIRS@', ''))


if __name__ == '__main__':
    main()
