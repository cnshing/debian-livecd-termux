#!/data/data/com.termux/files/usr/bin/python
"""Use the desktop profile wrapper and install extensions from Open VSX."""
import os
import subprocess

from desktop import BASE, CONFIG, DATA, PREFIX

# The most downloaded extension for each feature. Why these, and what each does not
# replace, is in docs/code-oss/README.md.
EXTENSIONS = (
    'GitHub.vscode-pull-request-github',
    'GitHub.vscode-github-actions',
    'eamodio.gitlens',
    'mhutchie.git-graph',
    'jeanp413.open-remote-ssh',
    'Kelvin.vscode-sshfs',
)

# Generic desktop metadata is fixed by packages/code-oss. This overlay selects
# the wrapper that supplies our private desktop configuration.
applications = DATA / 'applications'
applications.mkdir(parents=True, exist_ok=True)
for name in ('code-oss.desktop', 'code-oss-url-handler.desktop'):
    entry = (PREFIX / 'share/applications' / name).read_text()
    (applications / name).write_text(entry.replace(f'{PREFIX}/bin/code-oss', f'{BASE}/bin/code-oss'))
subprocess.run(['update-desktop-database', str(applications)], check=True)

# The desktop's configuration directory, rather than leaving a second one beside it.
env = {**os.environ, 'XDG_CONFIG_HOME': str(CONFIG)}
for extension in EXTENSIONS:
    subprocess.run(['code-oss', '--install-extension', extension], env=env, stdin=subprocess.DEVNULL, check=True)
