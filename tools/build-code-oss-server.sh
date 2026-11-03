#!/data/data/com.termux/files/usr/bin/bash
# Build Open Remote - SSH servers for Linux/glibc, in native Termux.
# Usage: bash tools/build-code-oss-server.sh [x64|arm64|all ...] (default: x64)
# Needs code-oss, git, nodejs-lts, python, rsync, curl, tar, xz-utils and zig.
# A server only accepts an editor at
# its own commit, so this reads the installed editor's: rerun it whenever code-oss updates.
# Finished steps are kept and skipped, under ~/.cache/code-oss-server. See docs/code-oss.
set -euo pipefail
work=${CODE_OSS_SERVER_WORK:-$HOME/.cache/code-oss-server}
app=${CODE_OSS_APP:-${PREFIX:-/usr}/lib/code-oss/resources/app}
python=${PYTHON:-python}
step() { echo "== $(date +%T) $*"; }
die() { echo "$*" >&2; exit 1; }
usage() {
    echo 'Usage: bash tools/build-code-oss-server.sh [x64|arm64|all ...]'
    echo 'Targets are remote Linux/glibc machines, independent of the Termux build host.'
}
arches=()
for arch in "${@:-x64}"; do
    case "$arch" in
        x64|x86_64|linux-x64) arch=x64;;
        arm64|aarch64|linux-arm64) arch=arm64;;
        all) arches=(x64 arm64); continue;;
        -h|--help) usage; exit 0;;
        *) usage >&2; die "Unsupported server architecture: $arch (supported: x64, arm64)";;
    esac
    if [[ " ${arches[*]} " != *" $arch "* ]]; then arches+=("$arch"); fi
done
for tool in "$python" git node npm rsync curl tar xz zig; do
    command -v "$tool" >/dev/null || die "Missing build tool: $tool"
done
[ -f "$app/product.json" ] && [ -d "$app/extensions" ] || die "Install Termux code-oss, or set CODE_OSS_APP to its resources/app directory"
# Absolute paths also work after changing into the source tree.
mkdir -p "$work"
work=$(cd "$work" && pwd)
app=$(cd "$app" && pwd)
# Prevent simultaneous targets from changing the shared checkout or lockfile.
if ! mkdir "$work/.build-lock" 2>/dev/null; then
    die "Build already running in $work (remove .build-lock only if that build has stopped)"
fi
trap 'rmdir "$work/.build-lock"' EXIT
# Use the same upstream patch revision as the package builder.
build_config=$(dirname -- "${BASH_SOURCE[0]}")/termux-build.json
termux_packages=$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$build_config")
commit=$("$python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$app/product.json")
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || die "Invalid editor commit: $commit"

step "Source at $commit"
mkdir -p "$work/patches"
if [ "$(git -C "$work/src" rev-parse HEAD 2>/dev/null)" != "$commit" ]; then
    rm -rf "$work/src"
    git init -q "$work/src"
    git -C "$work/src" remote add origin https://github.com/microsoft/vscode.git
    git -C "$work/src" fetch -q --depth 1 origin "$commit"
    git -C "$work/src" -c advice.detachedHead=false checkout -q FETCH_HEAD
fi
cd "$work/src"
# Termux's editor has both, so its server must find extensions in the same place and check them the same way.
for patch in 0003-use-open-vsx.org-as-extensions-gallery 0009-openvsx-extension-signature; do
    patch_file=$work/patches/$termux_packages-$patch.patch
    curl -fsSL --retry 3 "https://raw.githubusercontent.com/termux/termux-packages/$termux_packages/x11-packages/code-oss/$patch.patch" -o "$patch_file"
    if ! git apply --reverse --check "$patch_file" 2>/dev/null; then
        git apply --check "$patch_file"
        git apply --whitespace=nowarn "$patch_file"
        rm -rf out-vscode-reh-min
    fi
done

