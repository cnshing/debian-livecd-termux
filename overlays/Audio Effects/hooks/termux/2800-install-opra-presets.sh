#!/data/data/com.termux/files/usr/bin/bash
# Upstream's 2800-install-opra-presets hook: convert the OPRA headphone EQ database into EasyEffects
# presets (Harman targets), which EasyEffects lists under $XDG_DATA_DIRS/easyeffects/output/OPRA.
# Runs in the overlay's directory.
set -euo pipefail
source=https://opra.roonlabs.net/database_v1.jsonl # The mirror OPRA asks open-source users to use
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
curl -fsSL --retry 3 "$source" -o "$temporary/db.jsonl"
python lb/hooks/normal/scripts/opra2ee.py "$temporary/db.jsonl" "$PREFIX/share/easyeffects/output/OPRA"
