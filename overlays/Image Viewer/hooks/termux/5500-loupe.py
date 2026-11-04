#!/data/data/com.termux/files/usr/bin/python
"""Select Loupe for its supported image types in the private desktop profile."""
from configparser import ConfigParser

from desktop import CONFIG, PREFIX


def configure(config, prefix):
    entry = ConfigParser(interpolation=None)
    entry.optionxform = str
    entry.read(prefix / 'share/applications/org.gnome.Loupe.desktop')
    mime_types = entry['Desktop Entry']['MimeType'].strip(';').split(';')
    path = config / 'mimeapps.list'
    associations = ConfigParser(interpolation=None, strict=False)
    associations.optionxform = str
    associations.read(path)
    if not associations.has_section('Default Applications'):
        associations.add_section('Default Applications')
    for mime in mime_types:
        if mime.startswith('image/'):
            associations['Default Applications'][mime] = 'org.gnome.Loupe.desktop;'
    config.mkdir(parents=True, exist_ok=True)
    with path.open('w') as output:
        associations.write(output, space_around_delimiters=False)


if __name__ == '__main__':
    configure(CONFIG, PREFIX)
