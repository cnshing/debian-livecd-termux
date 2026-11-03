#!/usr/bin/env python3
"""Conversion checks: headroom, both channels, shelf filters, and invalid input."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("autoeq", Path(__file__).resolve().parents[2] / "packages/livecd-audio/autoeq.py")
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


if __name__ == "__main__":
    unittest.main()
