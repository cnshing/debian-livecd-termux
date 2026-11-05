#!/data/data/com.termux/files/usr/bin/bash
# Compatibility entry point: the fixed session preload is owned by android-procfs.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec bash "$repo/tools/build-packages.sh" --install android-procfs "$@"
