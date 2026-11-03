#!/bin/bash
# PC-side helper for the established phone-test-rig.md connection.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
serial=${PHONE_SERIAL:-${ANDROID_SERIAL:-}}
adb_command=(adb)
if test -n "$serial"; then adb_command+=(-s "$serial"); fi
host=${TERMUX_SSH_HOST:-termux}
"${adb_command[@]}" forward tcp:8022 tcp:8022 >/dev/null
case ${1:-} in
    setup)
        bundle=$(mktemp --suffix=.tgz)
        trap 'rm -f -- "$bundle"' EXIT
        tar --exclude='__pycache__' -czf "$bundle" install.sh src overlays prebuilt tests
        ssh "$host" 'mkdir -p "$HOME/debian-livecd-termux"; tar -xzf - -C "$HOME/debian-livecd-termux"' < "$bundle"
        if test -n "${LIVECD_REPO_TARBALL:-}"; then
            # Install a tarball you already have, such as a workflow artifact, instead of the latest release.
            ssh "$host" 'cat > "$HOME/debian-livecd-termux/livecd-repo.tar.gz"' < "$LIVECD_REPO_TARBALL"
            ssh "$host" 'bash "$HOME/debian-livecd-termux/install.sh" --repo-tarball "$HOME/debian-livecd-termux/livecd-repo.tar.gz"'
        else
            ssh "$host" 'bash "$HOME/debian-livecd-termux/install.sh"'
        fi
        ;;
    start|stop|status|select)
        action=$1
        shift
        options=""
        while test "$#" -gt 0; do
            case "$1" in
                --safe)
                    test "$action" = start || { echo '--safe requires start' >&2; exit 2; }
                    options="$options --safe"
                    shift
                    ;;
                --renderer)
                    test "$action" = start || test "$action" = select || { echo '--renderer requires start or select' >&2; exit 2; }
                    case ${2:-} in software|zink) ;; *) echo 'Renderer must be software or zink' >&2; exit 2;; esac
                    options="$options --renderer $2"
                    shift 2
                    ;;
                *) echo 'Unsupported desktop argument' >&2; exit 2;;
            esac
        done
        ssh "$host" "\"\$HOME/.local/bin/livecd\" $action $options"
        ;;
    validate)
        ssh "$host" "\"\$HOME/.local/bin/livecd\" validate"
        ;;
    screenshot)
        test "$#" = 1 || { echo 'screenshot takes no arguments; it prints a new temporary PNG path' >&2; exit 2; }
        capture=$(mktemp --suffix=.png "${TMPDIR:-/tmp}/livecd-screenshot.XXXXXXXX")
        if ! "${adb_command[@]}" exec-out screencap -p > "$capture"; then
            rm -f -- "$capture"
            exit 1
        fi
        printf '%s\n' "$capture"
        ;;
    *) printf 'Usage: bash tools/rig.sh setup|start [--safe] [--renderer software|zink]|stop|status|validate|select [--renderer software|zink]|screenshot\n' >&2; exit 2;;
esac
