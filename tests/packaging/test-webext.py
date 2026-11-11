#!/usr/bin/env python3
"""Host checks for extension archive identity, package layout and bootstrap migration."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

REPO = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


archive = module('webext_archive', 'packages/webext-ublock-origin-lite-chromium/archive.py')
runtime = module('webext_runtime', 'src/native/runtime.py')


class WebExtensions(unittest.TestCase):
    def test_archive_rejects_wrong_version_and_identity(self):
        identifier = 'ddkjiahejlhfcafbddmgiahcphecmpfh'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'extension'
            for browser, guid in [('firefox', 'addon@example.org'), ('chromium', identifier)]:
                data = io.BytesIO()
                with zipfile.ZipFile(data, 'w') as payload:
                    payload.writestr('manifest.json', json.dumps({
                        'version': '1.2.3', 'browser_specific_settings': {'gecko': {'id': guid}}}))
                prefix = b''
                if browser == 'chromium':
                    crx_id = bytes.fromhex(identifier.translate(str.maketrans('abcdefghijklmnop', '0123456789abcdef')))
                    header = b'\x0a\x10' + crx_id
                    prefix = struct.pack('<4sII', b'Cr24', 3, len(header)) + header
                path.write_bytes(prefix + data.getvalue())
                archive.validate(path, browser, guid, '1.2.3')
                with self.assertRaisesRegex(ValueError, 'Expected 9'):
                    archive.validate(path, browser, guid, '9')
                with self.assertRaises(ValueError):
                    archive.validate(path, browser, 'a' * 32, '1.2.3')

    def test_packages_coexist_and_chromium_registrations_share_one_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix, source = root / 'prefix', root / 'source'
            source.mkdir()
            (source / 'extension.crx').write_bytes(b'crx fixture')
            (source / 'extension.xpi').write_bytes(b'xpi fixture')
            (source / 'LICENSE').touch()
            for recipe in sorted((REPO / 'packages').glob('webext-*/build.sh')):
                env = {**os.environ, 'TERMUX_PREFIX': str(prefix), 'TERMUX_PKG_SRCDIR': str(source),
                       'TERMUX_PKG_BUILDER_DIR': str(recipe.parent)}
                subprocess.run(['bash', '-ec', 'source "$1"; termux_step_make_install', '-', str(recipe)],
                               cwd=source, env=env, check=True)
            for directory in ['lib/chromium/extensions', 'opt/google/chrome/extensions',
                              'opt/livecd-browsers/chromium-extensions',
                              'opt/livecd-browsers/ungoogled-chromium-extensions']:
                registrations = list((prefix / directory).glob('*.json'))
                self.assertEqual(len(registrations), 3)
                for registration in registrations:
                    descriptor = json.loads(registration.read_text())
                    payload = registration.with_suffix('.crx')
                    self.assertTrue(payload.is_symlink())
                    self.assertEqual(payload.resolve(), Path(descriptor['external_crx']))
                    self.assertEqual(payload.read_bytes(), b'crx fixture')
                    self.assertTrue(descriptor['external_version'])
            addons = prefix / 'share/mozilla/extensions/{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
            self.assertEqual(len(list(addons.glob('*.xpi'))), 4)
            preferences = prefix / 'lib/firefox/browser/defaults/preferences/livecd-extensions.js'
            self.assertIn('pref("extensions.startupScanScopes", 8)', preferences.read_text())

    def test_migration_backs_up_only_the_unchanged_hook_bootstrap(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            addon = home / '.config/livecd-native/firefox/extensions/uBlock0@raymondhill.net.xpi'
            addon.parent.mkdir(parents=True)
            backup = home / 'backup'
            original = b'original hook bootstrap'
            with mock.patch.object(Path, 'home', return_value=home), \
                    mock.patch.object(runtime, 'FIREFOX_UBLOCK_BOOTSTRAP_SHA256', hashlib.sha256(original).hexdigest()):
                addon.write_bytes(b'user updated copy')
                runtime.migrate_firefox_ublock(backup)
                self.assertEqual(addon.read_bytes(), b'user updated copy')
                addon.write_bytes(original)
                runtime.migrate_firefox_ublock(backup)
                self.assertFalse(addon.exists())
                self.assertEqual((backup / addon.relative_to(home)).read_bytes(), original)
                runtime.migrate_firefox_ublock(backup)


if __name__ == '__main__':
    unittest.main()
