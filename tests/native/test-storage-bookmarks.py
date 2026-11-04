#!/usr/bin/env python3
"""Storage discovery/ownership checks; run on host or in the native desktop."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('STORAGE_BOOKMARKS_SOURCE',
              str(ROOT / 'overlays/File Manager/filesystem/termux/home/.local/lib/livecd-native/storage-bookmarks.py')))
spec = importlib.util.spec_from_file_location('storage_bookmarks', SOURCE)
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


class Ownership(unittest.TestCase):
    uri = 'file:///storage/TEST-0001'
    line = uri + ' SD card'

    def test_existing_custom_bookmarks_and_formatting_survive(self):
        user = 'sftp://example.invalid/project Work\n\nfile:///home/example/projects Projects'
        text, owned = storage.merge_bookmarks(user, [], {self.uri: 'SD card'})
        self.assertTrue(text.startswith(user + '\n'))
        self.assertEqual(owned, [self.line])
        again, managed = storage.merge_bookmarks(text, owned, {self.uri: 'SD card'})
        self.assertEqual(again, text)
        self.assertEqual(managed, owned)

    def test_unplug_removes_only_owned_bookmarks(self):
        user = 'sftp://example.invalid/project Work\n'
        text, owned = storage.merge_bookmarks(user + self.line + '\n', [self.line], {})
        self.assertEqual(text, user)
        self.assertEqual(owned, [])

    def test_a_user_bookmark_to_the_same_volume_is_not_owned(self):
        user = self.uri + ' My files\n'
        text, owned = storage.merge_bookmarks(user, [], {self.uri: 'SD card'})
        self.assertEqual(text, user)
        self.assertEqual(owned, [])
        self.assertEqual(storage.merge_bookmarks(text, owned, {})[0], user)

    def test_user_renaming_an_automatic_bookmark_transfers_ownership(self):
        user = self.uri + ' Photos\n'
        text, owned = storage.merge_bookmarks(user, [self.line], {})
        self.assertEqual(text, user)
        self.assertEqual(owned, [])

    def test_user_reordering_is_preserved(self):
        text = self.line + '\nsftp://example.invalid/project Work\n'
        self.assertEqual(storage.merge_bookmarks(text, [self.line], {self.uri: 'SD card'})[0], text)

    def test_label_changes_and_reinsertions_do_not_accumulate_duplicates(self):
        text, owned = storage.merge_bookmarks(self.line + '\n', [self.line], {self.uri: 'SD card (TEST-0001)'})
        self.assertEqual(text.count(self.uri), 1)
        text, owned = storage.merge_bookmarks(text, owned, {})
        text, owned = storage.merge_bookmarks(text, owned, {self.uri: 'SD card'})
        self.assertEqual(text, self.line + '\n')

    def test_malformed_unrelated_bookmark_is_preserved(self):
        user = 'smb://[broken Example\n'
        text, owned = storage.merge_bookmarks(user, [], {self.uri: 'SD card'})
        self.assertTrue(text.startswith(user))


@unittest.skipUnless(HAVE_GIO, 'GIO file replacement requires native PyGObject')
class Persistence(unittest.TestCase):
    def test_gio_updates_and_removes_managed_entries_without_touching_custom_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bookmarks, state = root / 'gtk-3.0/bookmarks', root / 'state/storage.json'
            bookmarks.parent.mkdir()
            user = 'sftp://example.invalid/project Work\n'
            bookmarks.write_text(user)
            locations = {'file:///storage/TEST-0001': 'SD card'}
            storage.synchronize(bookmarks, state, locations)
            self.assertIn('SD card', bookmarks.read_text())
            first_mtime = bookmarks.stat().st_mtime_ns
            storage.synchronize(bookmarks, state, locations)
            self.assertEqual(bookmarks.stat().st_mtime_ns, first_mtime)
            storage.synchronize(bookmarks, state, {})
            self.assertEqual(bookmarks.read_text(), user)

    def test_concurrent_files_edit_is_reloaded_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bookmarks, state = root / 'bookmarks', root / 'state.json'
            user = 'sftp://example.invalid/project Work\n'
            edited = user + 'file:///home/example/notes Notes\n'
            bookmarks.write_text(user)
            merge = storage.merge_bookmarks
            first = True

            def concurrent_edit(text, owned, locations):
                nonlocal first
                if first:
                    first = False
                    bookmarks.write_text(edited)
                return merge(text, owned, locations)

            with mock.patch.object(storage, 'merge_bookmarks', side_effect=concurrent_edit):
                storage.synchronize(bookmarks, state, {'file:///storage/TEST-0001': 'SD card'})
            self.assertTrue(bookmarks.read_text().startswith(edited))

    def test_first_run_creates_bookmark_directory_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bookmarks, state = root / 'gtk-3.0/bookmarks', root / 'state/storage.json'
            storage.synchronize(bookmarks, state, {'file:///storage/TEST-0001': 'SD card'})
            self.assertEqual(bookmarks.read_text(), 'file:///storage/TEST-0001 SD card\n')
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
