#!/data/data/com.termux/files/usr/bin/python
"""Expose Android-managed Bluetooth headphones and microphone to PulseAudio apps."""

import argparse
import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time


PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
DEX = PREFIX / "share/livecd-mic/audio-route.dex"
MIC = Path(__file__).with_name("mic.py")
if not MIC.is_file():
    MIC = PREFIX / "bin/livecd-mic"
INPUT = "livecd_bluetooth_input"
OUTPUT = "livecd_bluetooth_output"
SILENCE = "livecd_no_microphone"
CONTROL = PREFIX / "tmp/livecd-mic-bluetooth.sock"
PLAYER = PREFIX / "libexec/livecd-mic/sco-output"


class RouteError(RuntimeError):
    pass


class Bridge:
    """An authenticated local connection; EOF asks the helper to release its route."""

    def __init__(self):
        self.connection = None
        self.process = None
        self.log = tempfile.TemporaryFile()
        self.buffer = b""

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException:
            self.close()
            raise

    def start(self):
        rish = Path(os.environ.get("LIVECD_MIC_RISH",
                    str(Path.home() / ".local/lib/shizuku/rish")))
        if not rish.is_file():
            raise RouteError("Export Shizuku's rish into ~/.local/lib/shizuku, or set LIVECD_MIC_RISH.")
        if not DEX.is_file():
            raise RouteError("The packaged audio-route.dex is missing; rebuild/install livecd-mic.")
        dex = DEX.read_bytes()
        token = secrets.token_hex(32)
        # SELinux denies shell -> app Unix sockets on the tested phone. Use an
        # ephemeral loopback listener authenticated by a fresh, one-use token.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            script = f"""set -eu
