#!/usr/bin/env python3
"""Does the phone's GSConnect answer an identity packet sent from this PC?

Sends a throwaway identity by broadcast or unicast, then waits for the phone itself to
dial back. Other KDE Connect peers on the LAN may also dial on a broadcast; they are
counted separately. It never pairs. Usage: test-discovery.py broadcast|unicast PHONE_IP [SECONDS]

Broadcast mode shows every GSConnect on the LAN a new unpaired device. One that already
holds three unpaired devices then switches off its own discovery and saves that setting.
"""
import json
import socket
import sys
import time
import uuid

mode, phone = sys.argv[1], sys.argv[2]
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 8
listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("", 0))
listener.listen(8)
identity = {"id": int(time.time() * 1000), "type": "kdeconnect.identity", "body": {
    "deviceId": uuid.uuid4().hex, "deviceName": f"discovery probe {mode}", "deviceType": "desktop",
    "protocolVersion": 8, "incomingCapabilities": [], "outgoingCapabilities": [],
    "tcpPort": listener.getsockname()[1]}}
sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sender.sendto((json.dumps(identity) + "\n").encode(),
              ("255.255.255.255" if mode == "broadcast" else phone, 1716))
start = time.time()
others = set()
while time.time() - start < seconds:
    listener.settimeout(max(seconds - (time.time() - start), 0.1))
    try:
        connection, address = listener.accept()
    except socket.timeout:
        break
    elapsed = time.time() - start
    connection.close()
    if address[0] == phone:
        print(f"PASS  {mode}: phone dialled back after {elapsed:.2f}s; {len(others)} other peer(s) before it")
        sys.exit(0)
    others.add(address[0])
print(f"FAIL  {mode}: phone did not dial back within {seconds:.0f}s; {len(others)} other peer(s) did")
sys.exit(1)