step 'Build dependencies, without running their install scripts'
export ELECTRON_SKIP_BINARY_DOWNLOAD=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 VSCODE_SKIP_NODE_VERSION_CHECK=1 DISABLE_V8_COMPILE_CACHE=1
[ -d node_modules ] || npm ci --ignore-scripts --no-audit --no-fund
[ -d build/node_modules ] || npm --prefix build ci --ignore-scripts --no-audit --no-fund
if [ "$(node -p "require('./remote/package.json').dependencies['node-ovsx-sign']")" != 1.2.0 ]; then
    npm --prefix remote pkg set dependencies.node-ovsx-sign=1.2.0
    npm --prefix remote install --package-lock-only --ignore-scripts --no-audit --no-fund
fi

step 'Server bundle'
[ -f out-vscode-reh-min/server-main.js ] || node --max-old-space-size=6144 build/next/index.ts bundle \
    --out out-vscode-reh-min --target server --minify --mangle-privates --nls

node_version=$(sed -n 's/^target="\(.*\)"$/\1/p' remote/.npmrc)
[[ "$node_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Cannot read the server Node.js version from remote/.npmrc'
deps_hash=$(sha256sum remote/package-lock.json | cut -d' ' -f1)
for arch in "${arches[@]}"; do
name=code-oss-server-linux-$arch
case "$arch" in
    x64) target=x86_64-linux-gnu.2.28;;
    arm64) target=aarch64-linux-gnu.2.28;;
esac
target_work=$work/targets/$commit/linux-$arch
node_work=$work/node/v$node_version/linux-$arch
stage=$work/stage/$name
mkdir -p "$target_work" "$node_work"

step "$arch Node.js $node_version, checked against its published hash"
tarball=node-v$node_version-linux-$arch.tar.xz
(
    cd "$node_work"
    if [ ! -f "$tarball" ]; then
        curl -fsSL --retry 3 "https://nodejs.org/dist/v$node_version/$tarball" -o "$tarball.part"
        mv "$tarball.part" "$tarball"
    fi
    curl -fsSL --retry 3 "https://nodejs.org/dist/v$node_version/SHASUMS256.txt" -o SHASUMS256.txt
    grep "  $tarball\$" SHASUMS256.txt | sha256sum -c -
    # Always extract the verified input, including after an interrupted extraction.
    mkdir -p node
    tar -xJf "$tarball" -C node --strip-components=1
)

step "$arch server dependencies, using npm's lockfile integrity checks"
deps=$target_work/deps
if [ "$(cat "$deps/.complete" 2>/dev/null || true)" != "$deps_hash" ]; then
    mkdir -p "$deps"
    cp remote/package.json remote/package-lock.json "$deps/"
    # npm 11 selects optional Linux packages even when npm itself runs on Android.
    # No install scripts or target executables run on the build host.
    npm --prefix "$deps" ci --ignore-scripts --no-audit --no-fund --os=linux --cpu="$arch" --libc=glibc
    printf '%s\n' "$deps_hash" > "$deps/.complete"
fi

step "$arch stage"
rm -rf "$stage"
mkdir -p "$stage/bin/helpers" "$stage/bin/remote-cli"
rsync -a --exclude='*.map' out-vscode-reh-min/ "$stage/out/"
rsync -a --exclude='*.map' --exclude='test/' --exclude='tests/' "$deps/node_modules/" "$stage/node_modules/"
cp LICENSE.txt "$stage/LICENSE"
cp ThirdPartyNotices.txt "$stage/ThirdPartyNotices.txt"
cp "$node_work/node/bin/node" "$stage/node"
cp resources/server/bin/code-server-linux.sh "$stage/bin/code-server-oss"
cp resources/server/bin/helpers/check-requirements-linux.sh "$stage/bin/helpers/check-requirements.sh"
for pair in remote-cli/code-linux.sh:remote-cli/code-oss helpers/browser-linux.sh:helpers/browser.sh; do
    sed -e "s/@@VERSION@@/$(node -p "require('./package.json').version")/g" -e "s/@@COMMIT@@/$commit/g" -e 's/@@APPNAME@@/code-oss/g' \
        "resources/server/bin/${pair%%:*}" > "$stage/bin/${pair##*:}"
