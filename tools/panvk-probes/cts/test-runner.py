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


if __name__ == '__main__':
    unittest.main()
