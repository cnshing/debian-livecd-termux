#!/data/data/com.termux/files/usr/bin/bash
# Entrypoint. Run in native Termux from a checkout of this repository:
#   bash install.sh [--repo-tarball FILE] [OPT-IN-OVERLAY...]
# It fetches the compiled packages from this project's latest GitHub release, unless
# --repo-tarball names a copy you already have, and unpacks them into a local apt repository.
set -euo pipefail
test "${PREFIX:-}" = /data/data/com.termux/files/usr || { echo 'Run in native com.termux, outside PRoot.' >&2; exit 2; }
test "$(dpkg --print-architecture)" = aarch64 || { echo 'The pinned GNOME runtime requires aarch64.' >&2; exit 2; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HOME/.local/state/livecd"
exec > >(tee -a "$HOME/.local/state/livecd/install.log") 2>&1
echo "=== install.sh $(date '+%F %T') $*"
trap 'echo "install.sh stopped at line $LINENO. The log is ~/.local/state/livecd/install.log." >&2' ERR
# The desktop's Android integrations need these apps. Termux cannot install them, so name what is missing.
missing=
for app in com.termux.x11=Termux:X11 com.termux.api=Termux:API moe.shizuku.privileged.api=Shizuku; do
    /system/bin/pm path "${app%%=*}" >/dev/null 2>&1 || missing="$missing ${app#*=}"
done
test -z "$missing" || { echo "Install these Android apps first:$missing. See README.md." >&2; exit 2; }
# Shared storage holds Shizuku's rish export, and Files shows it. termux-setup-storage asks Android.
if ! test -r /sdcard/Android; then
    termux-setup-storage || true
    for _ in $(seq 60); do test -r /sdcard/Android && break; sleep 1; done
    test -r /sdcard/Android || { echo 'Allow Termux storage access, then run this again.' >&2; exit 2; }
fi
shizuku=$HOME/.local/lib/shizuku
if ! test -f "$shizuku/rish_shizuku.dex"; then
    # find reports Android's unreadable app directories as a failure.
    exported=$(find /sdcard/ -maxdepth 3 -name rish_shizuku.dex -printf '%h\n' 2>/dev/null | head -n 1 || true)
    if test -z "$exported" || ! test -f "$exported/rish"; then
        echo 'In Shizuku, choose "Use Shizuku in terminal apps", export the files to shared storage, then run this again.' >&2
        exit 2
    fi
    install -d -m 700 "$shizuku"
    install -m 700 "$exported/rish" "$shizuku/rish"
    install -m 400 "$exported/rish_shizuku.dex" "$shizuku/rish_shizuku.dex"
fi
rish() { RISH_APPLICATION_ID=com.termux RISH_PRESERVE_ENV=0 timeout 30 "$shizuku/rish" -c "$*" </dev/null; }
# Shizuku+ may print a waiting notice before the answer, and its first calls after a pause
# can return nothing.
for attempt in $(seq 10); do
    case $(rish id 2>/dev/null || true) in *uid=2000\(shell\)*) break;; esac
    if test "$attempt" = 10; then
        echo 'Shizuku did not answer. Start Shizuku and allow Termux under its authorized apps, then run this again.' >&2
        exit 2
    fi
    sleep 2
done
# Termux:API shares Termux's user ID, so its microphone permission covers the desktop's processes.
rish pm grant com.termux.api android.permission.RECORD_AUDIO
# Android otherwise stops a backgrounded desktop to save battery.
rish dumpsys deviceidle whitelist +com.termux >/dev/null
release=https://github.com/cnshing/debian-livecd-termux/releases/latest/download
tarball_name=livecd-termux-repo-aarch64.tar.gz
tarball=
case ${1:-} in
    --repo-tarball) tarball=$(realpath -- "${2:?--repo-tarball needs a file}"); shift 2;;
    -*) echo "Usage: bash install.sh [--repo-tarball FILE] [OPT-IN-OVERLAY...]" >&2; exit 2;;
esac
common="$HOME/.local/state/livecd"
state="$HOME/.local/state/livecd-native"
base="$HOME/.local/lib/livecd-native"
install -d -m 700 "$common" "$state/baseline" "$base" "$HOME/.local/bin" "$HOME/.local/lib/livecd"
exec 9>"$common/session.lock"
flock -n 9 || { echo 'Stop the running desktop before native setup.' >&2; exit 2; }
export LIVECD_SETUP_LOCKED=1
if ! test -f "$state/baseline/complete"; then
  if test -f "$state/baseline/host-packages.tsv" && test -f "$state/baseline/termux-prefix.tar" && test -f "$state/baseline/native-settings.tar"; then
    tar -tf "$state/baseline/termux-prefix.tar" >/dev/null
    tar -tf "$state/baseline/native-settings.tar" >/dev/null
  else
    dpkg-query -W > "$state/baseline/host-packages.tsv"
    # Preserve the shared native ABI before any dependency installation.
    tar --exclude=usr/var/lib/proot-distro --exclude=usr/tmp \
        -cf "$state/baseline/termux-prefix.tar" -C /data/data/com.termux/files usr
    if test -d "$HOME/.config"; then
      tar -cf "$state/baseline/native-settings.tar" -C "$HOME" .config
    else
      tar -cf "$state/baseline/native-settings.tar" --files-from /dev/null
    fi
  fi
  touch "$state/baseline/complete"
