#!/usr/bin/env python3
"""Protocol-level checks of a running livecd-gsconnect, from a PC on the same LAN.

Acts as a disposable KDE Connect peer with a throwaway certificate, so the phone's
behaviour can be asserted packet by packet without any desktop on the PC side. It pairs
only with itself and unpairs at the end. Temporarily changes the phone's X clipboard.

Usage: test-protocol.py PHONE_IP [SSH_HOST]
"""
import json
import shlex
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

phone, ssh_host = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "termux"
device_id = uuid.uuid4().hex
results = []


def check(name, passed, detail=""):
    results.append(passed)
    print(f"{'PASS' if passed else 'FAIL'}  {name}{f'  [{detail}]' if detail else ''}", flush=True)


def on_phone(command, check_exit=True):
    wrapped = f"livecd-gsconnect exec -- sh -c {shlex.quote(command)}"
    return subprocess.run(["ssh", ssh_host, wrapped], capture_output=True, text=True, timeout=60,
                          check=check_exit).stdout.strip()


def dconf_path(suffix):
    return f"/org/gnome/shell/extensions/gsconnect/device/{device_id}/{suffix}"


def certificate(directory, label):
    cert, key = directory / f"{label}.pem", directory / f"{label}.key"
    subprocess.run(["openssl", "req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-keyout", key, "-new", "-x509", "-nodes", "-days", "2",
                    "-subj", f"/O=livecd/OU=test/CN={device_id}", "-out", cert],
                   check=True, capture_output=True)
    return cert, key


def identity(port):
    return {"id": int(time.time() * 1000), "type": "kdeconnect.identity", "body": {
        "deviceId": device_id, "deviceName": "protocol test", "deviceType": "desktop",
        "protocolVersion": 8, "tcpPort": port,
        "incomingCapabilities": ["kdeconnect.battery", "kdeconnect.clipboard", "kdeconnect.runcommand",
                                 "kdeconnect.ping"],
        "outgoingCapabilities": ["kdeconnect.battery.request", "kdeconnect.clipboard",
                                 "kdeconnect.runcommand.request", "kdeconnect.ping",
                                 "kdeconnect.findmyphone.request", "kdeconnect.mousepad.request"]}}


