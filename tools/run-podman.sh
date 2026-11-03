#!/usr/bin/env bash
# Rootless Podman equivalent of the pinned builder's Docker entry point.
set -euo pipefail
checkout=$(realpath "${1:?Usage: run-podman.sh CHECKOUT COMMAND...}")
shift
cache=${LIVECD_PODMAN_BUILD_ROOT:-$HOME/.cache/livecd-podman-build}
mkdir -p "$cache/work" "$cache/data"
cache=$(realpath "$cache")
image=${TERMUX_BUILDER_IMAGE_NAME:?The package build script supplies the pinned image}
container="livecd-termux-$(id -u)-$$"
# Map the image's builder account to the invoking user. Cache/output files retain
# host ownership; no recursive chown or host pid_max/AppArmor changes are needed.
exec podman run --rm --init --name "$container" \
    --userns=keep-id:uid=1001,gid=1001 --user 1001:1001 \
    --cap-add SYS_PTRACE --cap-add SYS_ADMIN --device /dev/fuse \
    --security-opt "seccomp=$checkout/scripts/profile.json" \
    --volume "$checkout:/home/builder/termux-packages:Z" \
    --volume "$cache/work:/home/builder/.termux-build:Z" \
    --volume "$cache/data:/data:Z" \
    --workdir /home/builder/termux-packages --env HOME=/home/builder \
    --env "TERMUX_PKG_MAKE_PROCESSES=${TERMUX_PKG_MAKE_PROCESSES:-${JOBS:-2}}" \
    --shm-size 1g --entrypoint /bin/bash "$image" -c 'exec "$@"' livecd-build "$@"
