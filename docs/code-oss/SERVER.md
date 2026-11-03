# Building the matching SSH server

Run [the builder](../../tools/build-code-oss-server.sh) in native Termux, with the
same `code-oss` package you use as the SSH client. It reads the installed editor's
commit and builds that exact source, including Termux's Open VSX gallery and
signature-verification patches. No commit rewriting is needed.

The targets describe the **remote machine**, independently of the phone:

| Target | Remote system | Native compiler target |
| --- | --- | --- |
| `x64` | Linux x86_64, glibc | `x86_64-linux-gnu.2.28` |
| `arm64` | Linux AArch64, glibc | `aarch64-linux-gnu.2.28` |

These are the two glibc Linux server architectures in this editor's upstream
build. ARM32, i686, Alpine/musl, macOS, Windows and Android server runtimes are
not implemented by this script. The ARM64 archive is for a Linux remote host;
it does not run directly on Android/Bionic.

## Build

```sh
pkg install code-oss git nodejs-lts npm python rsync curl tar xz-utils zig
bash tools/build-code-oss-server.sh all
# Or select one target; running without arguments preserves the original x64 default.
bash tools/build-code-oss-server.sh arm64
```

`aarch64` and `x86_64` are accepted aliases. An unsupported target fails before
downloading or changing the build tree.

The default work directory is `~/.cache/code-oss-server`. Source, the JavaScript
bundle and downloaded dependencies are reused. Node downloads are keyed by
version; dependency installations and native compiler work are separated by
editor commit and target. Interrupted downloads and incomplete dependency
installations are retried. A lock prevents concurrent builds sharing this directory.

To use another directory, set `CODE_OSS_SERVER_WORK` to it. `CODE_OSS_APP` can
point at an extracted Termux editor's `resources/app` directory, and `PYTHON`
selects the Python executable. The extracted app must include its compiled
built-in extensions and `product.json`.

The output is:

```text
~/.cache/code-oss-server/code-oss-server-linux-x64.tar.gz
~/.cache/code-oss-server/code-oss-server-linux-x64.tar.gz.sha256
~/.cache/code-oss-server/code-oss-server-linux-arm64.tar.gz
~/.cache/code-oss-server/code-oss-server-linux-arm64.tar.gz.sha256
```

Each archive contains one top-level directory. Its `build-info.json` records the
editor commit, version, target, Node version, remote dependency lock hash and
Termux patch revision. The builder verifies Node's published SHA-256 and uses
npm's lockfile integrity checks. It compiles `node-pty`, `native-watchdog`,
`spdlog` and SQLite with Zig, retains target-specific Parcel watcher and Koffi
prebuilds, and rejects a stage containing ELF files for another architecture.
Linux uses JavaScript implementations of `deviceid` and `fs-copyfile`; those
packages do not need Linux addons.

Rebuild after every editor update. Archive names are stable, so retain builds
for different commits in separate directories when hosting them.

## Use with Open Remote - SSH

**These archives are not published anywhere,** so the remote machine has to get one from you. The simplest way needs no
settings. Without one of the methods here, connecting fails with `ERROR 404` from a VSCodium URL. Copy the archive to the
remote machine, and unpack it where the extension's install script looks, which then skips its download. A real
connection was made this way:

```sh
COMMIT=2c33b50b16c472efe58357d1d2a8a5414bc23fbf   # The commit in the archive's build-info.json
mkdir -p ~/.vscode-server-oss/bin/$COMMIT
tar -xzf code-oss-server-linux-x64.tar.gz -C ~/.vscode-server-oss/bin/$COMMIT --strip-components=1
```

After an editor update, its new commit needs a new server in a new folder. The old folder can then be deleted.

Or let the extension download it. [The tests](VERIFICATION.md#the-server) copy the archive to the remote machine, and have
it serve the archive to itself while connecting:

```sh
python3 -m http.server 18088 --bind 127.0.0.1 --directory DIRECTORY-WITH-THE-ARCHIVE
```

```json
{
  "remote.SSH.serverDownloadUrlTemplate": "http://127.0.0.1:18088/code-oss-server-${os}-${arch}.tar.gz",
  "remote.SSH.serverValidation": "strict"
}
```

Stop it once connected. The URL is seen from the remote machine, not the phone. Or host them yourself, with a directory
for each editor commit, untested:

```json
{
  "remote.SSH.serverDownloadUrlTemplate": "https://YOUR-HOST/servers/${commit}/code-oss-server-${os}-${arch}.tar.gz",
  "remote.SSH.serverValidation": "strict"
}
```

Replace `YOUR-HOST` with your host; keep the `${...}` variables. The extension
substitutes the editor commit and remote OS/architecture. It downloads and
extracts the archive, then runs `bin/code-server-oss`. A different editor commit
must fail strict validation. These archives have not been published to a release.

For a manual check on the matching Linux machine:

```sh
sha256sum -c code-oss-server-linux-arm64.tar.gz.sha256
tar -xzf code-oss-server-linux-arm64.tar.gz
./code-oss-server-linux-arm64/bin/code-server-oss --version
./code-oss-server-linux-arm64/node tests/code-oss/server-smoke.cjs ./code-oss-server-linux-arm64
```

The smoke test needs this checkout's test file. It checks actual log writes,
SQLite FTS5 queries, file-watch events, a PTY shell, file copying and Koffi's libc
binding, as well as runtime identity and loading the signature verifier/watchdog.
ARM64 can also be checked under `qemu-aarch64 -L SYSROOT` on an x86_64 Linux host.

The phone-side integration test uses a private display and scratch profile:

```sh
python tests/code-oss/test-code-oss.py --remote-only \
  --ssh-config CONFIG --ssh-host HOST --ssh-path /absolute/new/scratch-folder \
  --server-url 'http://127.0.0.1:18088/code-oss-server-${os}-${arch}.tar.gz'
```

The SSH scratch path must not exist, and is deleted afterwards. The test installs a probe extension and Git Graph only
in that scratch server, and stops the server afterwards. It checks remote extension execution, file search, terminal
and task output, in addition to the SSH FS checks. Validation is always strict. It does not sign in to GitHub or
Microsoft. See [verification](VERIFICATION.md#the-server) for results.

## Remaining limits

**x86_64 has been connected to from the editor. ARM64 has only passed its runtime checks under emulation.**
Running `bin/code-server-oss` directly, such as for `--version`, creates empty folders in `~/.vscode-server-oss`.
Each extension the server installs leaves a `/tmp/ovsx-*` folder holding Open VSX's public key.
The Copilot runtime is 164 MB of the 433 MB unpacked server. Nothing here uses it, and Termux removes it from the editor.
Kerberos proxy authentication is not built. ARM64 omits the x64-only Microsoft
authentication broker, matching upstream's extension build. The bundled
`@vscode/sandbox-runtime` version ships only an x64 seccomp helper; that helper
is removed from ARM64. Authentication and agent/sandbox features have not been
validated by the server checks.
