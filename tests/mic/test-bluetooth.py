#!/usr/bin/env python3
"""Host checks for route failure, session ownership and capture cleanup."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("bluetooth",
        Path(__file__).resolve().parents[2] / "packages/livecd-mic/bluetooth.py")
bluetooth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bluetooth)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.bridge = mock.Mock(buffer=b"")
        self.bridge.receive.return_value = {"event": "ready"}
        self.events = []

    def microphone(self, command):
        self.events.append(command)
        return {"microphone": "off"}

    def run_session(self, application=()):
        @contextlib.contextmanager
        def devices(*args):
            self.events.append("publish")
            try:
                yield mock.Mock(player=mock.Mock(stdout="player-stdout"))
            finally:
                self.events.append("unpublish")
        with mock.patch.object(bluetooth, "microphone", side_effect=self.microphone), \
                mock.patch.object(bluetooth, "PulseDevices", side_effect=devices), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return bluetooth.call_session(self.bridge, 49, application)

    def test_rejected_route_never_opens_microphone(self):
        self.bridge.receive.side_effect = bluetooth.RouteError("No matching Bluetooth device")
        with self.assertRaises(bluetooth.RouteError):
            self.run_session()
        self.assertEqual(self.events, ["status"])

    def test_does_not_take_over_an_existing_microphone(self):
        with mock.patch.object(bluetooth, "microphone", return_value={"microphone": "idle"}):
            with self.assertRaisesRegex(bluetooth.RouteError, "livecd-mic off"):
                bluetooth.call_session(self.bridge, 49, ())
        self.bridge.send.assert_not_called()

    def test_child_exit_closes_capture_before_route_is_released(self):
        child = mock.Mock(returncode=7)
        child.poll.return_value = 7
        with mock.patch.object(bluetooth.subprocess, "Popen", return_value=child):
            self.assertEqual(self.run_session(["example-call"]), 7)
        self.assertEqual(self.events, ["status", "publish", "unpublish"])
        child.terminate.assert_not_called()

    def test_route_loss_closes_capture_and_stops_owned_application(self):
        child = mock.Mock()
        child.poll.return_value = None
        self.bridge.receive.side_effect = [{"event": "ready"}, bluetooth.RouteError("route lost")]
        with mock.patch.object(bluetooth.subprocess, "Popen", return_value=child), \
                mock.patch.object(bluetooth.select, "select", return_value=([self.bridge.connection], [], [])):
            with self.assertRaisesRegex(bluetooth.RouteError, "route lost"):
                self.run_session(["example-call"])
        self.assertEqual(self.events, ["status", "publish", "unpublish"])
        child.terminate.assert_called_once()

    def test_interrupt_closes_capture(self):
        with mock.patch.object(bluetooth.select, "select", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_session()
        self.assertEqual(self.events, ["status", "publish", "unpublish"])

    def test_one_controller_owns_the_session(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            (prefix / "tmp").mkdir()
            with mock.patch.object(bluetooth, "PREFIX", prefix), bluetooth.session_lock():
                with self.assertRaisesRegex(bluetooth.RouteError, "already running"):
                    with bluetooth.session_lock():
                        self.fail("second controller acquired session lock")
            with mock.patch.object(bluetooth, "PREFIX", prefix), bluetooth.session_lock():
                pass


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = socket.socketpair()
        self.bridge = bluetooth.Bridge()
        self.bridge.connection = self.left

    def tearDown(self):
        self.bridge.close()
        self.right.close()

    def test_buffered_route_loss_is_not_mistaken_for_ready(self):
        self.right.sendall(b'{"event":"ready"}\n{"event":"lost","error":"headset disconnected"}\n')
        self.assertEqual(self.bridge.receive()["event"], "ready")
        with self.assertRaisesRegex(bluetooth.RouteError, "headset disconnected"):
            self.bridge.receive()

    def test_eof_is_failure(self):
        self.right.close()
        with self.assertRaisesRegex(bluetooth.RouteError, "disconnected"):
            self.bridge.receive()

    def test_invalid_payloads_are_rejected(self):
        for payload in (b'[]\n', b'not-json\n', b'{"event":"unknown"}\n', b'\xff\n'):
            with self.subTest(payload=payload):
                self.right.sendall(payload)
                with self.assertRaises(bluetooth.RouteError):
                    self.bridge.receive()


class PulseDeviceTests(unittest.TestCase):
    def setUp(self):
        self.sources = {bluetooth.SILENCE, "other_input"}
        self.sinks = {"android_output", "other_output"}
        self.defaults = {"source": bluetooth.SILENCE, "sink": "android_output"}
        self.original_defaults = dict(self.defaults)
        self.modules = {}
        self.next_index = 10
        self.fail_source = False
        self.player = mock.Mock(stdout=io.StringIO('{"ready":true}\n'))

    def pulse(self, *arguments):
        command = arguments[0]
        if command.startswith("get-default-"):
            return self.defaults[command.removeprefix("get-default-")]
        if command.startswith("set-default-"):
            self.defaults[command.removeprefix("set-default-")] = arguments[1]
            return ""
        if arguments[:3] == ("list", "short", "modules"):
            # This shared module belongs to another user of the server.
            return "3\tmodule-suspend-on-idle\ttimeout=5\n"
        if arguments[:2] == ("list", "short"):
            names = self.sources if arguments[2] == "sources" else self.sinks
            return "\n".join(f"{i}\t{name}\tdriver" for i, name in enumerate(sorted(names)))
        if command == "load-module":
            if self.fail_source and arguments[1] == "module-sles-source":
                raise bluetooth.RouteError("source load failed")
            self.next_index += 1
            index = str(self.next_index)
            name = next(arg.split("=", 1)[1] for arg in arguments if arg.startswith(("sink_name=", "source_name=")))
            names = self.sinks if arguments[1] == "module-pipe-sink" else self.sources
            names.add(name)
            self.modules[index] = (names, name)
            return index
        if command == "unload-module":
            names, name = self.modules.pop(arguments[1])
            names.remove(name)
            return ""
        raise AssertionError(arguments)

    @contextlib.contextmanager
    def environment(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            (prefix / "tmp").mkdir()
            with mock.patch.object(bluetooth, "PREFIX", prefix), \
                    mock.patch.object(bluetooth, "pulse", side_effect=self.pulse), \
                    mock.patch.object(bluetooth.subprocess, "Popen", return_value=self.player), \
                    mock.patch.object(bluetooth.select, "select", return_value=([self.player.stdout], [], [])):
                yield

    def test_named_devices_preserve_defaults_and_remove_only_owned_modules(self):
        with self.environment(), bluetooth.PulseDevices('Headset "A"'):
            self.assertIn(bluetooth.INPUT, self.sources)
            self.assertIn(bluetooth.OUTPUT, self.sinks)
            self.assertEqual(self.defaults, self.original_defaults)
        self.assertNotIn(bluetooth.INPUT, self.sources)
        self.assertNotIn(bluetooth.OUTPUT, self.sinks)
        self.assertFalse(self.modules)

    def test_explicit_defaults_are_restored_on_exit(self):
        with self.environment(), bluetooth.PulseDevices("Headset", make_default=True):
            self.assertEqual(self.defaults, {"source": bluetooth.INPUT, "sink": bluetooth.OUTPUT})
        self.assertEqual(self.defaults, self.original_defaults)

    def test_user_changes_to_defaults_survive_cleanup(self):
        with self.environment(), bluetooth.PulseDevices("Headset", make_default=True):
            self.defaults.update(source="other_input", sink="other_output")
        self.assertEqual(self.defaults, {"source": "other_input", "sink": "other_output"})

    def test_partial_start_removes_output_when_microphone_fails(self):
        self.fail_source = True
        with self.environment(), self.assertRaisesRegex(bluetooth.RouteError, "source load failed"):
            with bluetooth.PulseDevices("Headset"):
                self.fail("source unexpectedly started")
        self.assertNotIn(bluetooth.OUTPUT, self.sinks)
        self.assertEqual(self.defaults, self.original_defaults)
        self.assertFalse(self.modules)
        self.player.wait.assert_called()


if __name__ == "__main__":
    unittest.main()
