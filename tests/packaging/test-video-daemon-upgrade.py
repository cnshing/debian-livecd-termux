#!/usr/bin/env python3
"""A shared Termux:VA daemon left running from before an upgrade is found; private ones are not."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import acceleration


class OutdatedDaemons(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.proc = self.tmp / 'proc'
        self.proc.mkdir()
        self.binary = self.tmp / 'bin/termux-va'
        self.binary.parent.mkdir()
        self.binary.write_text('')
        self.endpoint = self.tmp / 'tmp/termux-va/termux-va.sock'
        patch = mock.patch.object(acceleration, 'PREFIX', self.tmp)
        patch.start()
        self.addCleanup(patch.stop)

    def process(self, pid, exe, args=(), env=None):
        entry = self.proc / str(pid)
        entry.mkdir()
        os.symlink(exe, entry / 'exe')
        (entry / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in [exe, *args]) + b'\0')
        env = {'TERMUX_VA_SOCKET': str(self.endpoint)} if env is None else env
        (entry / 'environ').write_bytes(b''.join(f'{k}={v}\0'.encode() for k, v in env.items()))

    def found(self):
        return sorted(acceleration.outdated_daemons(self.endpoint, self.proc))

    def test_deleted_binary_on_the_session_socket_is_outdated(self):
        self.process(10, str(self.tmp / 'bin/termux-va.dpkg-tmp') + ' (deleted)')
        self.process(11, str(self.binary))
        self.assertEqual(self.found(), [10])

    def test_default_socket_from_tmpdir_counts(self):
        self.process(12, str(self.binary) + ' (deleted)', env={'TMPDIR': str(self.tmp / 'tmp')})
        self.assertEqual(self.found(), [12])

    def test_private_daemons_are_never_included(self):
        stage = str(self.tmp / 'stage/termux-va')
        self.process(20, stage, ['-v', '--sock', str(self.tmp / 'private.sock')])
        self.process(21, stage + ' (deleted)', env={'TERMUX_VA_SOCKET': str(self.tmp / 'other.sock')})
        self.process(22, '/system/bin/sh')
        self.assertEqual(self.found(), [])

    def test_another_binary_on_the_session_socket_is_outdated(self):
        self.process(30, str(self.tmp / 'old/termux-va'))
        self.assertEqual(self.found(), [30])

    def test_caller_owned_endpoint_is_left_alone(self):
        with mock.patch.object(acceleration, 'outdated_daemons') as outdated:
            self.assertEqual(acceleration.replace_outdated_daemons({'TERMUX_VA_SOCKET': '/x.sock'}), [])
            outdated.assert_not_called()


if __name__ == '__main__':
    unittest.main()
