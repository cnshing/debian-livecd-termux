#!/data/data/com.termux/files/usr/bin/bash
# Install Firefox, Chromium and Google Chrome, and optionally ungoogled Chromium, on native
# Termux, with extensions supplied by this repository's webext packages. Nothing
# runs under PRoot. All of them use the GPU and Android's hardware video.
# Usage: install.sh [firefox] [chromium] [chrome] [ungoogled-chromium]
#        (default: firefox chromium chrome)
# Rerun to update Chrome and the pinned ungoogled Chromium build, which apt does not manage
# here. APT manages extension updates.
set -eu
test "${PREFIX:-}" = /data/data/com.termux/files/usr || { echo 'Run this script in native Termux (com.termux).' >&2; exit 2; }
test "$(dpkg --print-architecture)" = aarch64 || { echo 'Google publishes Chrome for arm64 only, and this port is tested on aarch64.' >&2; exit 2; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export DEBIAN_FRONTEND=noninteractive

test $# -gt 0 || set -- firefox chromium chrome
for browser in "$@"; do
    case "$browser" in firefox|chromium|chrome|ungoogled-chromium) ;; *) echo "Unknown browser: $browser" >&2; exit 2;; esac
done
# An offline install has no Google Chrome: Google does not allow redistributing it, so it is not in
# the offline tarball, nor are the Debian libraries and ungoogled Chromium build fetched for these.
if test -n "${LIVECD_OFFLINE:-}"; then
    online=
    for browser in "$@"; do
        case "$browser" in
            chrome|ungoogled-chromium) online="$online $browser";;
            *) set -- "$@" "$browser";;
        esac
        shift
    done
    if test -n "$online"; then
        echo "Offline: leaving out$online. Once online: bash $source_dir/install.sh$online" >&2
    fi
    test $# -gt 0 || exit 0
fi
wants() { case " $selected " in *" $1 "*) return 0;; *) return 1;; esac; }
selected=" $* "

packages=""
wants firefox && packages="$packages firefox webext-ublock-origin-firefox webext-bitwarden-firefox webext-proton-pass-firefox"
if wants chromium || wants chrome || wants ungoogled-chromium; then
    packages="$packages webext-ublock-origin-lite-chromium webext-bitwarden-chromium webext-proton-pass-chromium"
fi
wants chromium && packages="$packages chromium"
# Chrome's GPU and video stack, and the loader that runs it, are packages from this repository.
wants chrome && packages="$packages gnupg patchelf desktop-file-utils openssl-tool bionilux android-vaapi-glibc termux-va"
# The pinned ungoogled-chromium is a glibc binary, with small helpers compiled here.
wants ungoogled-chromium && packages="$packages patchelf clang lld"
apt-get update
if wants chrome || wants ungoogled-chromium; then
    # glibc-repo only adds a source list, so index it before asking for glibc.
    apt-get install -y --no-install-recommends glibc-repo
    apt-get update
    packages="$packages glibc"
fi
# A running desktop must not have shared libraries replaced beneath it. New packages are fine.
if apt-get -s install --no-install-recommends $packages | grep -q '^Inst [^ ]* \['; then
    mkdir -p "$HOME/.local/state/livecd"
    # install.sh and apply-overlays.py already hold this lock when they run this as a hook.
    test -n "${LIVECD_SETUP_LOCKED:-}" || exec 9>"$HOME/.local/state/livecd/session.lock"
    test -n "${LIVECD_SETUP_LOCKED:-}" || flock -n 9 || { echo 'These packages upgrade shared libraries: stop the desktop first (livecd stop).' >&2; exit 2; }
    # livecd-desktop's APT guard would otherwise take this lock for the running desktop's.
    export LIVECD_SETUP_LOCKED=1
fi
apt-get install -y --no-install-recommends $packages

if wants chromium; then
    # Termux's recipe fills in placeholder names upstream has since renamed, which leaves
    # this menu entry unable to start. An upgrade restores the file; rerunning repairs it.
    sed -i -e "s|@@desktop_exec|$PREFIX/bin/chromium-browser|" -e 's|@@startup_wm_class|chromium|' \
        -e 's|@@desktop_icon|chromium|' "$PREFIX/share/applications/chromium.desktop"
    mkdir -p "$PREFIX/etc/chromium"
    cp "$source_dir/chromium-gpu.conf" "$PREFIX/etc/chromium/livecd-gpu.conf"
fi

if wants chrome; then
    # Under Bionilux its command line starts with the loader, not with Chrome.
    if pgrep -f "$PREFIX/opt/google/chrome/chrome" >/dev/null; then
        echo 'Close Google Chrome before updating it.' >&2; exit 2
    fi
    python "$source_dir/install-chrome.py"
    python "$source_dir/install-native-video.py"
fi

# This repository's chromium package is built with VA-API, which Termux's compiles out.
# The pinned ungoogled-chromium build runs on Chrome's shared glibc stack instead.
if wants ungoogled-chromium; then
    if [ -f "$PREFIX/lib/android-vaapi-glibc/manifest.json" ] ||
       [ -f "$HOME/.local/opt/livecd-native/acceleration/glibc/manifest.json" ]; then
        python "$source_dir/install-chromium.py" ungoogled-chromium --activate
    else
        echo 'ungoogled-chromium needs the shared GPU stack: run install.sh chrome ungoogled-chromium.' >&2; exit 2
    fi
fi
printf '\nInstalled: %s\n' "$*"
