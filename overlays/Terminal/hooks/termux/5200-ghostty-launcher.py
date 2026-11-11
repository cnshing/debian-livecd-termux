#!/data/data/com.termux/files/usr/bin/python
"""Launch Ghostty through the profile wrapper instead of package D-Bus activation."""
from configparser import ConfigParser

from desktop import BASE, DATA, PREFIX


def configure(base, data, prefix):
    entry = ConfigParser(interpolation=None)
    entry.optionxform = str
    entry.read(prefix / 'share/applications/com.mitchellh.ghostty.desktop')
    # The package's D-Bus service fails to execute on Termux, bypassing our Cairo
    # wrapper as well. Both the dock/menu launch and New Window must use Exec.
    entry['Desktop Entry']['DBusActivatable'] = 'false'
    command = f'"{base}/bin/ghostty" --gtk-single-instance=false'
    for section in entry.sections():
        if 'Exec' in entry[section]:
            entry[section]['Exec'] = command
    destination = data / 'applications/com.mitchellh.ghostty.desktop'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('w') as output:
        entry.write(output, space_around_delimiters=False)


if __name__ == '__main__':
    configure(BASE, DATA, PREFIX)
