#!/usr/bin/env python3
"""Generate the native resources without invoking upstream's Cargo wrapper.

Meson's upstream wrapper resets CARGO_HOME/RUSTFLAGS, which loses the Termux
cross toolchain. Use the same Blueprint/GResource inputs with Cargo directly.
"""
import json
from pathlib import Path
import subprocess
import sys

source, build = map(lambda p: Path(p).resolve(), sys.argv[1:3])
prefix = sys.argv[3]
(build / 'src').mkdir(parents=True, exist_ok=True)
resources = build / 'resources'
resources.mkdir(exist_ok=True)
config = {
    'VERSION': '1.2.0', 'GETTEXT_PACKAGE': 'missioncenter',
    'LOCALEDIR': prefix + '/share/locale',
    'PKGDATADIR': prefix + '/share/missioncenter',
    'APP_ID': 'io.missioncenter.MissionCenter',
}
(build / 'src/config.rs').write_text(''.join(
    f'pub static {key}: &str = {json.dumps(value)};\n' for key, value in config.items()))
blueprints = sorted((source / 'resources').rglob('*.blp'))
subprocess.run(['blueprint-compiler', 'batch-compile', str(resources),
                str(source / 'resources'), *map(str, blueprints)], check=True)
subprocess.run(['glib-compile-resources',
                str(source / 'resources/missioncenter.gresource.xml'),
                '--sourcedir=' + str(resources), '--sourcedir=' + str(source / 'resources'),
                '--target=' + str(resources / 'missioncenter.gresource')], check=True)
hwdb = source / 'subprojects/magpie/platform-linux/hwdb'
subprocess.run([sys.executable, str(hwdb / 'generate_hwdb.py'), '--output',
                str(build / 'hwdb'), str(hwdb / '20-pci-vendor-model.hwdb'),
                str(hwdb / '20-usb-vendor-model.hwdb')], check=True)