fi
if test -f "$HOME/.local/lib/livecd/config.json" && ! test -f "$state/baseline/livecd-config.json"; then
  cp -p "$HOME/.local/lib/livecd/config.json" "$state/baseline/livecd-config.json"
fi
export DEBIAN_FRONTEND=noninteractive
if test -z "$tarball"; then
    download=$(mktemp -d)
    trap 'rm -rf -- "$download"' EXIT
    if ! curl --fail --location --retry 3 "$release/$tarball_name" -o "$download/$tarball_name" ||
       ! curl --fail --location --retry 3 "$release/$tarball_name.sha256" -o "$download/$tarball_name.sha256"; then
        echo "Could not download a release from $release. Install a copy with: bash install.sh --repo-tarball FILE" >&2
        exit 2
    fi
    (cd "$download" && sha256sum --check --status "$tarball_name.sha256")
    tarball=$download/$tarball_name
fi
mkdir -p "$repo/repo"
rm -rf "$repo/repo/dists" "$repo/repo/pool"
tar -xzf "$tarball" -C "$repo"
# A fresh Termux has neither directory.
mkdir -p "$PREFIX/etc/apt/sources.list.d" "$PREFIX/etc/apt/preferences.d"
# trusted=yes because this index is not signed; the tarball's checksum is the only check.
printf 'deb [trusted=yes] file://%s livecd main\n' "$repo/repo" > "$PREFIX/etc/apt/sources.list.d/livecd.list"
# Our builds carry the Android patches, so a same-named package from Termux's mirrors must not
# replace them, even at a newer version. Libraries the builder compiled along the way, such as
# libexpat, are not pinned: Termux's newer releases of those win, and ours remain a fallback.
ours=$(for recipe in "$repo"/packages/*/; do
    basename "$recipe"
    for subpackage in "$recipe"*.subpackage.sh; do
        if test -e "$subpackage"; then basename "$subpackage" .subpackage.sh; fi
    done
done | tr '\n' ' ')
printf 'Package: %s\nPin: release n=livecd\nPin-Priority: 1001\n' "$ours" > "$PREFIX/etc/apt/preferences.d/livecd"
# Keep existing configuration files rather than stop at dpkg's question, and let the pin
# replace a newer Termux build of one of our packages.
apt=(apt-get -y --allow-downgrades -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
apt-get update
# Termux supports only whole upgrades: new packages link against libraries, such as libc++,
# that are newer than a fresh bootstrap's. This also finishes an earlier interrupted run.
"${apt[@]}" --fix-broken full-upgrade
dpkg --configure -a
"${apt[@]}" install x11-repo
apt-get update
# An on-device UPower build holds upower, which would stop livecd-upower replacing it.
if dpkg -s upower >/dev/null 2>&1; then apt-mark unhold upower; fi
mapfile -t packages < "$repo/src/native/packages.txt"
"${apt[@]}" install --no-install-recommends "${packages[@]}"
# Runtime code is owned by livecd-desktop. Setup only connects per-user paths.
python "$PREFIX/libexec/livecd-native/runtime.py"
if ! test -f "$HOME/.local/lib/livecd/config.json"; then
    printf '{}\n' > "$HOME/.local/lib/livecd/config.json"
    chmod 600 "$HOME/.local/lib/livecd/config.json"
fi
python "$repo/src/apply-overlays.py" --default "$@"
# Qualcomm GPUs get Mesa's Turnip driver, and the desktop then renders through Zink.
# `livecd start --renderer software` remains available, and a saved choice is kept.
if test -e /dev/kgsl-3d0 && python "$repo/prebuilt/turnip/gpu-setup.py" > "$state/gpu-setup.log"; then
    python - "$HOME/.local/lib/livecd/config.json" <<'EOF'
import json, sys
path = sys.argv[1]
with open(path) as file:
    config = json.load(file)
config.setdefault('native_renderer', 'zink')
with open(path, 'w') as file:
    json.dump(config, file)
EOF
else
    echo 'No supported GPU driver was set up; the desktop renders in software.'
fi
ln -sf "$repo/src/livecd-pkg" "$PREFIX/bin/livecd-pkg"
python "$base/audit.py" > "$state/elf-audit.json"
dpkg-query -W > "$state/host-packages.tsv"
printf '\nNative GNOME installed. Start: livecd start\n'
printf 'Validate: livecd validate; stop: livecd stop\n'
printf 'Optional applications: livecd-pkg list\n'
