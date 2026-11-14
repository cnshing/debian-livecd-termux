#!/usr/bin/env python3
"""Private panvk-desktop.py adapter: audit real terminal-child environment.

Set GHOSTTY_DMABUF_LAUNCHER to the extracted package's bin/ghostty-panvk-dmabuf
and pass this file as --ghostty-launcher. Only the harness-generated shell
script inside LIVECD_FULLSCREEN_TEST is changed. No installed files change.
"""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import sys

launcher = Path(os.environ['GHOSTTY_DMABUF_LAUNCHER']).resolve(strict=True)
out = Path(os.environ['LIVECD_FULLSCREEN_TEST']).resolve(strict=True)
script = Path(sys.argv[-1]).resolve(strict=True)
if script != out / 'ghostty-shell.sh' or '-e' not in sys.argv:
    raise RuntimeError('This adapter requires the private Ghostty harness shell')
spec = importlib.util.spec_from_file_location('packaged_launcher', launcher)
# The installed launcher has no .py suffix.
if spec is None:
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader('packaged_launcher', SourceFileLoader('packaged_launcher', str(launcher)))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
env, _ = module.environment(os.environ)
keys = sorted(k for k in env.keys() | os.environ.keys() if env.get(k) != os.environ.get(k))
(out / 'ghostty-child-expected.json').write_text(json.dumps({k: os.environ[k] for k in keys if k in os.environ}))
code = ('import json,os; from pathlib import Path; '
        f'Path({str(out / "ghostty-child-actual.json")!r}).write_text('
        f'json.dumps({{k:os.environ[k] for k in {keys!r} if k in os.environ}}))')
script.write_text(shlex.quote(sys.executable) + ' -c ' + shlex.quote(code) + '\n' + script.read_text())
os.execv(sys.executable, [sys.executable, str(launcher), *sys.argv[1:]])
