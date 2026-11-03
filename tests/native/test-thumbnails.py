#!/data/data/com.termux/files/usr/bin/python
"""Record Nautilus's automatic preview behavior for fresh local image URIs."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from gi.repository import Gio

folder = Path.home() / 'Pictures' / f'thumbnail-check-{time.time_ns()}'
folder.mkdir(parents=True)
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=400x300', '-frames:v', '1', str(folder / 'image.png')], check=True)
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(folder / 'image.png'), '-frames:v', '1', str(folder / 'image.jpg')], check=True)
shutil.copyfile(str(Path.home() / '.local/share/livecd-native/backgrounds/fakurian/unsplash-7Ra7YDFR4Pw.avif'), folder / 'image.avif')
files = sorted(folder.iterdir())
settings = Gio.Settings.new('org.gnome.nautilus.preferences')
result = {'folder': str(folder), 'show_image_thumbnails': settings.get_string('show-image-thumbnails'),
          'thumbnail_limit': settings.get_value('thumbnail-limit').unpack(), 'samples': []}


def sample(elapsed):
    rows = []
    for path in files:
        uri = path.as_uri()
        digest = hashlib.md5(uri.encode()).hexdigest() + '.png'
        info = Gio.File.new_for_path(str(path)).query_info('standard::content-type,thumbnail::*', Gio.FileQueryInfoFlags.NONE, None)
        rows.append({'file': path.name, 'mime': info.get_content_type(),
            'thumbnail_path': info.get_attribute_byte_string('thumbnail::path'),
            'cache_matches': [str(p) for p in (Path.home() / '.cache/livecd-native/thumbnails').rglob(digest)]})
    result['samples'].append({'elapsed_seconds': elapsed, 'files': rows})


sample(0)
process = subprocess.Popen(['nautilus', '--new-window', str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(12)
    sample(12)
    time.sleep(18)
    sample(30)
    import re
    size = re.search(r'dimensions:\s+(\d+x\d+)', subprocess.check_output(['xdpyinfo'], text=True)).group(1)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', size, '-i', ':0', '-frames:v', '1', '-y', str(Path.home() / '.local/state/livecd-native/thumbnails.png')], check=True)
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
print(json.dumps(result, indent=2))
