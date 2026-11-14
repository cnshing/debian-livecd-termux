#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('audit-vulkan14.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class Audit(unittest.TestCase):
    def test_hex_limits(self):
        report = audit.audit('bufferImageGranularity = 0x00000040\n')
        check = next(c for c in report['checks'] if c['name'] == 'bufferImageGranularity')
        self.assertTrue(check['ok'])

    def test_ambiguous_devices_rejected(self):
        with self.assertRaisesRegex(ValueError, 'single-device'):
            audit.declarations('maxPushConstantsSize = 128\nmaxPushConstantsSize = 256\n')

    def test_missing_data_and_conditional_feature(self):
        report = audit.audit('protectedMemory = true\n')
        checks = {c['name']: c for c in report['checks']}
        self.assertFalse(checks['pipelineProtectedAccess']['ok'])
        self.assertFalse(checks['pointSizeRange']['ok'])
        self.assertFalse(report['declarations_ok'])
        self.assertFalse(report['conformance_proven'])

    def test_array_and_decimal_parsing(self):
        report = audit.audit('maxViewportDimensions: count = 2\n\t8192\n\t8192\n'
                             'pointSizeRange: count = 2\n\t0.125\n\t255.875\n'
                             'pointSizeGranularity = 0.125\n')
        checks = {c['name']: c for c in report['checks']}
        self.assertTrue(checks['maxViewportDimensions']['ok'])
        self.assertTrue(checks['pointSizeRange']['ok'])


if __name__ == '__main__':
    unittest.main()
