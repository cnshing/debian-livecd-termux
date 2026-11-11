#!/data/data/com.termux/files/usr/bin/bash
# Entrypoint. Run in native Termux from a checkout of this repository:
#   bash install.sh [--repo-tarball FILE] [OPT-IN-OVERLAY...]
# It fetches the compiled packages from this project's latest GitHub release, unless
# --repo-tarball names a copy you already have, and unpacks them into a local apt repository.
# An offline tarball (livecd-termux-repo-aarch64-offline.tar.gz) also carries every Termux package,
# and apt then never contacts a mirror.
set -euo pipefail
test "${PREFIX:-}" = /data/data/com.termux/files/usr || { echo 'Run in native com.termux, outside PRoot.' >&2; exit 2; }
test "$(dpkg --print-architecture)" = aarch64 || { echo 'The pinned GNOME runtime requires aarch64.' >&2; exit 2; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$HOME/.local/state/livecd"
exec > >(tee -a "$HOME/.local/state/livecd/install.log") 2>&1
echo "=== install.sh $(date '+%F %T') $*"
trap 'echo "install.sh stopped at line $LINENO. The log is ~/.local/state/livecd/install.log." >&2' ERR
# Grant what Shizuku can, then report each feature whose Android app or permission is missing.
# Only a missing Termux:X11 stops the installation; the other features stay off until fixed.
preflight=0
bash "$repo/src/preflight.sh" --grant > "$HOME/.local/state/livecd/preflight.txt" || preflight=$?
cat "$HOME/.local/state/livecd/preflight.txt"
test "$preflight" = 0 || exit 2
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
# CI lists them in the tarball (tools/recipes.py pins), with the subpackages Termux's recipes add to
# ours. Older tarballs lack the list, so name the recipes here then.
if test -f "$repo/repo/pins"; then
    ours=$(tr '\n' ' ' < "$repo/repo/pins")
else
    ours=$(for recipe in "$repo"/packages/*/; do
        basename "$recipe"
        for subpackage in "$recipe"*.subpackage.sh; do
            if test -e "$subpackage"; then basename "$subpackage" .subpackage.sh; fi
        done
    done | tr '\n' ' ')
fi
printf 'Package: %s\nPin: release n=livecd\nPin-Priority: 1001\n' "$ours" > "$PREFIX/etc/apt/preferences.d/livecd"
# An offline tarball also holds, as suite termux, every Termux package the installation can need.
# apt, and every hook it starts, then reads only the two local suites, with a package list of their
# own, so no mirror is contacted and Termux's own sources and lists stay as they were.
offline=
if test -f "$repo/repo/dists/termux/Release"; then
    offline=$state/apt-offline
    mkdir -p "$offline/lists/partial" "$offline/sources.list.d"
    printf 'deb [trusted=yes] file://%s livecd main\ndeb [trusted=yes] file://%s termux main\n' \
        "$repo/repo" "$repo/repo" > "$offline/sources.list"
    printf 'Dir::Etc::SourceList "%s";\nDir::Etc::SourceParts "%s";\nDir::State::Lists "%s";\n' \
        "$offline/sources.list" "$offline/sources.list.d" "$offline/lists" > "$offline/apt.conf"
    export APT_CONFIG=$offline/apt.conf
    # Hooks leave out what only a network supplies, such as Google Chrome.
    export LIVECD_OFFLINE=1
    echo "Installing offline, from $repo/repo alone."
fi
# Keep existing configuration files rather than stop at dpkg's question, and let the pin
# replace a newer Termux build of one of our packages.
apt=(apt-get -y --allow-downgrades -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
apt-get update
# Termux's mirror picker can choose a mirror that stopped syncing; one served a ten-month-old index
# without packages this desktop needs. Use Termux's own server then, as termux-change-repo can.
index=$(ls "$PREFIX"/var/lib/apt/lists/*termux-main_dists_stable_*Release 2>/dev/null | head -n 1 || true)
if test -z "$offline" && test -n "$index" && test $(($(date +%s) - $(date -d "$(sed -n 's/^Date: //p' "$index")" +%s) )) -gt 1209600; then
    echo "The Termux mirror in $PREFIX/etc/apt/sources.list is out of date; using packages-cf.termux.dev."
    printf 'deb https://packages-cf.termux.dev/apt/termux-main stable main\n' > "$PREFIX/etc/apt/sources.list"
    apt-get update
fi
# Termux supports only whole upgrades: new packages link against libraries, such as libc++,
# that are newer than a fresh bootstrap's. This also finishes an earlier interrupted run.
"${apt[@]}" --fix-broken full-upgrade
dpkg --configure -a
"${apt[@]}" install x11-repo
apt-get update
# An on-device UPower build holds upower, which would stop android-upower replacing it.
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
# Earlier versions linked a livecd-pkg command here; pkg install replaces it.
rm -f "$PREFIX/bin/livecd-pkg"
python "$base/audit.py" > "$state/elf-audit.json"
dpkg-query -W > "$state/host-packages.tsv"
printf '\nNative GNOME installed. Start: livecd start\n'
printf 'Validate: livecd validate; stop: livecd stop\n'
printf "Optional applications: apt list '?archive(^livecd\$)', then pkg install NAME\n"
if test -n "$offline"; then
    printf 'Without a network, install them from the offline repository: APT_CONFIG=%s pkg install NAME\n' "$offline/apt.conf"
fi
# Repeat what the preflight found, which the package output has scrolled away.
if grep -q '^  WARN' "$common/preflight.txt"; then echo; cat "$common/preflight.txt"; fi
