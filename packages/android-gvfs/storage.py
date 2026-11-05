"""Discover readable Android storage roots without mounting or redirecting them."""
from collections import Counter
import os
from pathlib import Path
import re


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

