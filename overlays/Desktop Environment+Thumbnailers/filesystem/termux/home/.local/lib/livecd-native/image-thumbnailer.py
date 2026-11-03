#!/data/data/com.termux/files/usr/bin/python
"""Decode local images with native FFmpeg for the GNOME thumbnail factory."""
import subprocess
import sys

source, destination, size = sys.argv[1:]
size = int(size)
if size < 1 or size > 4096:
    raise SystemExit('Invalid thumbnail size')
subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', source,
    '-frames:v', '1', '-vf', f'scale={size}:{size}:force_original_aspect_ratio=decrease',
    '-f', 'image2', '-c:v', 'png', '-y', destination], check=True, timeout=25)
