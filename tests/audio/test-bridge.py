#!/usr/bin/env python3
"""Host checks for tunnel recovery without restarting the private audio graph."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

path = Path(__file__).resolve().parents[2] / 'packages/easyeffects/easyeffects-bridge.py'
spec = importlib.util.spec_from_file_location('bridge', path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class TunnelRecovery(unittest.TestCase):
    def setUp(self):
        self.env = {'PULSE_SERVER': 'unix:/private/pulse'}
        self.tunnel = bridge.PulseTunnel(self.env, 'unix:/backend/pulse', '/backend/cookie')
        self.sink = {'index': 2, 'name': 'bluetooth'}
        self.available = True
        self.present = False
        self.now = 0
        for patch in (
                mock.patch.object(bridge, 'invoke', side_effect=self.info),
                mock.patch.object(bridge, 'sinks', side_effect=self.sinks),
                mock.patch.object(bridge.subprocess, 'Popen', side_effect=self.process),
                mock.patch.object(bridge.time, 'monotonic', side_effect=lambda: self.now),
                contextlib.redirect_stdout(io.StringIO())):
            patch.__enter__()
            self.addCleanup(patch.__exit__, None, None, None)
        self.processes = []

    def info(self, *args, **kwargs):
        if not self.available:
            raise subprocess.CalledProcessError(1, 'pactl')
        return mock.Mock(stdout=json.dumps({'default_sink_name': self.sink['name']}))

    def sinks(self, env):
        if env is self.env:
            return [{'name': bridge.OUTPUT}] if self.present else []
        return [self.sink] if self.available else []

    def process(self, command, **kwargs):
        process = mock.Mock()
        process.poll.return_value = None
        self.processes.append((process, command, kwargs))
        return process

    def ready(self):
        self.assertFalse(self.tunnel.refresh())
        self.present = True
        self.assertTrue(self.tunnel.refresh())

    def test_a_healthy_tunnel_keeps_its_process(self):
        self.ready()
        for _ in range(10):
            self.now += 1
            self.assertTrue(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 1)
        _, command, kwargs = self.processes[0]
        args = json.loads(command[-1])
        self.assertEqual(args['target.object'], 'bluetooth')
        self.assertEqual(args['reconnect.interval.ms'], 0)
        self.assertEqual(kwargs['env']['PULSE_SERVER'], 'unix:/backend/pulse')
        self.assertEqual(kwargs['env']['PULSE_COOKIE'], '/backend/cookie')
        self.assertEqual(self.env['PULSE_SERVER'], 'unix:/private/pulse')

    def test_removed_then_recreated_sink_recovers(self):
        self.ready()
        old = self.processes[0][0]
        self.available = False
        self.assertFalse(self.tunnel.refresh())
        old.terminate.assert_called_once()
        self.assertIsNone(self.tunnel.process)
        self.available = True
        self.sink['index'] = 3
        self.assertFalse(self.tunnel.refresh())
        self.assertTrue(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 2)

    def test_same_name_recreated_between_polls_also_recovers(self):
        self.ready()
        self.sink['index'] = 4
        self.assertFalse(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 2)

    def test_default_route_change_retargets_the_tunnel(self):
        self.ready()
        self.sink = {'index': 0, 'name': 'speaker'}
        self.assertFalse(self.tunnel.refresh())
        self.assertEqual(json.loads(self.processes[-1][1][-1])['target.object'], 'speaker')

    def test_missing_node_or_dead_helper_reloads_the_module(self):
        self.ready()
        self.present = False
        self.assertFalse(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 2)
        self.processes[-1][0].poll.return_value = 1
        self.assertFalse(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 3)

    def test_startup_gets_a_grace_period_then_retries(self):
        self.assertFalse(self.tunnel.refresh())
        self.now = 4
        self.assertFalse(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 1)
        self.now = 5
        self.assertFalse(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 2)

    def test_a_transient_frontend_query_failure_keeps_the_tunnel(self):
        self.ready()
        with mock.patch.object(bridge, 'sinks', side_effect=[
                [self.sink], subprocess.TimeoutExpired('pactl', 5)]):
            self.assertFalse(self.tunnel.refresh())
        self.assertTrue(self.tunnel.refresh())
        self.assertEqual(len(self.processes), 1)

    def test_stuck_helper_is_killed_and_reaped_on_close(self):
        self.ready()
        process = self.processes[0][0]
        process.wait.side_effect = [subprocess.TimeoutExpired('pw-cli', 5), 0]
        self.tunnel.close()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertIsNone(self.tunnel.process)


if __name__ == '__main__':
    unittest.main()
