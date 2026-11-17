#!/usr/bin/env python3
"""Desktop start replaces a shared termux-va whose binary an upgrade replaced, and nothing else."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/native'))
import acceleration


class UpgradedDaemon(unittest.TestCase):
    def proc(self, root, pid, exe, fds):
        entry = Path(root) / str(pid)
        (entry / 'fd').mkdir(parents=True)
        os.symlink(exe, entry / 'exe')
        for number, target in enumerate(fds):
            os.symlink(target, entry / 'fd' / str(number))

    def test_only_the_replaced_lock_holder(self):
        with tempfile.TemporaryDirectory() as root:
            endpoint = '/tmp/termux-va/termux-va.sock'
            prefix = '/data/data/com.termux/files/usr/bin/termux-va'
            self.proc(root, 10, prefix, [endpoint + '.lock'])                 # current binary
            self.proc(root, 11, prefix + ' (deleted)', ['/home/p/a/s.lock'])  # private daemon
            self.proc(root, 12, '/bin/sh (deleted)', [endpoint + '.lock'])    # not termux-va
            self.assertIsNone(acceleration.upgraded_daemon(endpoint, root))
            self.proc(root, 13, prefix + ' (deleted)', [endpoint + '.lock'])  # upgraded shared one
            self.assertEqual(acceleration.upgraded_daemon(endpoint, root), 13)


if __name__ == '__main__':
    unittest.main()
