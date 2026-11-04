#!/data/data/com.termux/files/usr/bin/python
"""Keep readable Android storage in the native Files sidebar."""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urlsplit


def readable_directory(path):
    try:
        with os.scandir(path) as entries:
            next(entries, None)
        return os.access(path, os.R_OK | os.X_OK)
    except OSError:
        return False


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def storage_locations(mountinfo, shared=Path('/sdcard'), accessible=readable_directory,
                      devices=Path('/sys/dev/block')):
    """Use Android's public mount paths; runtime views are duplicate aliases."""
    volumes = {}
    for line in mountinfo.splitlines():
        fields = line.split(' - ', 1)[0].split()
        if len(fields) < 6:
            continue
        path = Path(unescape_mount(fields[4]))
        if path.parent not in (Path('/storage'), Path('/mnt/media_rw')):
            continue
        if path.name in ('emulated', 'self'):
            continue
        volumes.setdefault(path.name, []).append((path, fields[2]))
    locations = []
    if accessible(shared):
        locations.append((shared.resolve(), 'Internal storage'))
    removable = []
    for volume, paths in sorted(volumes.items()):
        paths.sort(key=lambda item: item[0].parent != Path('/storage'))
        usable = next((path for path, device in paths if accessible(path)), None)
        if usable is None:
            continue
        kind = 'Removable storage'
        for path, device in paths:
            try:
                hardware = str((devices / device).resolve())
            except OSError:
                hardware = ''
            if '/usb' in hardware:
                kind = 'USB drive'
                break
            if '/mmc_host/' in hardware or device.startswith('179:'):
                kind = 'SD card'
        removable.append((usable.resolve(), kind, volume))
    counts = Counter(kind for path, kind, volume in removable)
    for path, kind, volume in removable:
        label = f'{kind} ({volume})' if counts[kind] > 1 else kind
        if all(path != previous for previous, name in locations):
            locations.append((path, label))
    return {path.as_uri(): label for path, label in locations}


def bookmark_key(line):
    """Recognize aliases such as /sdcard without changing a user's bookmark."""
    uri = line.partition(' ')[0]
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return uri
    if parsed.scheme == 'file' and parsed.netloc in ('', 'localhost'):
        return str(Path(unquote(parsed.path)).resolve())
    return uri


def merge_bookmarks(text, owned, locations):
    wanted = {uri + ' ' + label for uri, label in locations.items()}
    lines = text.splitlines()
    # A renamed custom label no longer matches our exact ownership record.
    lines = [line for line in lines if line not in owned or line in wanted]
    existing = {bookmark_key(line) for line in lines}
    added = set()
    for uri, label in locations.items():
        line = uri + ' ' + label
        if bookmark_key(uri) not in existing:
            lines.append(line)
            existing.add(bookmark_key(uri))
            added.add(line)
    managed = (set(lines) & set(owned) & wanted) | added
    # Do not rewrite a user's formatting when there is no actual change.
    updated = text if lines == text.splitlines() else ''.join(line + '\n' for line in lines)
    return updated, sorted(managed)


def synchronize(bookmarks, state, locations):
    from gi.repository import Gio, GLib

    try:
        data = json.loads(state.read_text())
        owned = data['owned']
        if not isinstance(owned, list) or not all(isinstance(line, str) for line in owned):
            owned = []
    except (OSError, ValueError, KeyError, TypeError):
        owned = []
    bookmarks.parent.mkdir(parents=True, exist_ok=True)
    file = Gio.File.new_for_path(str(bookmarks))
    for attempt in range(3):
        try:
            success, contents, etag = file.load_contents(None)
            text = bytes(contents).decode('utf-8', errors='surrogateescape')
        except GLib.Error as error:
            if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
                raise
            text, etag = '', None
        updated, managed = merge_bookmarks(text, owned, locations)
        if updated != text:
            try:
                file.replace_contents(updated.encode('utf-8', errors='surrogateescape'), etag,
                                      False, Gio.FileCreateFlags.PRIVATE, None)
            except GLib.Error as error:
                if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.WRONG_ETAG):
                    continue  # Re-read a concurrent edit made by Files.
                raise
        saved = json.dumps({'owned': managed}, indent=2) + '\n'
        if not state.exists() or state.read_text() != saved:
            state.parent.mkdir(parents=True, exist_ok=True)
            temporary = state.with_suffix('.tmp')
            temporary.write_text(saved)
            temporary.chmod(0o600)
            temporary.replace(state)
        return
    raise RuntimeError('Files bookmarks kept changing; will retry on the next scan')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true', help='Refresh every three seconds')
    args = parser.parse_args()
    if not os.environ.get('LIVECD_NATIVE_SESSION'):
        raise SystemExit('Run through livecd-native exec inside the native desktop.')
    config = Path(os.environ['XDG_CONFIG_HOME'])
    state = Path(os.environ['XDG_STATE_HOME']) / 'storage-bookmarks.json'
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    with (runtime / 'storage-bookmarks.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        previous_error = None
        while True:
            try:
                locations = storage_locations(Path('/proc/self/mountinfo').read_text())
                synchronize(config / 'gtk-3.0/bookmarks', state, locations)
                previous_error = None
            except Exception as error:
                if not args.watch:
                    raise
                if str(error) != previous_error:
                    print('Storage bookmarks: ' + str(error), file=sys.stderr, flush=True)
                    previous_error = str(error)
            if not args.watch:
                return
            time.sleep(3)


if __name__ == '__main__':
    main()
