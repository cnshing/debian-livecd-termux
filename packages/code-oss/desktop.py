#!/usr/bin/env python3
"""Resolve the desktop tokens left by the upstream Termux packaging recipe."""
import json
from pathlib import Path
import re
import sys


def main():
    applications, product = map(Path, sys.argv[1:])
    protocol = json.loads(product.read_text())['urlProtocol']
    for name in ('code-oss.desktop', 'code-oss-url-handler.desktop'):
        path = applications / name
        text = path.read_text().replace('@@DESKTOP_NAME@@', 'code-oss').replace('@@URLPROTOCOL@@', protocol)
        if re.search(r'@@[A-Z_]+@@', text):
            raise RuntimeError('Unresolved desktop metadata: ' + name)
        path.write_text(text)


if __name__ == '__main__':
    main()
