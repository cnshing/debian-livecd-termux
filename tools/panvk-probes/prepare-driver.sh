#!/bin/bash
# Reconstruct the reviewed universal p0175 source. CI scratch checkout only.
set -euo pipefail
zenith=$(realpath "$1")
out=$(realpath -m "$2")
mkdir -p "$zenith/work/mesa" "$out"
mesa="$zenith/work/mesa"
# Seed a shallow repository: fetch-mesa.sh otherwise clones all Mesa history.
git -C "$mesa" init -q
git -C "$mesa" remote add origin https://gitlab.freedesktop.org/mesa/mesa.git
git -C "$mesa" config user.name 'PanVK research CI'
git -C "$mesa" config user.email 'panvk-ci@users.noreply.github.com'
bash "$zenith/scripts/fetch-mesa.sh"
bash "$zenith/scripts/prepare-rc5-tree.sh" --mesa "$mesa" --csf-max 233 --wip-max 0175
test "$(cat "$mesa/.panvk-patchlevel")" = p0175
{
  echo "zenith=$(git -C "$zenith" rev-parse HEAD)"
  echo 'mesa-base=5a07217f034b3e50d8c7c7794f97a2df1742613b'
  echo "reconstructed-commit=$(git -C "$mesa" rev-parse HEAD)"
  echo "reconstructed-tree=$(git -C "$mesa" rev-parse HEAD^{tree})"
  echo 'release-commit-label=795ca7ff3e8'
  echo 'patch-level=p0175'
  echo 'NOTE: prepare-rc5-tree creates timestamped commits. Its commit ID is not a reproducible source-content hash.'
  echo 'NOTE: release SOURCE.json provides no tree hash; matching the release label is not proof of content equivalence.'
} > "$out/SOURCE.txt"
git -C "$mesa" log --format='%h %s' > "$out/PATCHES.txt"
if [ "${PANVK_SKIP_ARCHIVE:-0}" != 1 ]; then
  tar -C "$zenith" -I 'zstd -T0' -cf "$out/prepared-source.tar.zst" work/mesa
fi
cat "$out/SOURCE.txt"
