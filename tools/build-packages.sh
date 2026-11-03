#!/usr/bin/env bash
# One Termux packaging path for native development builds and off-device builds.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
install_packages=false
continue_build=false
case ${1:-} in
    --install) install_packages=true; shift;;
    --continue) continue_build=true; shift;;
    --help|-h)
        printf 'Usage: bash tools/build-packages.sh [--install|--continue] PACKAGE...\n'
        printf 'Builds .debs with termux-packages. --install requires native Termux.\n'
        printf 'LIVECD_TERMUX_BUILDER can name an existing checkout at the pinned revision.\n'
        printf 'LIVECD_CONTAINER_ENGINE selects docker or podman (auto-detected by default).\n'
        exit 0;;
esac
test "$#" -gt 0 || { echo 'Name at least one package; see --help.' >&2; exit 2; }
python=${PYTHON:-python3}
native=false
if test "${PREFIX:-}" = /data/data/com.termux/files/usr; then native=true; fi
if $install_packages && ! $native; then
    echo '--install requires native Termux.' >&2; exit 2
fi
if ! $native; then
    engine=${LIVECD_CONTAINER_ENGINE:-}
    if test -z "$engine"; then
        if command -v docker >/dev/null; then engine=docker
        elif command -v podman >/dev/null; then engine=podman
        fi
    fi
    case "$engine" in docker|podman) ;; *) echo 'Off-device builds require Docker or Podman.' >&2; exit 2;; esac
    command -v "$engine" >/dev/null || { echo "Container engine not found: $engine" >&2; exit 2; }
    "$engine" info >/dev/null
fi
if $native; then
    export TERMUX_PKG_MAKE_PROCESSES=${TERMUX_PKG_MAKE_PROCESSES:-${JOBS:-2}}
    mkdir -p "$HOME/.local/state/livecd"
    exec 8>"$HOME/.local/state/livecd/session.lock"
    flock -n 8 || { echo 'Stop the managed desktop before building native packages.' >&2; exit 2; }
fi
# Validate package names and include this repository's dependencies before cloning.
ordered=$("$python" "$repo/tools/recipes.py" order "$@")
read -r -a packages <<< "$ordered"
revision=$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$repo/tools/termux-build.json")
repository=$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["repository"])' "$repo/tools/termux-build.json")
export TERMUX_BUILDER_IMAGE_NAME
TERMUX_BUILDER_IMAGE_NAME=$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["image"])' "$repo/tools/termux-build.json")
builder=${LIVECD_TERMUX_BUILDER:-$HOME/.cache/livecd-termux-builder}
mkdir -p "$(dirname -- "$builder")"
exec 9>"$builder.livecd.lock"
flock -n 9 || { echo 'This Termux builder is already in use.' >&2; exit 2; }
if ! test -d "$builder/.git"; then
    git clone --filter=blob:none --no-checkout "$repository" "$builder"
    git -C "$builder" checkout --detach "$revision"
fi
"$python" "$repo/tools/recipes.py" prepare "$builder"
case " ${packages[*]} " in
    *' chromium '*)
        recipe_version() { (set +u; source "$1"; printf '%s' "$TERMUX_PKG_VERSION"); }
        chromium_version=$(recipe_version "$builder/x11-packages/chromium/build.sh")
        host_tools_version=$(recipe_version "$builder/x11-packages/chromium-host-tools/build.sh")
        if test "$chromium_version" != "$host_tools_version"; then
            echo "Chromium $chromium_version does not match pinned host tools $host_tools_version." >&2
            exit 2
        fi;;
esac
cd "$builder"
build_flags=(-f -I)
if $continue_build; then build_flags+=(-c); fi
if $native; then
    ./build-package.sh "${build_flags[@]}" "${packages[@]}"
elif test "$engine" = podman; then
    "$repo/tools/run-podman.sh" "$builder" ./build-package.sh "${build_flags[@]}" -a aarch64 "${packages[@]}"
else
    ./scripts/run-docker.sh ./build-package.sh "${build_flags[@]}" -a aarch64 "${packages[@]}"
fi
if $install_packages; then
    case " ${packages[*]} " in
        *' livecd-upower '*)
            if dpkg -s upower >/dev/null 2>&1; then apt-mark unhold upower; fi;;
    esac
    "$python" "$repo/tools/recipes.py" install-output "$builder/output" "${packages[@]}"
fi
