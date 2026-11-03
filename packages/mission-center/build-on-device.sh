#!/data/data/com.termux/files/usr/bin/bash
# Compatibility entry point: build and install an APT-owned Termux package.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
exec bash "$repo/tools/build-packages.sh" --install mission-center "$@"
