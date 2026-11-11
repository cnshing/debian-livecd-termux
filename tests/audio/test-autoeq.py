#!/usr/bin/env python3
"""Conversion checks: headroom, both channels, shelf filters, and invalid input."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("autoeq", Path(__file__).resolve().parents[2] / "packages/easyeffects/easyeffects-autoeq.py")
autoeq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autoeq)

EXPORT = """Preamp: -6.3 dB
Filter 1: ON LSC Fc 105 Hz Gain 6.5 dB Q 0.70
Filter 2: ON PK Fc 125 Hz Gain -2.7 dB Q 0.55
Filter 3: OFF PK Fc 400 Hz Gain 9 dB Q 1
Filter 4: ON HSC Fc 10000 Hz Gain -3.1 dB Q 0.70
"""


class ImportTests(unittest.TestCase):
    def test_headroom_and_both_channels(self):
        preset = autoeq.convert(EXPORT)["output"]
        self.assertEqual(preset["plugins_order"], ["equalizer#0"])
        eq = preset["equalizer#0"]
        self.assertEqual(eq["input-gain"], -6.3)
        self.assertEqual(eq["output-gain"], 0)
        self.assertEqual(eq["num-bands"], 3)
        self.assertEqual(eq["left"], eq["right"])
        self.assertEqual([b["type"] for b in eq["left"].values()], ["Lo-shelf", "Bell", "Hi-shelf"])
        self.assertEqual(eq["left"]["band1"]["q"], 0.55)
        self.assertEqual(eq["left"]["band0"]["mode"], "APO (DR)")

    def test_rejects_lossy_or_invalid_imports(self):
        for invalid in (EXPORT.replace("Preamp: -6.3 dB\n", ""),
                        EXPORT + "GraphicEQ: 20 0; 1000 3\n",
                        EXPORT.replace("105 Hz", "9 Hz"),
                        EXPORT.replace("6.5 dB", "37 dB"),
                        EXPORT.replace("0.70", "101"),
                        EXPORT + "Preamp: -3 dB\n",
                        "Preamp: 0 dB\n" + "\n".join(
                            f"Filter {n}: ON PK Fc 100 Hz Gain 1 dB Q 1" for n in range(33))):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                autoeq.convert(invalid)


class CataloguePackagingTests(unittest.TestCase):
    def test_build_bundles_catalogue_and_refreshes_without_stale_presets(self):
        recipe = Path(__file__).resolve().parents[2] / "packages/easyeffects"
        # Exercise the real install stage without compiling EasyEffects or using the network.
        script = '''set -euo pipefail
source "$TERMUX_PKG_BUILDER_DIR/build.sh"
curl() { cp "$OPRA_FIXTURE" "${@: -1}"; }
termux_step_post_make_install
source "$TERMUX_PKG_BUILDER_DIR/easyeffects-autoeq.subpackage.sh"
for path in $TERMUX_SUBPKG_INCLUDE; do test -e "$TERMUX_PREFIX/$path"; done
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix = root / "prefix"
            build = root / "build"
            build.mkdir()
            fixture = root / "database.jsonl"
            records = [
                {"type": "vendor", "id": "vendor", "data": {"name": "Vendor"}},
                {"type": "product", "id": "product", "data": {
                    "vendor_id": "vendor", "name": "Headphones"}},
                {"type": "eq", "data": {"product_id": "product", "author": "AutoEQ",
                    "details": "Harman", "parameters": {"gain_db": -6.3, "bands": [
                        {"type": "peak_dip", "frequency": 125, "gain_db": -2.7, "q": 0.55}]}}},
            ]
            env = dict(os.environ, TERMUX_PKG_BUILDER_DIR=str(recipe),
                       TERMUX_PKG_BUILDDIR=str(build), TERMUX_PREFIX=str(prefix),
                       OPRA_FIXTURE=str(fixture))
            destination = prefix / "share/easyeffects/output/OPRA"
            destination.mkdir(parents=True)
            (destination / "stale.json").touch()
            for model in ("Headphones", "New headphones"):
                records[1]["data"]["name"] = model
                fixture.write_text("".join(json.dumps(record) + "\n" for record in records))
                subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True)
                self.assertEqual([path.name for path in destination.iterdir()],
                                 [f"Vendor {model} (AutoEQ).json"])
                preset = json.loads(next(destination.iterdir()).read_text())["output"]["equalizer#0"]
                self.assertEqual(preset["input-gain"], -6.3)
                self.assertEqual(preset["left"], preset["right"])
                self.assertEqual(preset["left"]["band0"]["mode"], "APO (DR)")
                self.assertFalse(list(build.iterdir()))
            failed = subprocess.run(["bash", "-c", script.replace(
                'cp "$OPRA_FIXTURE" "${@: -1}"', 'return 22')], env=env, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(list(build.iterdir()))
            self.assertTrue((destination / "Vendor New headphones (AutoEQ).json").exists())


if __name__ == "__main__":
    unittest.main()