umask 077
route_dir=$(mktemp -d /data/local/tmp/livecd-mic.XXXXXXXX)
trap 'rm -f "$route_dir/route.dex"; rmdir "$route_dir"' EXIT
base64 -d > "$route_dir/route.dex" <<'LIVECD_AUDIO_DEX'
{base64.b64encode(dex).decode()}
LIVECD_AUDIO_DEX
test "$(sha256sum "$route_dir/route.dex" | cut -d ' ' -f 1)" = {hashlib.sha256(dex).hexdigest()} || {{ echo 'Audio helper checksum mismatch' >&2; exit 1; }}
chmod 400 "$route_dir/route.dex"
CLASSPATH="$route_dir/route.dex" app_process / org.livecd.mic.AudioRoute {port} {token}
"""
            env = dict(os.environ, RISH_APPLICATION_ID="com.termux", RISH_PRESERVE_ENV="0")
            # rish variants can lose bytes when two readers compete for stdin.
            # Embed this small, public DEX in the command, then use only the socket.
            self.process = subprocess.Popen(["/system/bin/sh", str(rish), "-c", script],
                    stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, env=env)
            deadline = time.monotonic() + 15
            while True:
                listener.settimeout(max(0.01, deadline - time.monotonic()))
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    self.log.seek(0)
                    detail = self.log.read(2000).decode(errors="replace").strip()
                    raise RouteError("Shizuku audio helper did not connect within 15 seconds. " + detail)
                connection.settimeout(min(1, max(0.01, deadline - time.monotonic())))
                authentication = b""
                try:
                    while len(authentication) < 65:
                        chunk = connection.recv(65 - len(authentication))
                        if not chunk:
                            break
                        authentication += chunk
                except TimeoutError:
                    pass
                if hmac.compare_digest(authentication, (token + "\n").encode()):
                    self.connection = connection
                    return
                connection.close()
                if time.monotonic() >= deadline:
                    raise RouteError("No authenticated shell audio helper connected.")

    def send(self, command, **values):
        self.connection.sendall((json.dumps(dict(command=command, **values)) + "\n").encode())

    def receive(self, timeout=20):
        self.connection.settimeout(timeout)
        while b"\n" not in self.buffer:
            data = self.connection.recv(4096)
            if not data:
                raise RouteError("Android audio helper disconnected.")
            self.buffer += data
            if len(self.buffer) > 65536:
                raise RouteError("Android audio helper response is too large.")
        line, self.buffer = self.buffer.split(b"\n", 1)
        try:
            message = json.loads(line)
        except (ValueError, UnicodeDecodeError) as error:
            raise RouteError("Invalid Android audio helper response.") from error
        if not isinstance(message, dict) or message.get("event") not in ("devices", "ready", "lost", "error"):
            raise RouteError("Invalid Android audio helper event.")
        if message["event"] in ("error", "lost"):
            raise RouteError(str(message.get("error", "Android Bluetooth route failed.")))
        return message

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.process is not None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        self.log.close()

    def __exit__(self, *ignored):
        self.close()


def microphone(command):
    result = subprocess.run([sys.executable, "-I", str(MIC), command],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RouteError(result.stderr.strip() or "livecd-mic failed.")
    return json.loads(result.stdout)


def pulse(*arguments):
    result = subprocess.run(["pactl", *arguments], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RouteError(result.stderr.strip() or "PulseAudio request failed.")
    return result.stdout.strip()


class PulseDevices:
    """Owned PulseAudio endpoints backed by Android input and a native voice player."""

    def __init__(self, name, make_default=False):
        self.name = name
        self.make_default = make_default
        self.modules = []
        self.player = None
        self.directory = None
        self.log = tempfile.TemporaryFile()
        self.defaults = {}

    def __enter__(self):
        try:
            self.start()
            return self
        except BaseException:
            self.close()
            raise

    def load(self, *arguments):
        index = pulse("load-module", *arguments)
        if not index.isdecimal():
            raise RouteError("PulseAudio did not return a module ID.")
        self.modules.append(index)

    def start(self):
        self.defaults = {kind: pulse(f"get-default-{kind}") for kind in ("source", "sink")}
        for kind, name in (("sources", INPUT), ("sinks", OUTPUT)):
            if any(line.split("\t")[1] == name for line in pulse("list", "short", kind).splitlines()):
                raise RouteError("Bluetooth PulseAudio devices already exist; stop their controller first.")
        modules = pulse("list", "short", "modules")
        if "module-suspend-on-idle\t" not in modules:
            self.load("module-suspend-on-idle", "timeout=1")
        self.directory = tempfile.TemporaryDirectory(prefix="livecd-bt-", dir=PREFIX / "tmp")
        fifo = Path(self.directory.name) / "output.pcm"
        os.mkfifo(fifo, 0o600)
        self.player = subprocess.Popen([str(PLAYER), str(fifo)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=self.log, text=True)
        if not select.select([self.player.stdout], [], [], 5)[0]:
            raise RouteError("Native Bluetooth voice player did not start within five seconds.")
        line = self.player.stdout.readline()
        if not line:
            self.log.seek(0)
            raise RouteError("Native Bluetooth voice player failed: " + self.log.read(2000).decode(errors="replace"))
        if json.loads(line).get("ready") is not True:
            raise RouteError("Native Bluetooth voice player did not confirm readiness.")
        # Proplist quoting is passed directly to pactl, never interpreted by a shell.
        name = self.name.replace("\n", " ").replace("\r", " ")
        def properties(label):
            value = ("device.description=" + json.dumps(name + label, ensure_ascii=False)
                    + " device.icon_name=audio-headset device.class=sound device.bus=virtual")
            # pa_modargs_get_proplist parses the raw, still-escaped argument.
            # Use different outer quotes so the property's double quotes survive.
            return "'" + value.replace("'", "\\'") + "'"
        self.load("module-pipe-sink", f"sink_name={OUTPUT}", f"file={fifo}",
                "format=s16le", "rate=16000", "channels=1", "channel_map=mono",
                "sink_properties=" + properties(" Headphones"))
        self.load("module-sles-source", f"source_name={INPUT}",
                "format=s16le", "rate=48000", "channels=1", "latency=20",
                "source_properties=" + properties(" Microphone"))
        # Publishing endpoints must not switch unrelated applications unless requested.
        for kind, name in (("source", INPUT), ("sink", OUTPUT)):
            pulse(f"set-default-{kind}", name if self.make_default else self.defaults[kind])

    def close(self):
        for kind, name in (("source", INPUT), ("sink", OUTPUT)):
            if kind not in self.defaults:
                continue
            try:
                if pulse(f"get-default-{kind}") == name:
                    existing = {line.split("\t")[1] for line in pulse("list", "short", kind + "s").splitlines()}
                    target = self.defaults[kind]
                    if kind == "source" and (target not in existing or target.endswith(".monitor")):
                        target = SILENCE
                    if target in existing:
                        pulse(f"set-default-{kind}", target)
            except (RouteError, subprocess.SubprocessError, OSError) as error:
                print(f"Bluetooth default restore: {error}", file=sys.stderr)
        for index in reversed(self.modules):
            try:
                pulse("unload-module", index)
            except (RouteError, subprocess.SubprocessError, OSError) as error:
                print(f"Bluetooth device cleanup: {error}", file=sys.stderr)
        if self.player is not None:
            try:
                self.player.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.player.terminate()
                try:
                    self.player.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.player.kill()
                    self.player.wait()
            if self.player.stdout is not None:
                self.player.stdout.close()
        if self.directory is not None:
            self.directory.cleanup()
        self.log.close()

    def __exit__(self, *ignored):
        self.close()


class ControlServer:
    def __init__(self):
        self.socket = None
        self.state = {"active": False, "starting": True, "controller_pid": os.getpid()}

    def __enter__(self):
        # The caller holds the session lock, so any existing socket is stale.
        CONTROL.unlink(missing_ok=True)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(CONTROL))
        os.chmod(CONTROL, 0o600)
        self.socket.listen(4)
        return self

    def handle(self):
        with self.socket.accept()[0] as connection:
            connection.settimeout(1)
            try:
                request = json.loads(connection.recv(4096))
                stop = request.get("command") == "off"
                if request.get("command") == "defaults" and self.state.get("active"):
                    pulse("set-default-source", INPUT)
                    pulse("set-default-sink", OUTPUT)
                    self.state["default"] = True
                connection.sendall((json.dumps(dict(self.state, stopping=stop)) + "\n").encode())
                return stop
            except RouteError as error:
                connection.sendall((json.dumps({"error": str(error)}) + "\n").encode())
                return False
            except (ValueError, OSError, AttributeError):
                return False

    def __exit__(self, *ignored):
        self.socket.close()
        CONTROL.unlink(missing_ok=True)


def control(command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        try:
            connection.connect(str(CONTROL))
        except (FileNotFoundError, ConnectionRefusedError):
            return {"active": False}
        connection.sendall(json.dumps({"command": command}).encode())
        data = b""
        while b"\n" not in data and len(data) < 65536:
            chunk = connection.recv(4096)
            if not chunk:
                raise RouteError("Bluetooth device controller disconnected.")
            data += chunk
        result = json.loads(data)
        if "error" in result:
            raise RouteError(str(result["error"]))
        return result


def enable_background(device_id, make_default):
    state = control("status")
    if state.get("active"):
        if device_id and state.get("selected_device", {}).get("id") != device_id:
            raise RouteError("A different headset is active; run livecd-mic-bluetooth off first.")
        return control("defaults") if make_default else state
    log_path = PREFIX / "tmp/livecd-mic-bluetooth.log"
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as log:
        arguments = [sys.executable, "-I", str(Path(__file__).resolve()), "_serve", "--device", str(device_id)]
        if make_default:
            arguments.append("--default")
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True)
    try:
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RouteError(log_path.read_text()[-2000:].strip() or "Bluetooth device controller failed.")
            try:
                state = control("status")
            except (TimeoutError, ConnectionResetError):
                # The foreground controller may still be establishing the route.
                continue
            if state.get("active"):
                return state
            time.sleep(0.1)
        raise RouteError("Bluetooth device controller did not become ready within 35 seconds.")
    except BaseException:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        raise


def disable_background():
    state = control("off")
    deadline = time.monotonic() + 20
    if state.get("stopping"):
        while CONTROL.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if CONTROL.exists():
            raise RouteError("Bluetooth device controller has not finished cleaning up.")
    # After SIGKILL a controller cannot run finally blocks. Its Android helper
    # sees EOF, but PulseAudio may retain the named endpoints. Explicit off can
    # remove these; closing the pipe writer also lets the native player exit.
    with session_lock():
        CONTROL.unlink(missing_ok=True)
        modules = []
        fifos = []
        for line in pulse("list", "short", "modules").splitlines():
            fields = line.split("\t")
            if len(fields) < 3:
                continue
            if ((fields[1] == "module-sles-source" and f"source_name={INPUT}" in fields[2].split())
                    or (fields[1] == "module-pipe-sink" and f"sink_name={OUTPUT}" in fields[2].split())):
                modules.append(fields[0])
                if fields[1] == "module-pipe-sink":
                    for argument in fields[2].split():
                        if argument.startswith("file="):
                            path = Path(argument[5:])
                            if path.parent.parent == PREFIX / "tmp" and path.parent.name.startswith("livecd-bt-"):
                                fifos.append(path)
        if modules and pulse("get-default-source") == INPUT:
            pulse("set-default-source", SILENCE)
        for index in reversed(modules):
            pulse("unload-module", index)
        for fifo in fifos:
            try:
                fifo.unlink(missing_ok=True)
                fifo.parent.rmdir()
            except OSError:
                pass
    return {"active": False}


@contextlib.contextmanager
def session_lock():
    with (PREFIX / "tmp/livecd-mic-bluetooth.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RouteError("A Bluetooth microphone session is already running.") from error
        yield


def call_session(bridge, device_id, application, make_default=True, server=None):
    state = microphone("status")
    if state["microphone"] != "off":
        raise RouteError("Run livecd-mic off before starting a Bluetooth session.")
    child = None
    try:
        bridge.send("enable", device_id=device_id)
        message = bridge.receive()
        if message["event"] != "ready":
            raise RouteError("Android did not confirm the requested Bluetooth route.")
        with PulseDevices(message.get("selected_device", {}).get("name", "Android Bluetooth"), make_default) as devices:
            message.update(active=True, starting=False, input=INPUT, output=OUTPUT,
                    default=make_default, controller_pid=os.getpid())
            if server is not None:
                server.state = message
            print(json.dumps(message), flush=True)
            print("Bluetooth audio devices are available; stop with Ctrl-C or livecd-mic-bluetooth off.", file=sys.stderr)
            if application:
                child = subprocess.Popen(application)
            watched = [bridge.connection, devices.player.stdout]
            if server is not None:
                watched.append(server.socket)
            while child is None or child.poll() is None:
                if bridge.buffer:
                    bridge.receive()
                readable = select.select(watched, [], [], 0.25 if child else None)[0]
                if bridge.connection in readable:
                    bridge.receive()
                if devices.player.stdout in readable:
                    raise RouteError("Native Bluetooth voice output stopped.")
                if server is not None and server.socket in readable and server.handle():
                    return 0
            return child.returncode
    finally:
        # Stop capture before releasing Android's route, which may fall back to the phone.
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="list Android Bluetooth call devices without changing routing")
    commands.add_parser("status", help="show the published Linux audio devices")
    commands.add_parser("off", help="remove the Linux audio devices and release the Android audio route")
    on = commands.add_parser("on", help="publish headset output and microphone for Linux applications")
    on.add_argument("--device", type=int, default=0, metavar="ID")
    on.add_argument("--default", action="store_true", help="also make the headset the desktop default")
    call = commands.add_parser("call", help="hold a Bluetooth route and enable the microphone until Ctrl-C")
    call.add_argument("--device", type=int, default=0, metavar="ID", help="device ID from devices")
    call.add_argument("application", nargs=argparse.REMAINDER, help="optional -- COMMAND ARGS")
    if len(sys.argv) > 1 and sys.argv[1] == "_serve":
        internal = argparse.ArgumentParser()
        internal.add_argument("--device", type=int, default=0)
        internal.add_argument("--default", action="store_true")
        args = internal.parse_args(sys.argv[2:])
        args.command = "_serve"
    else:
        args = parser.parse_args()
    if getattr(args, "device", 0) < 0:
        parser.error("--device must be a positive device ID")
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    os.environ.setdefault("PULSE_SERVER", f"unix:{PREFIX}/tmp/livecd-host/pulse.sock")
    try:
        if args.command == "status":
            print(json.dumps(control("status")))
            return 0
        if args.command == "off":
            print(json.dumps(disable_background()))
            return 0
        if args.command == "on":
            print(json.dumps(enable_background(args.device, args.default)))
            return 0
        lock = session_lock() if args.command != "devices" else contextlib.nullcontext()
        server_context = ControlServer() if args.command != "devices" else contextlib.nullcontext()
        with lock, server_context as server, Bridge() as bridge:
            if args.command == "devices":
                bridge.send("devices")
                print(json.dumps(bridge.receive()))
                return 0
            application = args.application if args.command == "call" else []
            if application and application[0] == "--":
                application = application[1:]
            make_default = args.default if args.command == "_serve" else True
            return call_session(bridge, args.device, application, make_default, server)
    except KeyboardInterrupt:
        return 130
    except (RouteError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"livecd-mic-bluetooth: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
