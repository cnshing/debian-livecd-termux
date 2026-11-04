"""Remove only the previous helper's owned bookmarks during stopped setup."""
import json
from pathlib import Path


def retire_bookmarks(config, state, home):
    from gi.repository import Gio, GLib

    record = state / 'storage-bookmarks.json'
    try:
        owned = json.loads(record.read_text())['owned']
    except (OSError, ValueError, KeyError, TypeError):
        owned = []
    if not isinstance(owned, list) or not all(isinstance(line, str) for line in owned):
        owned = []
    file = Gio.File.new_for_path(str(config / 'gtk-3.0/bookmarks'))
    for attempt in range(3):
        try:
            _, contents, etag = file.load_contents(None)
            text = bytes(contents).decode('utf-8', errors='surrogateescape')
            updated = ''.join(line for line in text.splitlines(keepends=True)
                              if line.rstrip('\r\n') not in owned)
            if updated != text:
                file.replace_contents(updated.encode('utf-8', errors='surrogateescape'), etag,
                                      False, Gio.FileCreateFlags.PRIVATE, None)
            break
        except GLib.Error as error:
            if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.WRONG_ETAG):
                continue
            if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
                break
            raise
    else:
        raise RuntimeError('Bookmarks changed during migration; retry with Files closed.')
    record.unlink(missing_ok=True)
    base = home / '.local/lib/livecd-native'
    for relative in ['storage-bookmarks.py', 'autostart/livecd-storage-bookmarks.desktop']:
        (base / relative).unlink(missing_ok=True)
