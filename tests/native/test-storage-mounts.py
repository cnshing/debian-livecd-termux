#!/usr/bin/env python3
"""Android mount discovery and migration checks; --integration tests real GIO proxies."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('LIVECD_STORAGE_SOURCE', str(ROOT / 'packages/livecd-storage'))) / 'storage.py'
spec = importlib.util.spec_from_file_location('android_storage', SOURCE)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)
HAVE_GIO = importlib.util.find_spec('gi') is not None


def mount(path, device='0:50'):
    return f'20 1 {device} / {path} rw - fuse /dev/fuse rw\n'


class Discovery(unittest.TestCase):
    def discover(self, text, readable=()):
        return storage.storage_locations(text, Path('/storage/emulated/0'),
                                         lambda path: str(path) in readable)

    def test_internal_and_card_root_avoid_app_directory_and_duplicate_views(self):
        info = (mount('/storage/emulated') + mount('/storage/emulated/0/Android/data') +
                mount('/storage/TEST-0001') + mount('/mnt/media_rw/TEST-0001', '179:1') +
                mount('/mnt/runtime/read/TEST-0001'))
        found = self.discover(info, {'/storage/emulated/0', '/storage/TEST-0001',
                                   '/mnt/media_rw/TEST-0001', '/mnt/runtime/read/TEST-0001'})
        self.assertEqual(found, {'file:///storage/emulated/0': 'Internal storage',
                                 'file:///storage/TEST-0001': 'SD card'})

    def test_denied_or_removed_volumes_are_not_bookmarked(self):
        self.assertEqual(self.discover(mount('/storage/TEST-0001')), {})
        self.assertEqual(self.discover('', {'/storage/TEST-0001'}), {})

    def test_accessible_media_path_is_a_fallback(self):
        info = mount('/storage/TEST-0001') + mount('/mnt/media_rw/TEST-0001', '179:1')
        found = self.discover(info, {'/mnt/media_rw/TEST-0001'})
        self.assertEqual(found, {'file:///mnt/media_rw/TEST-0001': 'SD card'})

    def test_multiple_cards_get_distinct_labels(self):
        info = mount('/storage/TEST-0001', '179:1') + mount('/storage/TEST-0002', '179:2')
        found = self.discover(info, {'/storage/TEST-0001', '/storage/TEST-0002'})
        self.assertEqual(set(found.values()), {'SD card (TEST-0001)', 'SD card (TEST-0002)'})

    def test_usb_is_identified_from_device_ancestry(self):
        with tempfile.TemporaryDirectory() as directory:
            devices = Path(directory)
            (devices / '8:1').symlink_to(devices / 'platform/usb1/drive/partition')
            found = storage.storage_locations(mount('/storage/TEST-0001') +
                      mount('/mnt/media_rw/TEST-0001', '8:1'), Path('/sdcard'),
                      lambda path: str(path) == '/storage/TEST-0001', devices)
            self.assertEqual(found, {'file:///storage/TEST-0001': 'USB drive'})

    def test_unknown_hardware_has_an_honest_label(self):
        found = self.discover(mount('/storage/TEST-0001'), {'/storage/TEST-0001'})
        self.assertEqual(found['file:///storage/TEST-0001'], 'Removable storage')

    def test_mount_escapes_are_decoded_before_uri_encoding(self):
        found = self.discover(mount('/storage/Test\\040Drive'), {'/storage/Test Drive'})
        self.assertEqual(found, {'file:///storage/Test%20Drive': 'Removable storage'})


@unittest.skipUnless(HAVE_GIO, 'Migration uses GIO file replacement')
class Migration(unittest.TestCase):
    def test_only_exact_owned_bookmarks_are_removed(self):
        spec = importlib.util.spec_from_file_location('migrate', SOURCE.with_name('migrate.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config, state = home / 'config', home / 'state'
            (config / 'gtk-3.0').mkdir(parents=True)
            state.mkdir()
            owned = 'file:///storage/TEST-0001 SD card'
            user = 'file:///storage/TEST-0001 My card\nsftp://example.invalid/project Work\n'
            bookmarks = config / 'gtk-3.0/bookmarks'
            bookmarks.write_text(owned + '\n' + user)
            import json
            (state / 'storage-bookmarks.json').write_text(json.dumps({'owned': [owned]}))
            base = home / '.local/lib/livecd-native'
            (base / 'autostart').mkdir(parents=True)
            (base / 'storage-bookmarks.py').touch()
            (base / 'autostart/livecd-storage-bookmarks.desktop').touch()
            module.retire_bookmarks(config, state, home)
            self.assertEqual(bookmarks.read_text(), user)
            self.assertFalse((state / 'storage-bookmarks.json').exists())
            self.assertFalse((base / 'storage-bookmarks.py').exists())
            self.assertFalse((base / 'autostart/livecd-storage-bookmarks.desktop').exists())
            # Re-running setup must preserve the user's existing bookmark file.
            before = bookmarks.stat().st_mtime_ns
            module.retire_bookmarks(config, state, home)
            self.assertEqual(bookmarks.stat().st_mtime_ns, before)


if __name__ == '__main__':
    import sys
    if '--integration' in sys.argv:
        from storage_mount_integration import integration
        integration(SOURCE.parent)
    else:
        unittest.main()