done
chmod +x "$stage"/bin/code-server-oss "$stage"/bin/helpers/* "$stage"/bin/remote-cli/*

find "$stage/node_modules/@vscode/ripgrep-universal/bin" -mindepth 1 -maxdepth 1 ! -name "linux-$arch" -exec rm -rf {} +

"$python" - "$stage" "$app" "$commit" "$arch" "$node_version" "$deps_hash" "$termux_packages" <<'EOF'
# Manifests as build/gulpfile.reh.ts writes them, and the built-in extensions a server ships.
# The installed editor's are this commit's, already compiled. A server skips UI extensions.
import hashlib, json, shutil, sys
from pathlib import Path
stage, app = map(Path, sys.argv[1:3])
commit, arch, node_version, deps_hash, termux_packages = sys.argv[3:]
version = json.load(open('package.json'))['version']
product = json.load(open('product.json'))
nls = Path('out-vscode-reh-min')
product.update(commit=commit, version=version, date=(nls / 'date').read_text().strip(), nlsMetadataHash=hashlib.sha256(
    commit.encode() + b'\0' + (nls / 'nls.keys.json').read_bytes() + b'\0' + (nls / 'nls.messages.json').read_bytes()).hexdigest())
(stage / 'product.json').write_text(json.dumps(product, indent='\t'))
package = json.load(open('remote/package.json'))
package.update(name=product['nameShort'], version=version, type='module')
package.pop('dependencies', None)
package.pop('optionalDependencies', None)
(stage / 'package.json').write_text(json.dumps(package, indent='\t'))

def is_ui(manifest):
    kind = manifest.get('extensionKind')
    if kind in ('ui', 'workspace'):
        return kind == 'ui'
    contributes = manifest.get('contributes') or {}
    return not manifest.get('main') and not {'debuggers', 'jsonValidation'} & set(contributes)

kept = 0
for source in (app / 'extensions').iterdir():
    manifest = source / 'package.json'
    if source.name == 'node_modules' or (manifest.exists() and not is_ui(json.loads(manifest.read_text()))):
        shutil.copytree(source, stage / 'extensions' / source.name, symlinks=True)
        kept += 1
print('Built-in extensions kept:', kept)

# Universal npm packages can carry extra platforms even after npm's target selection.
for parent in list(stage.rglob('prebuilds')):
    if parent.is_dir():
        for child in parent.iterdir():
            if child.is_dir() and child.name != f'linux-{arch}':
                shutil.rmtree(child)
# The ARM64 Copilot SDK also bundles x64 ripgrep and tgrep executables.
for parent in list((stage / 'node_modules').rglob('bin')):
    if parent.is_dir():
        for child in parent.iterdir():
            if child.is_dir() and child.name.startswith(('linux-', 'darwin-', 'win32-')) and child.name != f'linux-{arch}':
                shutil.rmtree(child)
for child in (stage / 'node_modules/@parcel').glob('watcher-*'):
    if child.name != f'watcher-linux-{arch}-glibc':
        shutil.rmtree(child)
for parent in (stage / 'node_modules/@vscode/sandbox-runtime').rglob('seccomp'):
    for child in parent.iterdir():
        if child.is_dir() and child.name != arch:
            shutil.rmtree(child)
# Upstream's MSAL broker only ships Linux x64. ARM64 uses its JS authentication path.
if arch != 'x64':
    auth = stage / 'extensions/microsoft-authentication/dist'
    for pattern in ('*msal*.node', '*msal*.so'):
        for file in auth.glob(pattern):
            file.unlink()
(stage / 'build-info.json').write_text(json.dumps(dict(
    commit=commit, version=version, platform='linux', arch=arch, libc='glibc',
    nodeVersion=node_version, remoteLockSha256=deps_hash, termuxPackagesCommit=termux_packages,
), indent=2) + '\n')
EOF

step "$arch native addons, cross-compiled"
# As node-gyp would, for code that throws C++ exceptions through node-addon-api. No sanitizers:
# zig otherwise adds some that trap. kerberos is left out: only proxy authentication loads it.
addon_flags=(-target "$target" -fPIC -O2 -fno-sanitize=all -fstack-protector-strong -D_LARGEFILE_SOURCE -D_FILE_OFFSET_BITS=64)
addon_includes=(-I"$node_work/node/include/node" -I"$deps/node_modules/node-addon-api")
addon() { # NAME MODULE [zig c++ arguments...]
    local name=$1 module=$stage/node_modules/$2
    shift 2
    mkdir -p "$module/build/Release"
    (cd "$module" && zig c++ "${addon_flags[@]}" "${addon_includes[@]}" -std=gnu++20 -fexceptions -shared \
        -DBUILDING_NODE_EXTENSION -DNAPI_CPP_EXCEPTIONS "-DNODE_GYP_MODULE_NAME=$name" "$@" -o "build/Release/$name.node")
    echo "Built $name"
}
addon pty node-pty src/unix/pty.cc -lutil
addon watchdog @vscode/native-watchdog src/watchdog.cc -lpthread
addon spdlog @vscode/spdlog -DNODE_API_SWALLOW_UNTHROWABLE_EXCEPTIONS -DFMT_CONSTEVAL= -Ideps/spdlog/include src/main.cc src/logger.cc -lpthread
sqlite=$stage/node_modules/@vscode/sqlite3
tar -xzf "$sqlite/deps/sqlite-autoconf-3390400.tar.gz" -C "$target_work"
zig cc "${addon_flags[@]}" -D_REENTRANT=1 -DSQLITE_THREADSAFE=1 -DHAVE_USLEEP=1 -DSQLITE_ENABLE_FTS3 -DSQLITE_ENABLE_FTS4 -DSQLITE_ENABLE_FTS5 \
    -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_DBSTAT_VTAB=1 -DSQLITE_ENABLE_MATH_FUNCTIONS -c "$target_work/sqlite-autoconf-3390400/sqlite3.c" -o "$target_work/sqlite3.o"
addon vscode-sqlite3 @vscode/sqlite3 -DNODE_API_SWALLOW_UNTHROWABLE_EXCEPTIONS -I"$target_work/sqlite-autoconf-3390400" \
    src/backup.cc src/database.cc src/node_sqlite3.cc src/statement.cc "$target_work/sqlite3.o" -lpthread -ldl -lm

step "$arch architecture audit"
"$python" - "$stage" "$arch" <<'EOF'
import sys
from pathlib import Path
stage, arch = Path(sys.argv[1]), sys.argv[2]
machine = {'x64': 62, 'arm64': 183}[arch]
count = 0
for file in stage.rglob('*'):
    if not file.is_file() or file.is_symlink():
        continue
    with file.open('rb') as stream:
        header = stream.read(20)
    if header[:4] == b'\x7fELF':
        actual = int.from_bytes(header[18:20], 'little' if header[5] == 1 else 'big')
        if actual != machine:
            raise SystemExit(f'Wrong ELF architecture ({actual}, expected {machine}): {file}')
        count += 1
print(f'{count} ELF files checked for linux-{arch}')
for required in (f'node_modules/@parcel/watcher-linux-{arch}-glibc/watcher.node',
                 f'node_modules/@vscode/ripgrep-universal/bin/linux-{arch}/rg'):
    if not (stage / required).is_file():
        raise SystemExit(f'Missing target dependency: {required}')
EOF

step "$arch package"
tar -czf "$work/$name.tar.gz.part" -C "$work/stage" "$name"
mv "$work/$name.tar.gz.part" "$work/$name.tar.gz"
(cd "$work" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
ls -l "$work/$name.tar.gz"
cat "$work/$name.tar.gz.sha256"
done
step "Done: a server for commit $commit"
