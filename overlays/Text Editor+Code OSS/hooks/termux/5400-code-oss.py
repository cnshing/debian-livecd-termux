#!/data/data/com.termux/files/usr/bin/python
"""Use the desktop profile wrapper. Extensions are packages: code-oss-extension-*."""
import subprocess

from desktop import BASE, DATA, PREFIX

# Generic desktop metadata is fixed by packages/code-oss. This overlay selects
# the wrapper that supplies our private desktop configuration.
applications = DATA / 'applications'
applications.mkdir(parents=True, exist_ok=True)
for name in ('code-oss.desktop', 'code-oss-url-handler.desktop'):
    entry = (PREFIX / 'share/applications' / name).read_text()
    (applications / name).write_text(entry.replace(f'{PREFIX}/bin/code-oss', f'{BASE}/bin/code-oss'))
subprocess.run(['update-desktop-database', str(applications)], check=True)
