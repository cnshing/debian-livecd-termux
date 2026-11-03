#!/bin/bash
# Run an isolated stock GSConnect on a Debian PC as a pairing partner for the phone.
# Its private bus and XDG directories leave the PC's own GSConnect and pairings alone.
# Usage: test-peer.sh start | stop | bus COMMAND... | cli DAEMON_ARGUMENTS...
#
# Do not exercise clipboard sync through it: it shares the PC's X clipboard. It needs an
# X server on DISPLAY (default :0) but opens no windows. test-protocol.py covers clipboard.
# It is still a new unpaired device to every GSConnect on the LAN. One already holding three
# unpaired devices switches off its own discovery and saves that; check `discoverable` after.
# An unexplained notification was also reported on the PC during testing; see VERIFICATION.md.
set -euo pipefail
dir=${LIVECD_GSCONNECT_PEER_DIR:-${XDG_RUNTIME_DIR:-/tmp}/livecd-gsconnect-peer}
daemon=/usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io/service/daemon.js

isolated() {
    env -i PATH="$PATH" HOME="$dir/home" LANG=C.UTF-8 DISPLAY="${DISPLAY:-:0}" GDK_BACKEND=x11 \
        LIVECD_GSCONNECT_PEER_DIR="$dir" \
        XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" XDG_CONFIG_HOME="$dir/config" \
        XDG_CACHE_HOME="$dir/cache" XDG_DATA_HOME="$dir/data" XDG_RUNTIME_DIR="$dir/run" \
        GNOME_SETUP_DISPLAY="${DISPLAY:-:0}" "$@"
}

case ${1:-} in
    start)
        mkdir -p "$dir/home" "$dir/config" "$dir/cache" "$dir/data" "$dir/run"
        chmod 700 "$dir" "$dir/run"
        isolated setsid dbus-run-session -- "$0" _inner > "$dir/log" 2>&1 < /dev/null &
        ;;
    _inner)
        printf '%s\n' "$DBUS_SESSION_BUS_ADDRESS" > "$dir/run/bus-address"
        gsettings set org.gnome.Shell.Extensions.GSConnect name 'PC test peer'
        printf '%s\n' "$$" > "$dir/run/pid"
        exec "$daemon"
        ;;
    stop)
        kill "$(cat "$dir/run/pid")"
        ;;
    bus)
        shift
        isolated DBUS_SESSION_BUS_ADDRESS="$(cat "$dir/run/bus-address")" "$@"
        ;;
    cli)
        shift
        "$0" bus "$daemon" "$@"
        ;;
    *) echo "Usage: $0 start | stop | bus COMMAND... | cli DAEMON_ARGUMENTS..." >&2; exit 2;;
esac
