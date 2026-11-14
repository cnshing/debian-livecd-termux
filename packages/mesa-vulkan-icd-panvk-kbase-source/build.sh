# Side-by-side candidate: no overlay selects it until desktop qualification.
source "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/../mesa-vulkan-icd-panvk-kbase/build.sh"
TERMUX_PKG_DESCRIPTION="Source-built PanVK qualification driver for Bionic and glibc; selected explicitly"
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
_PANVK_INSTALL_NAME=panvk-kbase-source
_PANVK_ICD_API_VERSION=1.3.363
_PANVK_SOURCE_LOCK="$(dirname "$(realpath "${BASH_SOURCE[0]}")")/source.lock.json"
# The immutable release assets and their SHA-256 are recorded together with
# the reconstructed source tree and Actions run, and installed as SOURCE.json.
read -r _RELEASE _BIONIC_SHA256 _GLIBC_SHA256 < <(python3 -c '
import json,sys
p=json.load(open(sys.argv[1]))
print(p["release"], p["bionic_sha256"], p["glibc_sha256"])
' "$_PANVK_SOURCE_LOCK")
