#!/usr/bin/env python3
"""Check that the shipped wallpaper collection can populate GNOME Appearance."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / 'overlays/Desktop Environment+Theming'
SOURCE = OVERLAY / 'filesystem/live_installed/usr/share/backgrounds'


class WallpaperCatalog(unittest.TestCase):
    def test_complete_collection_has_loadable_catalog_and_preserves_other_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / 'backgrounds').symlink_to(SOURCE, target_is_directory=True)
            other = data / 'gnome-background-properties/custom.xml'
            other.parent.mkdir()
            other.write_text('<wallpapers/>')
            desktop = types.ModuleType('desktop')
            desktop.DATA = data
            spec = importlib.util.spec_from_file_location('wallpapers',
                       OVERLAY / 'hooks/termux/2750-register-backgrounds.py')
            module = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, desktop=desktop):
                spec.loader.exec_module(module)
            catalog = module.register_backgrounds()
            first = catalog.read_bytes()
            module.register_backgrounds()
            self.assertEqual(first, catalog.read_bytes())
            self.assertEqual(other.read_text(), '<wallpapers/>')
            items = ET.parse(catalog).getroot().findall('wallpaper')
            images = {p.resolve() for p in SOURCE.rglob('*') if p.suffix in ('.avif', '.jpg')}
            self.assertEqual(len(images), 52, 'Keep the full pinned upstream collection')
            self.assertEqual({Path(item.findtext('filename')) for item in items}, images)
            self.assertEqual(len(items), len(images))
            for item in items:
                self.assertTrue(Path(item.findtext('filename')).is_file())
                self.assertTrue(item.findtext('name'))
                self.assertEqual(item.findtext('options'), 'zoom')
            self.assertTrue((SOURCE / 'ATTRIBUTIONS.txt').is_file())


if __name__ == '__main__':
    unittest.main()
