#!/usr/bin/env python3
"""The Android UPower backend against a fake battery, on a private bus.

Run in native Termux: python3 tests/upower/test-backend.py [UPOWERD]

This script plays the Shizuku helper, so no phone-wide state changes and the real
history file is untouched. Takes about two minutes because it waits out poll intervals.
"""
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

upowerd = sys.argv[1] if len(sys.argv) > 1 else os.environ['PREFIX'] + '/libexec/upowerd'
SERVICE = 'org.freedesktop.UPower'
DEVICE = '/org/freedesktop/UPower/devices/battery_BAT0'
INTERFACE = SERVICE + '.Device'
POLL_WAIT = 36
failures = []


def check(name, passed, detail=''):
    print(('ok   ' if passed else 'FAIL ') + name + (f': {detail}' if detail != '' else ''), flush=True)
    if not passed:
        failures.append(name)


def near(actual, expected, margin=0.01):
    return abs(actual - expected) <= margin


class Rig:
    def __init__(self, root):
        self.root = root
        self.battery = root / 'battery'
        self.battery.mkdir()
        self.client = root / 'client'
        rish = root / 'rish'
        # The real client stays running after starting the helper, so this does too.
        rish.write_text(f'echo "$$ $2" > {self.client}.new; mv {self.client}.new {self.client}; exec sleep 600\n')
        address = 'unix:path=' + str(root / 'bus')
        config = root / 'bus.conf'
        config.write_text(f'<busconfig><type>session</type><auth>EXTERNAL</auth><listen>{address}</listen>'
                          f'<policy context="default"><allow user="{os.getuid()}"/><allow own="*"/>'
                          '<allow send_destination="*"/><allow receive_sender="*"/></policy></busconfig>')
        self.bus_process = subprocess.Popen(['dbus-daemon', '--nofork', '--nopidfile', '--config-file=' + str(config)])
        while not (root / 'bus').exists():
            time.sleep(0.05)
        self.env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=address, UPOWER_HISTORY_DIR=str(root),
                        UP_ANDROID_BATTERY_DIR=str(self.battery), MC_RISH=str(rish))
        self.bus = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
        self.daemon = None

    def write(self, status='Discharging', capacity=57):
        # Samsung's shape: current_now in mA, which must lose to the file in uA.
        (self.battery / 'uevent').write_text(
            f'POWER_SUPPLY_NAME=battery\nPOWER_SUPPLY_STATUS={status}\nPOWER_SUPPLY_TECHNOLOGY=Li-ion\n'
            f'POWER_SUPPLY_VOLTAGE_NOW=4000000\nPOWER_SUPPLY_CURRENT_NOW=-500\nPOWER_SUPPLY_CAPACITY={capacity}\n'
            'POWER_SUPPLY_CHARGE_FULL=4300000\nPOWER_SUPPLY_CHARGE_FULL_DESIGN=4300000\n'
            'POWER_SUPPLY_CHARGE_NOW=0\nPOWER_SUPPLY_CHARGE_COUNTER=1670000\nPOWER_SUPPLY_TEMP=300\n')
        (self.battery / 'batt_current_ua_now').write_text('-500000\n')
        (self.battery / 'battery_cycle').write_text('1022\n')

    def start(self, **env):
        self.daemon = subprocess.Popen([upowerd], env=dict(self.env, **env))
        for _ in range(100):
            try:
                self.properties()
                return
            except GLib.Error:
                time.sleep(0.1)
        raise SystemExit('upowerd did not come up')

    def stop(self):
        self.daemon.terminate()
        self.daemon.wait(timeout=5)

    def call(self, interface, method, arguments=None, path=DEVICE):
        return self.bus.call_sync(SERVICE, path, interface, method, arguments, None, Gio.DBusCallFlags.NONE, 5000, None)

    def properties(self):
        return self.call('org.freedesktop.DBus.Properties', 'GetAll', GLib.Variant('(s)', (INTERFACE,))).unpack()[0]

    def refresh(self):
        self.call(INTERFACE, 'Refresh')

    def helper_address(self):
        for _ in range(100):
            if self.client.exists():
                pid, command = self.client.read_text().split(' ', 1)
                token = re.search(r'echo (\S+);', command).group(1)
                port = int(re.search(r'nc 127\.0\.0\.1 (\d+)', command).group(1))
                return int(pid), token, port
            time.sleep(0.1)
        raise SystemExit('The daemon did not start the fake rish')

    def wakeups(self):
        total = 0
        for task in Path(f'/proc/{self.daemon.pid}/task').iterdir():
            total += sum(int(line.split()[1]) for line in (task / 'status').read_text().splitlines()
                         if line.startswith('voluntary_ctxt_switches'))
        return total


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def main(rig):
    rig.write()
    rig.start()
    values = rig.properties()
    check('percentage', values['Percentage'] == 57, values['Percentage'])
    check('discharging', values['State'] == 2, values['State'])
    check('voltage', near(values['Voltage'], 4.0), values['Voltage'])
    check('temperature', near(values['Temperature'], 30.0), values['Temperature'])
    check('design energy is real, not 100 Wh', near(values['EnergyFullDesign'], 16.555), values['EnergyFullDesign'])
    check('current energy', near(values['Energy'], 16.555 * 0.57), values['Energy'])
    check('rate uses uA, not the mA current_now', near(values['EnergyRate'], 2.0), values['EnergyRate'])
    check('time to empty', near(values['TimeToEmpty'], 3600 * 16.555 * 0.57 / 2, 2), values['TimeToEmpty'])
    check('cycle count from the vendor file', values['ChargeCycles'] == 1022, values['ChargeCycles'])
    check('unmeasured health is not reported as 100%', values['Capacity'] == 0, values['Capacity'])
    check('native path has no sysfs twin', values['NativePath'] == '/android/BAT0', values['NativePath'])
    check('history available', values['HasHistory'])

    rig.write(capacity=56)
    rig.refresh()
    check('Refresh() reads on demand', rig.properties()['Percentage'] == 56)

    pid, token, port = rig.helper_address()
    stranger = socket.create_connection(('127.0.0.1', port))
    stranger.sendall(b'not the token\n')
    stranger.settimeout(5)
    check('a wrong token is disconnected', stranger.recv(16) == b'')
    stranger.close()
    time.sleep(0.5)
    rig.write(capacity=55)
    time.sleep(POLL_WAIT)
    check('polls while no helper is connected', rig.properties()['Percentage'] == 55)

    helper = socket.create_connection(('127.0.0.1', port))
    helper.sendall(token.encode() + b'\n')
    time.sleep(1)
    check('the Shizuku client VM is stopped once the helper is up', not alive(pid))
    helper.sendall(b'  mSavedBatteryAsoc: 85\n')
    time.sleep(1)
    values = rig.properties()
    check('health from Android', near(values['Capacity'], 85), values['Capacity'])
    check('full energy follows health', near(values['EnergyFull'], 16.555 * 0.85), values['EnergyFull'])

    rig.write(capacity=54)
    before = rig.wakeups()
    time.sleep(POLL_WAIT)
    wakeups = rig.wakeups() - before
    check('no polling while the helper is connected', rig.properties()['Percentage'] == 55)
    check(f'daemon stays asleep for {POLL_WAIT} s', wakeups <= 2, wakeups)
    helper.sendall(b'01-01 00:00:00.000 I/battery_level( 1117): [54,4000,300]\n')
    time.sleep(1)
    check('a battery event wakes it at once', rig.properties()['Percentage'] == 54)

    rig.write('Full', 100)
    helper.sendall(b'I/battery_status( 1117): [5,2,1,2,Li-ion]\n')
    time.sleep(1)
    values = rig.properties()
    check('full', values['State'] == 4, values['State'])
    check('a full battery has no rate or time to empty', values['EnergyRate'] == 0 and values['TimeToEmpty'] == 0,
          (values['EnergyRate'], values['TimeToEmpty']))
    rig.write('Not charging', 80)
    rig.refresh()
    check('not charging is pending, not discharging', rig.properties()['State'] == 5)
    rig.write('Charging', 50)
    rig.refresh()
    values = rig.properties()
    check('charging', values['State'] == 1 and values['TimeToFull'] > 0, (values['State'], values['TimeToFull']))
    display = rig.call('org.freedesktop.DBus.Properties', 'GetAll', GLib.Variant('(s)', (INTERFACE,)),
                       '/org/freedesktop/UPower/devices/DisplayDevice').unpack()[0]
    check("Shell's display device", display['IsPresent'] and display['Percentage'] == 50 and display['State'] == 1)
    history = rig.call(INTERFACE, 'GetHistory', GLib.Variant('(suu)', ('charge', 3600, 100))).unpack()[0]
    check('history records samples', len(history) > 0, len(history))

    helper.close()
    time.sleep(1)
    rig.write('Charging', 49)
    time.sleep(POLL_WAIT)
    check('polling resumes when the helper is lost', rig.properties()['Percentage'] == 49)
    rig.stop()

    # A phone whose sysfs is closed to apps falls back to Android's public API.
    rig.start(UP_ANDROID_BATTERY_DIR=str(rig.root / 'missing'), MC_RISH=str(rig.root / 'missing'))
    api = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=20).stdout
    values = rig.properties()
    match = re.search(r'"percentage": *(\d+)', api)
    check('Termux:API fallback', match and values['Percentage'] == float(match.group(1)) and values['Voltage'] > 3,
          (values['Percentage'], values['Voltage']))
    check('no invented energy without a capacity', values['EnergyFullDesign'] == 0, values['EnergyFullDesign'])
    rig.stop()

    # Termux's own packages ask on the session bus, which must reach this same daemon.
    source = Path(__file__).resolve().parents[2] / 'packages/android-upower/org.freedesktop.UPower.service'
    services = rig.root / 'services'
    services.mkdir()
    (services / source.name).write_text(source.read_text().replace('@TERMUX_PREFIX@/libexec/upowerd', upowerd)
                                        .replace('@TERMUX_PREFIX@', os.environ['PREFIX']))
    address = 'unix:path=' + str(rig.root / 'session-bus')
    config = rig.root / 'session.conf'
    config.write_text(f'<busconfig><type>session</type><auth>EXTERNAL</auth><listen>{address}</listen>'
                      f'<servicedir>{services}</servicedir><policy context="default"><allow user="{os.getuid()}"/>'
                      '<allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy></busconfig>')
    session_bus = subprocess.Popen(['dbus-daemon', '--nofork', '--nopidfile', '--config-file=' + str(config)],
                                   env=dict(rig.env, MC_RISH=str(rig.root / 'missing')))
    while not (rig.root / 'session-bus').exists():
        time.sleep(0.05)
    rig.write('Charging', 48)
    session = Gio.DBusConnection.new_for_address_sync(
        address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
    reply = session.call_sync(SERVICE, DEVICE, 'org.freedesktop.DBus.Properties', 'Get',
                              GLib.Variant('(ss)', (INTERFACE, 'Percentage')), None, Gio.DBusCallFlags.NONE, 10000, None)
    check('the session bus starts this daemon on demand', reply.unpack()[0] == 48, reply.unpack()[0])
    pid = session.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                            'GetConnectionUnixProcessID', GLib.Variant('(s)', (SERVICE,)), None,
                            Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    check('it is this build', os.path.realpath(f'/proc/{pid}/exe') == os.path.realpath(upowerd))
    session_bus.kill()
    session_bus.wait()
    time.sleep(1)
    check('it exits with that bus', not alive(pid))


root = Path(tempfile.mkdtemp(prefix='upower-test.'))
rig = Rig(root)
try:
    main(rig)
finally:
    if rig.daemon and rig.daemon.poll() is None:
        rig.daemon.kill()
    rig.bus_process.kill()
    shutil.rmtree(root, ignore_errors=True)
print('\nFAILED: ' + ', '.join(failures) if failures else '\nAll passed')
sys.exit(bool(failures))
