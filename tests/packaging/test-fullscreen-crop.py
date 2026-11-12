#!/usr/bin/env python3
"""Check independent X11 geometry used by browser compositor pixel captures."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/browsers'))
spec = importlib.util.spec_from_file_location('fullscreen', ROOT / 'tests/browsers/test-fullscreen.py')
fullscreen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fullscreen)


class CompositorCrop(unittest.TestCase):
    def test_asymmetric_client_shadow_uses_actual_bottom_extent(self):
        # Observed x1s window: content begins at X=32, Y=119. Inferring bottom
        # from half the outer/inner width instead placed the crop at Y=122.
        box = dict(screenX=10, screenY=13, outerHeight=760, innerHeight=629,
                   dpr=1, rootX=32, rootY=122)
        fullscreen.compositor_origin(box, (22, 22, 19, 25))
        self.assertEqual((box['rootX'], box['rootY']), (32, 119))

    def test_device_pixels_are_converted_to_css_coordinates(self):
        box = dict(screenX=10, screenY=13, outerHeight=380, innerHeight=314.5,
                   dpr=2)
        fullscreen.compositor_origin(box, (22, 22, 19, 25))
        self.assertEqual((box['rootX'], box['rootY']), (21, 66))

    def test_no_client_shadow_preserves_browser_geometry(self):
        box = dict(rootX=0, rootY=0)
        fullscreen.compositor_origin(box, None)
        self.assertEqual(box, dict(rootX=0, rootY=0))


if __name__ == '__main__':
    unittest.main()
