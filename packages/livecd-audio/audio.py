#!/data/data/com.termux/files/usr/bin/python
"""An opt-in native EasyEffects graph feeding Termux's existing PulseAudio."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import time


PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
STATE = Path.home() / ".local/state/livecd-audio"
RUNTIME = Path(os.environ.get("TMPDIR", str(PREFIX / "tmp"))) / "livecd-fx"
RECORD = STATE / "session.json"
AUDIO_ENV = ("PIPEWIRE_RUNTIME_DIR", "PIPEWIRE_REMOTE", "PULSE_SERVER")


def invoke(command, env, **kwargs):
    return subprocess.run(command, env=env, check=True, text=True, **kwargs)


def process_start(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def running():
    try:
        data = json.loads(RECORD.read_text())
        if process_start(data["pid"]) == data["start"]:
            return data
    except (OSError, ValueError, KeyError):
        pass
    return None


def wait_for(probe, children, description, attempts=100):
    for _ in range(attempts):
        if any(child.poll() is not None for child in children):
            raise RuntimeError(f"Audio process exited while waiting for {description}; see {STATE / 'session.log'}")
        try:
            result = probe()
            if result:
                return result
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {description}; see {STATE / 'session.log'}")


def sinks(env):
    return json.loads(invoke(["pactl", "--format=json", "list", "sinks"], env, capture_output=True).stdout)


def supervise(server, cookie):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "owner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A private bus keeps this native GTK application independent of a PRoot desktop.
        env = os.environ.copy()
        env.update(PIPEWIRE_RUNTIME_DIR=str(RUNTIME), XDG_RUNTIME_DIR=str(RUNTIME),
                   PIPEWIRE_REMOTE="pipewire-0", PULSE_SERVER=f"unix:{RUNTIME}/pulse/native",
                   GDK_BACKEND="x11", GSK_RENDERER="cairo", GSETTINGS_BACKEND="keyfile")
        env.setdefault("DISPLAY", ":0")
        env["LV2_PATH"] = os.pathsep.join(filter(None, [str(PREFIX / "lib/lv2"),
                                                     env.get("LV2_PATH"), str(Path.home() / ".lv2")]))
        RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
        RUNTIME.chmod(0o700)
        config = STATE / "pipewire"
        config.mkdir(exist_ok=True)
        for filename in ("pipewire.conf", "pipewire-pulse.conf"):
            shutil.copyfile(PREFIX / "share/pipewire" / filename, config / filename)
        dropins = config / "pipewire.conf.d"
        dropins.mkdir(exist_ok=True)
        (dropins / "90-termux-output.conf").write_text('''context.modules = [
  { name = libpipewire-module-pulse-tunnel
    args = {
      tunnel.mode = sink
      pulse.server.address = %s
      reconnect.interval.ms = 1000
      audio.channels = 2
      audio.position = [ FL FR ]
      stream.props = {
        node.name = "livecd_termux_output"
        node.description = "Termux PulseAudio output"
        media.class = "Audio/Sink"
        node.virtual = false
        priority.session = 1000
      }
    }
  }
]
''' % json.dumps(server))
        daemon_env = dict(env, PIPEWIRE_CONFIG_DIR=str(config), PULSE_SERVER=server)
        if cookie:
            daemon_env["PULSE_COOKIE"] = cookie
        children = []
        stopped = False

        def stop(*_):
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            children.append(subprocess.Popen(["pipewire"], env=daemon_env))
            wait_for(lambda: (RUNTIME / "pipewire-0").exists(), children, "PipeWire socket")
            # The policy profile manages streams/defaults without probing ALSA,
            # BlueZ or cameras; Android hardware is already behind PulseAudio.
            children.append(subprocess.Popen(["wireplumber", "--profile=policy"], env=env))
            children.append(subprocess.Popen(["pipewire-pulse"], env=dict(env, PIPEWIRE_CONFIG_DIR=str(config))))
            wait_for(lambda: any(s["name"] == "livecd_termux_output" for s in sinks(env)),
                     children, "PulseAudio tunnel")
            # EasyEffects handles app redirection, avoiding a feedback loop through
            # its own virtual sink. Only select the logical tunnel in this private graph.
            wait_for(lambda: invoke(["pactl", "set-default-sink", "livecd_termux_output"],
                                    env, capture_output=True), children, "WirePlumber default-node policy")
            invoke(["gsettings", "set", "com.github.wwmm.easyeffects.streamoutputs",
                    "use-default-output-device", "false"], env)
            invoke(["gsettings", "set", "com.github.wwmm.easyeffects.streamoutputs",
                    "output-device", "livecd_termux_output"], env)
            children.append(subprocess.Popen(["easyeffects", "--gapplication-service"], env=env))
            wait_for(lambda: any(s["name"] == "easyeffects_sink" for s in sinks(env)),
                     children, "EasyEffects sink")
            public_env = {key: env[key] for key in (
                "PIPEWIRE_RUNTIME_DIR", "XDG_RUNTIME_DIR", "PIPEWIRE_REMOTE", "PULSE_SERVER",
                "DBUS_SESSION_BUS_ADDRESS", "GDK_BACKEND", "GSK_RENDERER", "GSETTINGS_BACKEND",
                "DISPLAY", "LV2_PATH")}
            data = {"pid": os.getpid(), "start": process_start(os.getpid()),
                    "backend": server, "env": public_env}
            temporary = RECORD.with_suffix(".tmp")
            temporary.write_text(json.dumps(data))
            temporary.replace(RECORD)
            while not stopped:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("Audio process exited unexpectedly")
                time.sleep(0.2)
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
            for child in reversed(children):
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            RECORD.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Start the private native audio graph")
    start.add_argument("--pulse-server", help="Existing Termux PulseAudio address")
    start.add_argument("--pulse-cookie", help="Existing PulseAudio cookie, if required")
    for command in ("stop", "status", "env", "ui"):
        commands.add_parser(command)
    execute = commands.add_parser("exec", help="Launch a native application through EasyEffects")
    execute.add_argument("application", nargs=argparse.REMAINDER)
    preset = commands.add_parser("preset", help="Load a local output preset by name")
    preset.add_argument("name")
    internal = commands.add_parser("_run", help=argparse.SUPPRESS)
    internal.add_argument("server")
    internal.add_argument("cookie")
    args = parser.parse_args()
    if args.command == "_run":
        supervise(args.server, args.cookie)
        return
    current = running()
    if args.command == "start":
        if current:
            print("Native audio already running")
            return
        env = os.environ.copy()
        server = args.pulse_server or env.get("PULSE_SERVER")
        if not args.pulse_server and server == f"unix:{RUNTIME}/pulse/native":
            # A shell using `livecd-audio env` may restart the graph. Its old
            # frontend is not the downstream PulseAudio server to reconnect to.
            server = None
            env.pop("PULSE_SERVER", None)
        host_socket = PREFIX / "tmp/livecd-host/pulse.sock"
        if not server and host_socket.exists():
            server = f"unix:{host_socket}"
        if server:
            env["PULSE_SERVER"] = server
        cookie = args.pulse_cookie or env.get("PULSE_COOKIE", "")
        if cookie:
            env["PULSE_COOKIE"] = cookie
        # Probe only the logical PulseAudio endpoint, never Android hardware.
        info = json.loads(invoke(["pactl", "--format=json", "info"], env, capture_output=True).stdout)
        server = server or info["server_string"]
        if str(RUNTIME) in server:
            raise RuntimeError("Backend points to this graph; choose the Termux PulseAudio server")
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (STATE / "session.log").open("a") as log:
            process = subprocess.Popen(["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
                                        "_run", server, cookie], stdout=log, stderr=log,
                                       start_new_session=True, stdin=subprocess.DEVNULL)
        wait_for(running, [process], "native audio startup", attempts=350)
        print("Native EasyEffects ready. Open: livecd-audio ui")
    elif args.command == "status":
        print(json.dumps(current or {"running": False}, indent=2))
    elif args.command == "stop":
        if current:
            os.kill(current["pid"], signal.SIGTERM)
            for _ in range(100):
                if not running():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Audio shutdown timed out")
        print("Native audio stopped")
    else:
        if args.command == "ui" and not current:
            invoke([sys.executable, str(Path(__file__).resolve()), "start"], os.environ.copy())
            current = running()
        if not current:
            raise RuntimeError("Start native audio first: livecd-audio start")
        env = dict(os.environ, **current["env"])
        if args.command == "env":
            for key in AUDIO_ENV:
                print(f"export {key}={shlex.quote(current['env'][key])}")
        elif args.command == "exec":
            application = args.application
            if application[:1] == ["--"]:
                application = application[1:]
            if not application:
                parser.error("exec requires an application")
            # Normal applications retain their desktop bus, settings backend,
            # renderer and runtime directory. Only the audio endpoint changes.
            app_env = dict(os.environ, **{key: current["env"][key] for key in AUDIO_ENV})
            os.execvpe(application[0], application, app_env)
        elif args.command == "ui":
            invoke(["easyeffects"], env)
        elif args.command == "preset":
            invoke(["easyeffects", "--load-preset", args.name], env)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f"Native audio: {exc}")
