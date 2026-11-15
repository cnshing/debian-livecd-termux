#!/usr/bin/env python3
"""Exercise CTS result handling without a GPU or a CTS build."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cts_runner', Path(__file__).with_name('run.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

FAKE_CTS = '''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
args = dict(arg[2:].split('=', 1) for arg in sys.argv[1:])
assert os.environ.get('PANVK_G77_NO_MERGE') == os.environ.get('FAKE_EXPECT_NO_MERGE', '0')
assert os.environ.get('PANVK_DEBUG', '') == os.environ.get('FAKE_EXPECT_DEBUG', '')
assert os.environ.get('PANVK_TRACE_CORE_FEATURES_ONLY', '') == os.environ.get('FAKE_EXPECT_CORE_ONLY', '')
assert os.environ.get('PANVK_KBASE_IMPORT_CLEAR', '') == os.environ.get('FAKE_EXPECT_IMPORT_CLEAR', '')
assert os.environ.get('PANVK_KBASE_IMPORT_SET', '') == os.environ.get('FAKE_EXPECT_IMPORT_SET', '')
if os.environ.get('FAKE_EXPECT_TRACE'):
    assert args['deqp-vk-library-path'].endswith('/trace.so')
    assert os.environ['PANVK_TRACE_LOADER'].endswith('/lib/libvulkan.so')
    assert Path(os.environ['PANVK_TRACE_SPIRV_DIR']).is_dir()
else:
    assert 'PANVK_TRACE_LOADER' not in os.environ
    assert 'PANVK_TRACE_SPIRV_DIR' not in os.environ
if args.get('deqp-runmode') == 'txt-caselist':
    Path(args['deqp-caselist-export-file']).write_text(
        'GROUP: dEQP-VK.compute\\nTEST: dEQP-VK.compute.a\\nTEST: dEQP-VK.compute.b\\n')
else:
    case = args['deqp-case']
    status = os.environ.get('FAKE_STATUS', 'Pass')
    Path(args['deqp-log-filename']).write_text(
        '<TestCaseResult CasePath="'+case+'"><Result StatusCode="'+status+'">result</Result></TestCaseResult>')
    sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
'''


class Results(unittest.TestCase):
    def test_parser_ignores_truncated_tail(self):
        text = '<TestCaseResult CasePath="a"><Result StatusCode="NotSupported">skip</Result></TestCaseResult>'
        self.assertEqual(runner.qpa_results(text + '<TestCaseResult'),
                         [{'case': 'a', 'status': 'NotSupported', 'detail': 'skip'}])

    def invoke(self, root, name, extra=(), env=None):
        cts = root / 'cts'
        cts.mkdir(exist_ok=True)
        exe = cts / 'deqp-vk'
        exe.write_text(FAKE_CTS)
        exe.chmod(0o755)
        driver = root / 'driver.so'
        driver.write_bytes(b'fake ICD')
        output = root / name
        argv = ['run.py', '--suite', 'vk', '--cts', str(cts), '--driver', str(driver),
                '--pattern', 'dEQP-VK.compute.*', '--out', str(output), *extra]
        with patch.object(sys, 'argv', argv), patch.dict(os.environ, {
                'PREFIX': str(root), 'TMPDIR': str(root), **(env or {})}), \
                patch.object(runner, 'memory_available', return_value=4_000_000):
            code = runner.main()
        return code, json.loads((output / 'results.json').read_text())

    def test_bounded_run_resumes_to_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, report = self.invoke(root, 'partial', ['--max-cases', '1'])
            self.assertEqual(code, 1)
            self.assertFalse(report['complete'])
            code, report = self.invoke(root, 'resumed', ['--resume-from', str(root / 'partial')])
            self.assertEqual(code, 0)
            self.assertEqual(report['counts'], {'Pass': 2})
            self.assertEqual(report['results'][0]['origin'], str(root / 'partial'))
            self.assertEqual(report['results'][1]['origin'], str(root / 'resumed'))

    def test_first_failure_stops_and_cannot_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, report = self.invoke(root, 'failure', env={'FAKE_STATUS': 'Fail'})
            self.assertEqual(code, 1)
            self.assertEqual(len(report['results']), 1)
            with self.assertRaisesRegex(RuntimeError, 'Prior run failed'):
                self.invoke(root, 'resumed', ['--resume-from', str(root / 'failure')])

    def test_nonzero_exit_overrides_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(Path(directory), 'exit', env={'FAKE_EXIT': '1'})
            self.assertEqual(code, 1)
            self.assertEqual(report['counts'], {'ProcessFailure': 1})

    def test_all_skipped_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(Path(directory), 'skip', env={'FAKE_STATUS': 'NotSupported'})
            self.assertEqual(code, 1)
            self.assertTrue(report['complete'])
            self.assertEqual(report['counts'], {'NotSupported': 2})

    def test_unmerged_mode_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(Path(directory), 'unmerged', ['--unmerged-compute'],
                                       env={'FAKE_EXPECT_NO_MERGE': '1'})
            self.assertEqual(code, 0)
            self.assertTrue(report['identity']['unmerged_compute'])

    def test_uncached_host_mode_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(Path(directory), 'uncached', ['--uncached-host-memory'],
                                       env={'FAKE_EXPECT_DEBUG': 'no_wb_mmap'})
            self.assertEqual(code, 0)
            self.assertTrue(report['identity']['uncached_host_memory'])

    def test_trace_mode_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / 'trace.so'
            trace.write_bytes(b'fake trace loader')
            code, report = self.invoke(root, 'traced', ['--trace-loader', str(trace)],
                                       env={'FAKE_EXPECT_TRACE': '1'})
            self.assertEqual(code, 0)
            self.assertEqual(report['identity']['trace_loader_sha256'], runner.digest(trace))

    def test_inherited_trace_mode_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(Path(directory), 'clean-trace',
                                       env={'PANVK_TRACE_LOADER': '/wrong/loader.so',
                                            'PANVK_TRACE_SPIRV_DIR': '/wrong/spirv',
                                            'PANVK_TRACE_CORE_FEATURES_ONLY': '1'})
            self.assertEqual(code, 0)
            self.assertNotIn('trace_loader_sha256', report['identity'])

    def test_core_filter_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace = root / 'trace.so'
            trace.write_bytes(b'fake trace loader')
            code, report = self.invoke(root, 'filtered', ['--trace-loader', str(trace), '--core-features-only'],
                                       env={'FAKE_EXPECT_TRACE': '1', 'FAKE_EXPECT_CORE_ONLY': '1'})
            self.assertEqual(code, 0)
            self.assertTrue(report['identity']['core_features_only'])
            self.assertTrue(report['diagnostic_only'])

    def test_import_coherence_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(Path(directory), 'local-import', ['--local-coherent-imports'],
                                       env={'FAKE_EXPECT_IMPORT_CLEAR': '0x400', 'FAKE_EXPECT_IMPORT_SET': '0x800'})
            self.assertEqual(code, 0)
            self.assertTrue(report['identity']['local_coherent_imports'])
            self.assertTrue(report['diagnostic_only'])

    def test_inherited_import_flags_are_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.invoke(Path(directory), 'clean-import',
                                       env={'PANVK_KBASE_IMPORT_CLEAR': '0x400', 'PANVK_KBASE_IMPORT_SET': '0x800'})
            self.assertEqual(code, 0)
            self.assertFalse(report['identity']['local_coherent_imports'])


if __name__ == '__main__':
    unittest.main()
