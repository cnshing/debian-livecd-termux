"""Check device selection without changing client libraries or microphone policy."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
from audio import server


class AudioBackend(unittest.TestCase):
    def test_default_preserves_android_output_and_safe_source(self):
        with tempfile.TemporaryDirectory() as directory:
            command, env, sink = server(directory, '/private/pulse.sock', {'PATH': '/bin'})
            self.assertEqual(sink, 'OpenSL_ES_sink')
            self.assertIn('--load=module-sles-sink sink_name=OpenSL_ES_sink', command)
            self.assertTrue(any('source_name=android_no_microphone' in arg for arg in command))
            self.assertFalse(any('module-sles-source' in arg for arg in command))
            self.assertEqual(env, {'PATH': '/bin'})

    def test_candidate_only_changes_server_search_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / 'candidate'
            for name in ('bin/pulseaudio', 'lib/pulseaudio/modules/module-aaudio-sink.so'):
                p = prefix / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            (root / 'audio.json').write_text(json.dumps({'backend': 'aaudio', 'server_prefix': str(prefix)}))
            inherited = {'LD_LIBRARY_PATH': '/original', 'PULSE_SERVER': 'unix:/old'}
            command, env, sink = server(root, '/private/new.sock', inherited)
            self.assertEqual(sink, 'AAudio_sink')
            self.assertEqual(command[0], str(prefix / 'bin/pulseaudio'))
            self.assertIn('--load=module-aaudio-sink sink_name=AAudio_sink', command)
            self.assertTrue(any('socket=/private/new.sock' in arg for arg in command))
            self.assertNotIn('PULSE_SERVER', env)
            self.assertTrue(env['LD_LIBRARY_PATH'].startswith(str(prefix / 'lib/pulseaudio')))
            self.assertEqual(inherited, {'LD_LIBRARY_PATH': '/original', 'PULSE_SERVER': 'unix:/old'})

    def test_invalid_selection_fails_before_launch(self):
        for settings in ([], {'backend': 'alsa'}, {'backend': 'aaudio', 'server_prefix': 'relative'},
                         {'backend': 'aaudio', 'server_prefix': '/missing/candidate'}):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / 'audio.json').write_text(json.dumps(settings))
                with self.assertRaises(ValueError):
                    server(directory, '/private/pulse.sock', {})


if __name__ == '__main__':
    unittest.main()
