#!/usr/bin/env python3
"""The 10-bit session ids must agree between the daemon (termux-va) and the VA bridge
(android-vaapi, also built into android-vaapi-glibc): both patch their own byte-identical copy of
tva_protocol.h. Also checks the gates that keep 10-bit off unless the daemon's probe proved P010."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def header_hunks(patch):
    """The added and removed lines of a patch's tva_protocol.h section."""
    text = (ROOT / patch).read_text()
    section = re.search(r'^diff --git a/\S*tva_protocol\.h.*?(?=^diff --git |\Z)', text, re.M | re.S)
    assert section, patch
    return [line for line in section.group(0).splitlines()
            if line[:1] in '+-' and not line.startswith(('+++', '---'))]


class TenBitProtocol(unittest.TestCase):
    def test_header_changes_match(self):
        self.assertEqual(header_hunks('packages/termux-va/0002-ten-bit-decode.patch'),
                         header_hunks('packages/android-vaapi/0108-ten-bit-decode.patch'))

    def test_ids(self):
        lines = '\n'.join(header_hunks('packages/termux-va/0002-ten-bit-decode.patch'))
        for name, value in (('CODEC_HEVC_MAIN10', 11), ('CODEC_VP9_PROFILE2', 12), ('CODEC_HEVC_MAIN10_ENC', 13)):
            self.assertRegex(lines, rf'{name}\s*=\s*{value},')

    def test_gated_by_probe(self):
        daemon = (ROOT / 'packages/termux-va/0002-ten-bit-decode.patch').read_text()
        bridge = (ROOT / 'packages/android-vaapi/0108-ten-bit-decode.patch').read_text()
        # Only Qualcomm components are probed; a missing list (older daemon) offers nothing.
        self.assertIn('!strncmp(name, "OMX.qcom.", 9) || !strncmp(name, "c2.qti.", 7)', daemon)
        self.assertIn('.tenbit', daemon)
        self.assertIn('return;   /* an older daemon: no 10-bit sessions */', bridge)
        self.assertIn('tva_ten_bit_available("video/hevc")', bridge)
        self.assertIn('TERMUX_VA_DISABLE_10BIT', bridge)

    def test_encode_gated_by_probe(self):
        daemon = (ROOT / 'packages/termux-va/0011-ten-bit-encode.patch').read_text()
        bridge = (ROOT / 'packages/android-vaapi/0111-ten-bit-encode.patch').read_text()
        # The daemon lists the encoder only when one P010 picture became a Main10 stream.
        self.assertIn('ok = (b[6] & 31) == 2;   /* general_profile_idc */', daemon)
        self.assertIn('"video/hevc-enc %s', daemon)
        self.assertIn('tva_ten_bit_available("video/hevc-enc")', bridge)
        self.assertIn('return CODEC_HEVC_MAIN10_ENC;', bridge)


if __name__ == '__main__':
    unittest.main()
