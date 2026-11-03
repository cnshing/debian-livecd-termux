#!/data/data/com.termux/files/usr/bin/python
"""Play a generated audio/video fixture in a real native mpv X11 window."""
import json
import os
from pathlib import Path
import re
import subprocess
import time

state = Path.home() / '.local/state/livecd-native'
video = Path.home() / 'Documents/livecd-native-validation/video.mp4'
video.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
    '-i', 'testsrc2=size=320x240:rate=15', '-f', 'lavfi',
    '-i', 'sine=frequency=440:sample_rate=44100', '-t', '5',
    '-c:v', 'mpeg4', '-c:a', 'aac', '-y', str(video)], check=True)
with (state / 'mpv-test.log').open('w') as log:
    player = subprocess.Popen(['mpv', '--title=LiveCD Native Video',
        '--loop-file=inf', '--vo=x11', '--hwdec=no', '--ao=pulse', str(video)],
        stdout=log, stderr=log)
    try:
        time.sleep(3)
        assert player.poll() is None
        window = subprocess.check_output(['xdotool', 'search', '--onlyvisible',
            '--name', 'LiveCD Native Video'], text=True).splitlines()[-1]
        subprocess.run(['xdotool', 'windowactivate', '--sync', window], check=True)
        size = re.search(r'dimensions:\s+(\d+x\d+)',
            subprocess.check_output(['xdpyinfo'], text=True)).group(1)
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-f', 'x11grab', '-video_size', size, '-i', os.environ['DISPLAY'],
            '-ss', '2', '-frames:v', '1', '-y', str(state / 'video.png')], check=True)
        output = (state / 'mpv-test.log').read_text()
        assert 'AO: [pulse]' in output and 'VO: [x11]' in output, output
        print(json.dumps({'ok': True, 'window': window, 'bytes': video.stat().st_size,
            'log': output}, indent=2))
    finally:
        player.terminate()
        player.wait(timeout=5)
