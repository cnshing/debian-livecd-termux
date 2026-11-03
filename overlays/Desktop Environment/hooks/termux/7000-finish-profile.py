#!/data/data/com.termux/files/usr/bin/python
"""Build the databases generated from every overlay's files. Upstream's 7000-dconf-update."""
from pathlib import Path
import subprocess

from desktop import BASE, DATA, environment

(BASE / 'autostart').mkdir(exist_ok=True)
for directory in ('Desktop', 'Documents', 'Downloads', 'Templates', 'Pictures', 'Videos', 'Music'):
    (Path.home() / directory).mkdir(exist_ok=True)
subprocess.run(['dconf', 'compile', str(BASE / 'dconf-defaults'), str(BASE / 'dconf.d')], check=True)
subprocess.run(['update-desktop-database', str(DATA / 'applications')], check=True)
subprocess.run(['fc-cache', '-f', str(DATA / 'fonts')], env=environment(), check=True)
