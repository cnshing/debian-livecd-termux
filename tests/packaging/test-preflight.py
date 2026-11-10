#!/usr/bin/env python3
"""src/preflight.sh: each missing Android app or permission names the feature it turns off.

A fake pm answers from a list of installed packages, and a fake rish answers Shizuku's shell
commands from the phone's real output formats, so it runs on any host.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PREFLIGHT = Path(__file__).resolve().parents[2] / 'src/preflight.sh'
FAKE_PM = '''#!/bin/sh
# pm path PACKAGE
grep -qx "$2" "$FAKE/installed"
'''
# rish -c "COMMAND": shell id, granted permissions from $FAKE/granted, and a grant log.
FAKE_RISH = '''#!/bin/sh
shift
echo "$*" >> "$FAKE/rish.log"
case $* in
    id) test -e "$FAKE/shizuku-running" && echo 'uid=2000(shell) gid=2000(shell)';;
    'dumpsys package com.termux.api')
        echo '    requested permissions:'
        echo '      android.permission.CAMERA'
        echo '      android.permission.RECORD_AUDIO'
        echo '    runtime permissions:'
        for permission in CAMERA RECORD_AUDIO; do
            state=false; grep -qx "$permission" "$FAKE/granted" && state=true
            echo "        android.permission.$permission: granted=$state, flags=[ USER_SET]"
        done;;
    'dumpsys deviceidle whitelist')
        echo 'system,com.android.shell,2000'
        grep -qx idle "$FAKE/granted" && echo 'user,com.termux,10309';;
    'pm grant com.termux.api android.permission.'*) echo "${*##*.}" >> "$FAKE/granted";;
    'dumpsys deviceidle whitelist +com.termux') echo idle >> "$FAKE/granted";;
esac
exit 0
'''
ALL_APPS = ['com.termux.x11', 'com.termux.api', 'moe.shizuku.privileged.api']


class Preflight(unittest.TestCase):
    def setUp(self):
        self.fake = Path(tempfile.mkdtemp())
        self.home = self.fake / 'home'
        shizuku = self.home / '.local/lib/shizuku'
        shizuku.mkdir(parents=True)
        for name, text in (('pm', FAKE_PM), ('rish', FAKE_RISH)):
            path = (self.fake if name == 'pm' else shizuku) / name
            path.write_text(text)
            path.chmod(0o755)
        (shizuku / 'rish_shizuku.dex').write_text('')
        self.sdcard = self.fake / 'sdcard'
        (self.sdcard / 'Android').mkdir(parents=True)
        self.gpu = self.fake / 'kgsl-3d0'
        self.gpu.write_text('')
        self.apps(ALL_APPS)
        (self.fake / 'granted').write_text('CAMERA\nRECORD_AUDIO\nidle\n')
        (self.fake / 'shizuku-running').write_text('')

    def apps(self, names):
        (self.fake / 'installed').write_text(''.join(f'{name}\n' for name in names))

    def run_preflight(self, *args):
        env = {**os.environ, 'HOME': str(self.home), 'FAKE': str(self.fake),
               'LIVECD_PREFLIGHT_PM': str(self.fake / 'pm'), 'LIVECD_PREFLIGHT_SDCARD': str(self.sdcard),
               'LIVECD_PREFLIGHT_GPU': str(self.gpu)}
        result = subprocess.run(['bash', str(PREFLIGHT), *args], env=env, capture_output=True,
                                text=True, timeout=120)
        lines = result.stdout.splitlines()
        # Each feature's level, by its name: {'Phone microphone': 'WARN', ...}
        levels = {line[8:].split(' (')[0]: line.split()[0] for line in lines if line[:2] == '  ' and line[2] != ' '}
        return result.returncode, levels, result.stdout

    def problems(self, levels):
        return {feature: level for feature, level in levels.items() if level != 'ok'}

    def test_everything_granted(self):
        status, levels, output = self.run_preflight()
        self.assertEqual(status, 0, output)
        self.assertEqual(len(levels), 9, output)
        self.assertEqual(self.problems(levels), {}, output)

    def test_missing_camera_names_only_the_cameras(self):
        (self.fake / 'granted').write_text('RECORD_AUDIO\nidle\n')
        status, levels, output = self.run_preflight()
        self.assertEqual(status, 0, output)
        self.assertEqual(self.problems(levels), {'Front and rear cameras': 'WARN'}, output)
        self.assertIn('Termux:API > Permissions > Camera', output)

    def test_missing_microphone_turns_off_both_microphones(self):
        (self.fake / 'granted').write_text('CAMERA\nidle\n')
        _, levels, output = self.run_preflight()
        self.assertEqual(self.problems(levels),
                         {'Phone microphone': 'WARN', 'Bluetooth headset microphone': 'WARN'}, output)

    def test_missing_battery_exemption(self):
        (self.fake / 'granted').write_text('CAMERA\nRECORD_AUDIO\n')
        _, levels, output = self.run_preflight()
        self.assertEqual(self.problems(levels), {'Desktop keeps running in the background': 'WARN'}, output)

    def test_missing_storage(self):
        (self.sdcard / 'Android').rmdir()
        _, levels, output = self.run_preflight()
        self.assertEqual(self.problems(levels),
                         {'Internal storage, SD card and USB drives in Files': 'WARN'}, output)

    def test_missing_gpu(self):
        self.gpu.unlink()
        _, levels, output = self.run_preflight()
        self.assertEqual(self.problems(levels), {'GPU rendering and hardware video': 'WARN'}, output)

    def test_missing_termux_x11_stops(self):
        self.apps(['com.termux.api', 'moe.shizuku.privileged.api'])
        status, levels, output = self.run_preflight()
        self.assertEqual(status, 2, output)
        self.assertEqual(self.problems(levels), {'Desktop display': 'STOP'}, output)

    def test_missing_termux_api(self):
        self.apps(['com.termux.x11', 'moe.shizuku.privileged.api'])
        status, levels, output = self.run_preflight()
        self.assertEqual(status, 0, output)
        self.assertEqual(set(self.problems(levels)),
                         {'Phone microphone', 'Front and rear cameras', 'Battery status'}, output)

    def test_stopped_shizuku_names_its_features(self):
        (self.fake / 'shizuku-running').unlink()
        status, levels, output = self.run_preflight()
        self.assertEqual(status, 0, output)
        self.assertEqual(set(self.problems(levels)),
                         {'Phone microphone', 'Bluetooth headset microphone', 'Front and rear cameras',
                          'Whole-device CPU and processes in Mission Center',
                          'Desktop keeps running in the background'}, output)
        self.assertIn('Start Shizuku, allow Termux', output)

    def test_grant_fills_in_what_was_missing(self):
        (self.fake / 'granted').write_text('')
        _, before, _ = self.run_preflight()
        self.assertEqual(len(self.problems(before)), 4)
        status, after, output = self.run_preflight('--grant')
        self.assertEqual(status, 0, output)
        self.assertEqual(self.problems(after), {}, output)
        log = (self.fake / 'rish.log').read_text()
        self.assertIn('appops set com.termux READ_EXTERNAL_STORAGE allow', log)


if __name__ == '__main__':
    unittest.main()