class Channel:
    def __init__(self, cert, key):
        listener = socket.socket()
        listener.bind(("", 0))
        listener.listen(1)
        listener.settimeout(15)
        port = listener.getsockname()[1]
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.sendto((json.dumps(identity(port)) + "\n").encode(), (phone, 1716))
        raw, _ = listener.accept()
        listener.close()
        raw.settimeout(10)
        self.plain_identity = json.loads(raw.makefile().readline())
        # The side that dialled is the TLS server; KDE Connect inverts the usual roles.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.load_cert_chain(cert, key)
        self.tls = context.wrap_socket(raw)
        self.buffer = b""
        self.send(identity(port))
        self.peer = self.receive(lambda p: p["type"] == "kdeconnect.identity")

    def send(self, packet):
        self.tls.sendall((json.dumps(packet) + "\n").encode())

    def packet(self, kind, **body):
        self.send({"id": int(time.time() * 1000), "type": kind, "body": body})

    def receive(self, wanted, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if line.strip():
                    packet = json.loads(line)
                    if wanted(packet):
                        return packet
            self.tls.settimeout(max(deadline - time.time(), 0.1))
            try:
                chunk = self.tls.recv(65536)
            except (socket.timeout, ssl.SSLWantReadError):
                continue
            if not chunk:
                raise ConnectionError("closed by phone")
            self.buffer += chunk
        return None

    def close(self):
        self.tls.close()


CLIPBOARD_READ = """imports.gi.versions.Gtk='3.0';const {Gtk,Gdk}=imports.gi;Gtk.init(null);
print(Gtk.Clipboard.get_default(Gdk.Display.get_default()).wait_for_text());"""
CLIPBOARD_WRITE = """imports.gi.versions.Gtk='3.0';const {Gtk,Gdk,GLib}=imports.gi;Gtk.init(null);
const c=Gtk.Clipboard.get_default(Gdk.Display.get_default());c.set_text(ARGV[0],-1);c.store();
GLib.timeout_add(0,4000,()=>{Gtk.main_quit();return false;});Gtk.main();"""


POINTER_READ = """imports.gi.versions.Gtk='3.0';const {Gtk,Gdk}=imports.gi;Gtk.init(null);
const [,x,y]=Gdk.Display.get_default().get_default_seat().get_pointer().get_position();print(`${x},${y}`);"""


def pointer_read():
    return on_phone(f"cjs -c {shlex.quote(POINTER_READ)} 2>/dev/null")


def clipboard_read():
    return on_phone(f"cjs -c {shlex.quote(CLIPBOARD_READ)} 2>/dev/null")


def clipboard_write(text):
    return on_phone(f"cjs -c {shlex.quote(CLIPBOARD_WRITE)} {shlex.quote(text)} 2>/dev/null")


def main():
    log = "$HOME/.local/state/livecd-gsconnect/session.log"
    criticals_before = int(on_phone(f"grep -ac CRITICAL {log} || true"))
    marker = f"$TMPDIR/livecd-gsconnect-probe-{device_id}"
    command_list = ("{'probe': <{'name': <'probe'>, 'command': <'echo ran > " + marker + "'>}>}")
    on_phone(f"dconf write {dconf_path('plugin/runcommand/command-list')} {shlex.quote(command_list)}")
    with tempfile.TemporaryDirectory() as temporary:
        cert, key = certificate(Path(temporary), "peer")
        channel = Channel(cert, key)
        check("TLS 1.2+ handshake with the native OpenSSL backend", channel.tls.version() in ("TLSv1.2", "TLSv1.3"),
              f"{channel.tls.version()}, {channel.tls.cipher()[0]}")
        check("Phone speaks protocol 8 after TLS", channel.peer["body"]["protocolVersion"] == 8,
              channel.peer["body"]["deviceName"])

        channel.packet("kdeconnect.runcommand.request", key="probe")
        time.sleep(2)
        ran = on_phone(f"test -e {marker} && echo yes || echo no")
        check("Unpaired peer cannot run a command", ran == "no")
        channel.close()
        time.sleep(1)

        channel = Channel(cert, key)
        channel.packet("kdeconnect.pair", pair=True, timestamp=int(time.time()))
        time.sleep(2)
        on_phone(f"$PREFIX/bin/livecd-gsconnect pair {device_id}")
        reply = channel.receive(lambda p: p["type"] == "kdeconnect.pair")
        check("Pairing accepted through the CLI", bool(reply and reply["body"].get("pair")))
        listed = on_phone(f"$PREFIX/bin/livecd-gsconnect devices | grep {device_id}")
        check("Phone records the peer as paired", listed.endswith("true\ttrue"), listed)

        channel.packet("kdeconnect.battery.request", request=True)
        on_phone(f"dconf write {dconf_path('plugin/battery/send-statistics')} true")
        battery = channel.receive(lambda p: p["type"] == "kdeconnect.battery")
        sysfs = on_phone("cat /sys/class/power_supply/battery/capacity")
        check("Battery level comes from Android sysfs",
              bool(battery) and str(battery["body"]["currentCharge"]) == sysfs,
              f"{battery and battery['body']} sysfs={sysfs}")

        # GSConnect forgets a disconnected unpaired device, including the earlier setting.
        on_phone(f"dconf write {dconf_path('plugin/runcommand/command-list')} {shlex.quote(command_list)}")
        time.sleep(1)
        channel.packet("kdeconnect.runcommand.request", key="probe")
        time.sleep(2)
        ran = on_phone(f"cat {marker} 2>/dev/null || true")
        check("Paired peer runs a configured command with Termux's sh", ran == "ran", ran)
        on_phone(f"rm -f {marker}")
        channel.packet("kdeconnect.runcommand.request", key="not-configured")

        channel.packet("kdeconnect.ping", message="protocol test ping")
        time.sleep(1)

        previous = clipboard_read()
        on_phone(f"dconf write {dconf_path('plugin/clipboard/receive-content')} true; "
                 f"dconf write {dconf_path('plugin/clipboard/send-content')} true")
        time.sleep(1)
        inbound = f"to-phone {uuid.uuid4().hex}"
        channel.packet("kdeconnect.clipboard", content=inbound)
        time.sleep(2)
        seen = clipboard_read()
        check("Peer clipboard reaches the phone's X clipboard", seen == inbound, seen)
        outbound = f"from-phone {uuid.uuid4().hex}"
        clipboard_write(outbound)
        sent = channel.receive(lambda p: p["type"] == "kdeconnect.clipboard"
                               and p["body"].get("content") == outbound, 8)
        check("Phone's X clipboard reaches the peer", bool(sent))
        if previous and previous != "null":
            clipboard_write(previous)

        # Pointer only: synthetic keys would land in whichever window has focus.
        before = pointer_read()
        channel.packet("kdeconnect.mousepad.request", dx=-37, dy=-23)
        time.sleep(3)
        after = pointer_read()
        check("Remote pointer motion moves the phone's X pointer", before != after, f"{before} -> {after}")

        channel.packet("kdeconnect.pair", pair=False)
        time.sleep(1)
        listed = on_phone(f"$PREFIX/bin/livecd-gsconnect devices | grep {device_id} || echo gone")
        check("Peer's unpair request is honoured", listed == "gone" or listed.endswith("false"), listed)
        channel.close()

        # Pair again, then present a different certificate under the same device ID.
        time.sleep(1)
        channel = Channel(cert, key)
        channel.packet("kdeconnect.pair", pair=True, timestamp=int(time.time()))
        time.sleep(2)
        on_phone(f"$PREFIX/bin/livecd-gsconnect pair {device_id}")
        channel.receive(lambda p: p["type"] == "kdeconnect.pair")
        channel.close()
        time.sleep(1)
        forged_cert, forged_key = certificate(Path(temporary), "forged")
        rejected = False
        try:
            forged = Channel(forged_cert, forged_key)
            forged.packet("kdeconnect.runcommand.request", key="probe")
            time.sleep(2)
            forged.close()
        except (OSError, ConnectionError, ValueError):
            rejected = True
        ran = on_phone(f"test -e {marker} && echo yes || echo no")
        check("Wrong certificate for a paired ID cannot run commands", ran == "no",
              "connection refused" if rejected else "connected but ignored")
        listed = on_phone(f"$PREFIX/bin/livecd-gsconnect devices | grep {device_id} || echo gone")
        check("Wrong certificate drops the pairing, as upstream intends", not listed.endswith("true\ttrue"), listed)

    criticals = int(on_phone(f"grep -ac CRITICAL {log} || true")) - criticals_before
    check("No new GLib/CJS criticals in the daemon log", criticals == 0, f"{criticals} new")
    on_phone(f"$PREFIX/bin/livecd-gsconnect unpair {device_id}; dconf reset -f {dconf_path('')}", check_exit=False)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
