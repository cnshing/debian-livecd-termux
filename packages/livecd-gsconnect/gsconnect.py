#!/data/data/com.termux/files/usr/bin/python
"""Native GSConnect on a private D-Bus session, independent of any PRoot desktop."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
APP_ID = "org.gnome.Shell.Extensions.GSConnect"
EXTENSION = PREFIX / "share/gnome-shell/extensions/gsconnect@andyholmes.github.io"
DAEMON = EXTENSION / "service/daemon.js"
STATE = Path.home() / ".local/state/livecd-gsconnect"
RUNTIME = Path(os.environ.get("TMPDIR", str(PREFIX / "tmp"))) / "livecd-gsconnect"
RECORD = STATE / "session.json"
FORBIDDEN_NAME = "\"',;:.!?()[]<>"  # Device.validateName rejects peers using these.
PUBLIC_ENV = ("DBUS_SESSION_BUS_ADDRESS", "DBUS_SYSTEM_BUS_ADDRESS", "DISPLAY", "GDK_BACKEND",
              "GIO_USE_NETWORK_MONITOR", "GNOME_SETUP_DISPLAY", "XDG_RUNTIME_DIR")


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


def valid_name(name):
    return bool(name.strip()) and len(name) <= 32 and not set(name) & set(FORBIDDEN_NAME)


def default_name():
    model = subprocess.run(["getprop", "ro.product.model"], capture_output=True, text=True).stdout.strip()
    name = re.sub("[" + re.escape(FORBIDDEN_NAME) + "]", "", f"{model} Termux").strip()
    return name[:32] if valid_name(name[:32]) else "Termux"


def gsettings(env, *arguments):
    return subprocess.run(["gsettings", *arguments], env=env, check=True, text=True,
                          capture_output=True).stdout.strip()


def daemon_ready(env):
    # The name is claimed before GTK opens the display; actions exist only afterwards.
    # Check the owner first, because asking an unowned name would activate a new daemon.
    reply = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                            "--object-path", "/org/freedesktop/DBus",
                            "--method", "org.freedesktop.DBus.NameHasOwner", APP_ID],
                           env=env, capture_output=True, text=True).stdout
    if "true" not in reply:
        return False
    actions = subprocess.run(["gdbus", "call", "--session", "--dest", APP_ID,
                              "--object-path", "/" + APP_ID.replace(".", "/"),
                              "--method", "org.gtk.Actions.List"],
                             env=env, capture_output=True, text=True).stdout
    return "'refresh'" in actions


def session_env():
    """Environment for the bus itself: activated helpers such as dconf inherit it."""
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.update(
        GDK_BACKEND="x11",
        XDG_RUNTIME_DIR=str(RUNTIME),
        # GLib's default monitor expects systemd and reports no network, which
        # silently stops discovery. Netlink works and follows Wi-Fi changes.
        GIO_USE_NETWORK_MONITOR="netlink",
        # GSConnect only reads this to prefer X11 clipboard access over wl-paste.
        GNOME_SETUP_DISPLAY=env["DISPLAY"],
    )
    return env


def supervise(name):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "owner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = os.environ.copy()
        # Android has no system bus. Logind lookups must fail, not abort startup.
        env["DBUS_SYSTEM_BUS_ADDRESS"] = env["DBUS_SESSION_BUS_ADDRESS"]
        current = gsettings(env, "get", APP_ID, "name").strip("'")
        if name:
            gsettings(env, "set", APP_ID, "name", name)
        elif current in ("", "localhost"):
            gsettings(env, "set", APP_ID, "name", default_name())
        stopped = False

        def stop(*_):
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        daemon = subprocess.Popen([str(DAEMON)], env=env)
        try:
            for _ in range(300):
                if stopped:
                    return
                if daemon.poll() is not None:
                    raise RuntimeError(f"Daemon exited during startup; is an X server on "
                                       f"{env['DISPLAY']}? See {STATE / 'session.log'}")
                if daemon_ready(env):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Timed out waiting for the GSConnect daemon")
            data = {"pid": os.getpid(), "start": process_start(os.getpid()),
                    "env": {key: env[key] for key in PUBLIC_ENV}}
            temporary = RECORD.with_suffix(".tmp")
            temporary.write_text(json.dumps(data))
            temporary.replace(RECORD)
            while not stopped:
                if daemon.poll() is not None:
                    raise RuntimeError(f"Daemon exited unexpectedly: {daemon.returncode}")
                time.sleep(0.5)
        finally:
            if daemon.poll() is None:
                daemon.terminate()
                try:
                    daemon.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait()
            RECORD.unlink(missing_ok=True)


def start_session(name):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    with (STATE / "session.log").open("a") as log:
        process = subprocess.Popen(["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
                                    "_run", name], stdout=log, stderr=log, env=session_env(),
                                   start_new_session=True, stdin=subprocess.DEVNULL)
    for _ in range(350):
        if running():
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)
    else:
        # Without a record, stop could not find it: never leave it listening.
        os.killpg(process.pid, signal.SIGTERM)
    raise RuntimeError(f"Startup failed; is an X server on {session_env()['DISPLAY']}? "
                       f"See {STATE / 'session.log'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Start the daemon; it listens on the LAN until stopped")
    start.add_argument("--name", help="Device name shown to peers (kept for later starts)")
    commands.add_parser("stop")
    commands.add_parser("status", help="Report the session and known devices")
    commands.add_parser("devices", help="Print ID, name, connected, paired")
    for command, description in (("pair", "Request pairing, or accept a pending request"),
                                 ("unpair", "Unpair a device, or reject a pending request")):
        commands.add_parser(command, help=description).add_argument("device")
    connect = commands.add_parser("connect", help="Contact a peer by address, without broadcast discovery")
    connect.add_argument("address", metavar="HOST[:PORT]")
    commands.add_parser("ui", help="Open the GSConnect preferences window, starting the daemon if needed")
    execute = commands.add_parser("exec", help="Run a command on the private bus, e.g. the daemon's CLI")
    execute.add_argument("arguments", nargs=argparse.REMAINDER)
    commands.add_parser("_run", help=argparse.SUPPRESS).add_argument("name")
    args = parser.parse_args()
    if args.command == "_run":
        supervise(args.name)
        return
    current = running()
    if args.command == "start":
        if args.name and not valid_name(args.name):
            parser.error(f"--name must be 1-32 characters without any of {FORBIDDEN_NAME}")
        if current:
            print("GSConnect already running")
            return
        start_session(args.name or "")
        print("GSConnect ready and listening on the LAN (TCP/UDP 1716). Pair: livecd-gsconnect ui")
        return
    if args.command == "ui" and not current:
        # A menu entry has no terminal to show "start it first" in.
        start_session("")
        current = running()
    if args.command == "stop":
        if current:
            os.kill(current["pid"], signal.SIGTERM)
            for _ in range(100):
                if not running():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Shutdown timed out")
        print("GSConnect stopped")
        return
    if args.command == "status" and not current:
        print("GSConnect not running")
        return
    if not current:
        raise RuntimeError("Start it first: livecd-gsconnect start")
    env = dict(os.environ, **current["env"])
    cli = [str(DAEMON)]
    if args.command in ("status", "devices"):
        if args.command == "status":
            print(f"GSConnect running, owner PID {current['pid']}; "
                  f"name {gsettings(env, 'get', APP_ID, 'name')}")
        subprocess.run([*cli, "--list-all"], env=env, check=True)
    elif args.command in ("pair", "unpair"):
        subprocess.run([*cli, "--device", args.device, f"--{args.command}"], env=env, check=True)
    elif args.command == "connect":
        host, _, port = args.address.partition(":")
        target = f"lan://{host}:{port or 1716}"
        subprocess.run(["gapplication", "action", APP_ID, "connect", repr(target)], env=env, check=True)
    elif args.command == "ui":
        subprocess.run([str(EXTENSION / "gsconnect-preferences")], env=env, check=True)
    elif args.command == "exec":
        arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        if not arguments:
            parser.error("exec requires a command")
        os.execvpe(arguments[0], arguments, env)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f"GSConnect: {exc}")
