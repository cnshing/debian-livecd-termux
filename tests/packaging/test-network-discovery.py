#!/usr/bin/env python3
"""Check the isolated build scope and discovery's private-session boundary."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recipes = load('network_recipes', 'tools/recipes.py')
discovery = load('network_discovery', 'packages/avahi/discovery.py')


class NetworkDiscovery(unittest.TestCase):
    def test_requested_set_has_one_job_and_only_its_local_dependencies(self):
        jobs = recipes.plan(['gvfs'])['include']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['packages'], 'avahi gvfs')
        self.assertFalse(jobs[0]['exact'])

    def test_discovery_requires_the_desktop_system_bus(self):
        for env in ({}, {'LIVECD_NATIVE_SESSION': 'test'}):
            with patch.dict(os.environ, env, clear=True), patch.object(discovery.os, 'execvp') as execute:
                with self.assertRaises(SystemExit):
                    discovery.main()
                execute.assert_not_called()

    def test_discovery_uses_the_session_runtime_and_preserves_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {'LIVECD_NATIVE_SESSION': 'session-test', 'XDG_RUNTIME_DIR': directory,
                   'DBUS_SYSTEM_BUS_ADDRESS': 'unix:path=' + directory + '/system-bus'}
            with patch.dict(os.environ, env, clear=True), patch.object(discovery.os, 'execvp') as execute:
                discovery.main()
                self.assertEqual(os.environ['LIVECD_NATIVE_SESSION'], 'session-test')
                self.assertEqual(os.environ['DBUS_SYSTEM_BUS_ADDRESS'], env['DBUS_SYSTEM_BUS_ADDRESS'])
                command, args = execute.call_args.args
                self.assertEqual(command, 'avahi-daemon')
                self.assertIn('--file=' + directory + '/avahi.conf', args)
                self.assertNotIn('--daemonize', args)
            config = Path(directory) / 'avahi.conf'
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertIn('enable-dbus=yes', config.read_text())
            self.assertIn('disable-publishing=yes', config.read_text())


if __name__ == '__main__':
    unittest.main()
