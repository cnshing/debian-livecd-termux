#!/data/data/com.termux/files/usr/bin/bash
# Install Firefox, Chromium, Google Chrome and ungoogled Chromium on native Termux, with
# the live CD's extensions, using the live CD's own extension scripts. Nothing runs under PRoot.
# Usage: install.sh [firefox] [chromium] [chrome] [ungoogled-chromium]    (default: all four)
# Rerun to update Chrome and the pinned Chromium builds, which apt does not manage here,
# and the extension files.
set -eu
test "${PREFIX:-}" = /data/data/com.termux/files/usr || { echo 'Run this script in native Termux (com.termux).' >&2; exit 2; }
test "$(dpkg --print-architecture)" = aarch64 || { echo 'Google publishes Chrome for arm64 only, and this port is tested on aarch64.' >&2; exit 2; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$source_dir/../../.." && pwd)
scripts=$repo/overlays/Browser/lb/hooks/normal/scripts
. "$scripts/install-chrome-extensions.sh"
. "$scripts/install-firefox-extensions.sh"
export DEBIAN_FRONTEND=noninteractive

test $# -gt 0 || set -- firefox chromium chrome ungoogled-chromium
for browser in "$@"; do
    case "$browser" in firefox|chromium|chrome|ungoogled-chromium) ;; *) echo "Unknown browser: $browser" >&2; exit 2;; esac
done
wants() { case " $selected " in *" $1 "*) return 0;; *) return 1;; esac; }
selected=" $* "

# The hook asks dpkg for the version, and dpkg cannot see Chrome or Termux's chromium name.
chrome_prodversion() { printf '%s\n' "$browser_major"; }

# IDs match upstream's os/config.yaml. Both Chromium builds get uBlock Origin Lite because Google's
# update server answers 204, nothing to install, when asked for full uBlock Origin at
# this version. The live CD's ungoogled-chromium gets the full one from a Debian package.
install_chromium_extensions() {
    for entry in 'ddkjiahejlhfcafbddmgiahcphecmpfh uBlock Origin Lite' \
                 'nngceckbapebfimnlniiiahkandclblb Bitwarden' \
                 'ghmbeldphafepmbegfdlkpapadhbakde Proton Pass'; do
        install_crx "${entry%% *}" "${entry#* }" "$1"
        # install_crx only warns, so that one bad extension does not stop an image build.
        test -f "$1/${entry%% *}.crx" || { echo "Missing extension: ${entry#* }" >&2; exit 1; }
    done
}

packages="curl unzip jq"
wants firefox && packages="$packages firefox"
wants chromium && packages="$packages chromium"
wants chrome && packages="$packages gnupg patchelf desktop-file-utils clang git llvm openssl-tool patch rust"
# The VA-API Chromium builds are Debian's and ungoogled-chromium's glibc binaries.
if wants chromium || wants ungoogled-chromium; then
    packages="$packages patchelf clang lld"
fi
apt-get update
if wants chrome || wants chromium || wants ungoogled-chromium; then
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
fi
apt-get install -y --no-install-recommends $packages

if wants firefox; then
    extensions="$PREFIX/share/mozilla/extensions/{ec8030f7-c20a-464f-9b0e-13a3a9e97384}"
    install_firefox_xpi 'uBlock0@raymondhill.net' 'uBlock Origin' "$extensions"
    install_firefox_xpi '{446900e4-71c2-419f-a6a7-df9c091e268b}' 'Bitwarden' "$extensions"
    install_firefox_xpi '78272b6fa58f4a1abaac99321d503a20@proton.me' 'Proton Pass' "$extensions"
    # The live CD relies on Debian's value here: upstream's default leaves add-ons from
    # this directory disabled behind a prompt. Upstream also scans it only for a new profile
    # or a Firefox upgrade, which would miss these in a profile that already exists.
    # This directory is the one that loads after, and so overrides, Firefox's own defaults.
    mkdir -p "$PREFIX/lib/firefox/browser/defaults/preferences"
    cat > "$PREFIX/lib/firefox/browser/defaults/preferences/livecd-extensions.js" <<'EOF'
pref("extensions.autoDisableScopes", 3);
pref("extensions.startupScanScopes", 8);
EOF
fi

if wants chromium; then
    browser_major=$(dpkg-query -W -f='${Version}' chromium | cut -d. -f1)
    install_chromium_extensions "$PREFIX/lib/chromium/extensions"
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
    browser_major=$(cut -d. -f1 "$PREFIX/opt/google/chrome/INSTALLED_VERSION")
    install_chromium_extensions "$PREFIX/opt/google/chrome/extensions"
fi

# Termux's chromium package compiles VA-API out. These pinned builds keep it, and run
# on the shared glibc GPU and video stack that the chrome step sets up. --activate makes
# the desktop's Chromium menu entry and chromium-browser start the VA-API build; the
# package's own command stays available as $PREFIX/bin/chromium-browser.
prebuilt=
wants chromium && prebuilt="$prebuilt chromium"
wants ungoogled-chromium && prebuilt="$prebuilt ungoogled-chromium"
if [ -n "$prebuilt" ]; then
    if [ -f "$HOME/.local/opt/livecd-native/acceleration/glibc/manifest.json" ]; then
        python "$source_dir/install-chromium.py" $prebuilt --activate
        for name in $prebuilt; do
            browser_major=$(jq -r --arg name "$name" '.browsers[$name].version' "$source_dir/chromium-prebuilt.lock.json" | cut -d. -f1)
            install_chromium_extensions "$PREFIX/opt/livecd-browsers/$name-extensions"
        done
    elif wants ungoogled-chromium; then
        echo 'ungoogled-chromium needs the shared GPU stack: run install.sh chrome ungoogled-chromium.' >&2; exit 2
    else
        echo 'Chromium stays on Termux'"'"'s build without hardware video until install.sh chrome sets up the shared GPU stack.' >&2
    fi
fi
printf '\nInstalled: %s\n' "$*"
