#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
# The server's default backend is Android GLES. Its ANGLE dependency is never
# selected by the qualified native Mali mpv profile.
if test -r /dev/mali0 && test -w /dev/mali0; then
    apt-get install -y --no-upgrade virglrenderer-android
fi
