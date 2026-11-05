#!/data/data/com.termux/files/usr/bin/bash
# Compatibility entry point: build and install an APT-owned Termux package.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
if test "${1:-}" = --no-install; then
    shift
    exec bash "$repo/tools/build-packages.sh" android-upower "$@"
fi
exec bash "$repo/tools/build-packages.sh" --install android-upower "$@"
