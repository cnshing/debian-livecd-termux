#!/usr/bin/env python3
"""Host checks for stopped status, stale sockets, and live owner responses."""
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import desktop


class DesktopStatus(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        patch = mock.patch.multiple(desktop, STATE=root / 'state', ENDPOINT=root / 'control.sock')
        patch.start()
        self.addCleanup(patch.stop)

    def command(self, action='status'):
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', ['desktop.py', action]), contextlib.redirect_stdout(output):
            code = desktop.main()
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def test_never_started_or_cleanly_stopped(self):
        self.assertEqual(self.command(), {'ok': False, 'running': False})

    def test_stale_session_and_unlistened_socket(self):
        desktop.STATE.mkdir()
        (desktop.STATE / 'session.json').write_text('{"pid": 1}')
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(str(desktop.ENDPOINT))
        self.assertEqual(self.command(), {'ok': False, 'running': False})
        # A query does not remove another owner's state.
        self.assertTrue(desktop.ENDPOINT.exists())
        self.assertTrue((desktop.STATE / 'session.json').exists())

    def test_stop_is_idempotent(self):
        self.assertEqual(self.command('stop'), {'ok': True, 'running': False})

    def test_running_owner_response_is_preserved(self):
        response = {'ok': True, 'backend': 'native', 'owner': 123, 'renderer': 'software'}
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(desktop.ENDPOINT))
            server.listen(1)
            server.settimeout(5)

            def answer():
                connection, _ = server.accept()
                with connection:
                    connection.makefile('rb').readline()
                    connection.sendall((json.dumps(response) + '\n').encode())

            thread = threading.Thread(target=answer, daemon=True)
            thread.start()
            self.assertEqual(self.command(), response)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_other_errors_still_fail(self):
        for error in (PermissionError('denied'), TimeoutError('timeout'), RuntimeError('owner error')):
            with self.subTest(error=error), mock.patch.object(desktop, 'request', side_effect=error):
                with self.assertRaises(type(error)):
                    self.command()


if __name__ == '__main__':
    unittest.main()
