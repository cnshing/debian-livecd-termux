#!/usr/bin/env python3
"""Select Unix desktop integrations while retaining Android's libc and Rust target.

This follows Termux's alacritty/ruffle approach: retarget the desktop crates only.
Never change libc, rustix, nix, getrandom or other syscall/ABI crates to Linux.
Downloaded versions and package checksums remain pinned. Cargo may prune unused
Wayland dependencies; audit the resulting lock against the upstream identities.
Update per-file vendor checksums after applying source transformations.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib


DESKTOP_CRATES = {
    'accesskit_winit', 'arboard', 'cpal', 'eframe', 'egui-winit', 'fontique',
    'global-hotkey', 'rfd', 'rustls-platform-verifier', 'webbrowser', 'wgpu', 'wgpu-core',
    'wgpu-hal', 'winit', 'x11-dl', 'x11rb', 'x11rb-protocol', 'xkbcommon-dl',
    'yeslogic-fontconfig-sys',
}
APK_OS = 'disabling_this_because_it_is_for_building_an_apk'
VENDOR_PATCHES = {
    'cpal': 'cpal-record-queue.vendor.diff',
    'libopus_sys': 'libopus-android-host.vendor.diff',
}


def desktop(text):
    # Normalized Cargo manifests also contain escaped quotes in cfg expressions.
    for quote in ('"', '\\"'):
        text = text.replace(quote + 'android' + quote, quote + APK_OS + quote)
        text = text.replace(quote + 'linux' + quote, quote + 'android' + quote)
    return text


def prepare(source, prefix):
    source = source.resolve()
    lock = (source / 'Cargo.lock').read_bytes()
    changes = {}

    def rewrite(path, transform):
        old = path.read_text()
        new = transform(old)
        if old != new:
            path.write_text(new)
            changes[str(path.relative_to(source))] = hashlib.sha256(new.encode()).hexdigest()

    # Native Termux uses X11 windows, rather than an Android Activity or Wayland.
    root = source / 'Cargo.toml'
    rewrite(root, lambda text: text.replace('"accesskit", "wayland", "x11"', '"accesskit", "x11"'))
    app_manifest = source / 'apps/desktop/Cargo.toml'
    rewrite(app_manifest, lambda text: text.replace(
        'winit = { workspace = true, features = ["wayland-csd-adwaita"] }',
        'winit.workspace = true').replace(
        'arboard = { version = "=3.6.1", features = ["wayland-data-control"] }',
        'arboard = "=3.6.1"'))
    rewrite(source / 'crates/platform/Cargo.toml', lambda text: text.replace(
        'features = ["xdg-portal", "wayland"]', 'features = ["xdg-portal"]'))

    for directory in (source / 'apps/desktop', source / 'crates'):
        for path in directory.rglob('*'):
            if path.suffix in ('.rs', '.toml'):
                rewrite(path, lambda text: text.replace(
                    'target_os = "linux"', 'any(target_os = "linux", target_os = "android")'))

    # Package updates come from APT, and must never install upstream's glibc binaries.
    rewrite(source / 'apps/desktop/src/updater_install.rs', lambda text: text.replace(
        "pub(super) fn linux_package_manager_update_command() -> Option<&'static str> {",
        "pub(super) fn linux_package_manager_update_command() -> Option<&'static str> {\n"
        '\tif cfg!(target_os = "android") { return Some("pkg upgrade serein"); }'))

    vendored = {}
    for directory in (source / 'termux-vendor').iterdir():
        manifest = directory / 'Cargo.toml'
        if manifest.is_file():
            name = tomllib.loads(manifest.read_text())['package']['name']
            if name in DESKTOP_CRATES | VENDOR_PATCHES.keys():
                vendored[name] = directory
    missing = (DESKTOP_CRATES | VENDOR_PATCHES.keys()) - vendored.keys()
    if missing:
        raise RuntimeError('Missing locked desktop crates: ' + ', '.join(sorted(missing)))

    for name in DESKTOP_CRATES:
        directory = vendored[name]
        for path in directory.rglob('*'):
            if path.suffix not in ('.rs', '.toml'):
                continue
            def transform(text):
                text = desktop(text)
                # Termux libraries have unversioned SONAMEs. Preserve libc's ABI.
                text = re.sub(r'(lib(?:xkbcommon(?:-x11)?|xcb|fontconfig)\.so)\.\d+', r'\1', text)
                return text.replace('/tmp', str(prefix) + '/tmp')
            rewrite(path, transform)

    # These defaults independently re-enable Wayland after eframe disables it.
    # X11 clipboard uses arboard; Unix accessibility does not need winit/wayland.
    rewrite(vendored['egui-winit'] / 'Cargo.toml', lambda text: text.replace(
        '    "smithay-clipboard",\n', ''))
    rewrite(vendored['accesskit_winit'] / 'Cargo.toml', lambda text: text.replace(
        '    "winit/wayland",\n', '').replace('    "winit/wayland-dlopen",\n', ''))

    for name, filename in VENDOR_PATCHES.items():
        patch = Path(__file__).with_name(filename)
        subprocess.run(['patch', '--forward', '-p1', '-d', str(vendored[name]), '-i', str(patch)], check=True)

    # Cargo verifies vendored files before building. Retain each crate's package
    # hash and replace only file hashes for the locally patched source.
    for directory in vendored.values():
        path = directory / '.cargo-checksum.json'
        checksum = json.loads(path.read_text())
        checksum['files'] = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                             for name in checksum['files']}
        path.write_text(json.dumps(checksum, sort_keys=True) + '\n')

    # Removing Wayland features prunes their dependencies. Resolve offline from
    # the original vendor set, then reject any new version/source/package hash.
    subprocess.run(['cargo', 'metadata', '--offline', '--format-version=1'],
                   cwd=source, stdout=subprocess.DEVNULL, check=True)
    def identities(content):
        return {(item['name'], item['version'], item.get('source'), item.get('checksum'))
                for item in tomllib.loads(content)['package']}
    original = identities(lock.decode())
    current = identities((source / 'Cargo.lock').read_text())
    if current - original:
        raise RuntimeError('Preparation changed locked dependency identities: ' + repr(current - original))
    print(f'Prepared Termux desktop sources: {len(changes)} files; all dependency versions pinned')


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
