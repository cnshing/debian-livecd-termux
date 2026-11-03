# Code OSS device verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

Tested on the established rig: Galaxy Note10+ (SM-N975U1), Android 11,
arm64, over USB. **This covers one phone and one PC, with no GitHub account signed in.** Everything ran on
a private Xvfb display with its own session bus and scratch data, under the desktop's environment. The live
desktop was stopped, and nothing was shown on the phone's screen, so touch input and Termux:X11 are untested.

| Component | Version |
| --- | --- |
| Code OSS, Electron | 1.144.0 (commit `2c33b50b`), 43.7.11, official Termux |
| gnome-keyring, gcr, libsecret | 51.1, 3.41.2, 0.21.8.2, official Termux |
| git, gh | 2.56.0, 2.103.3, official Termux |
| Pull Requests, Actions | `GitHub.vscode-pull-request-github` 0.174.0, `GitHub.vscode-github-actions` 0.32.3 |
| GitLens, Git Graph | `eamodio.gitlens` 19.5.0, `mhutchie.git-graph` 1.30.0 |
| SSH | `jeanp413.open-remote-ssh` 0.5.1, `Kelvin.vscode-sshfs` 1.27.0 |

Installing added only packages, with no upgrades or removals. The other machine was this project's PC, x86_64,
through a private `sshd`: loopback only, with a throwaway key, reached from the phone with `adb reverse`. Its
hostname is replaced by `dev-pc` in the results (`temp/docs/evidence/code-oss/result.json`).

## Results

[`test-code-oss.py`](../../tests/code-oss/test-code-oss.py) passed **42 of 42**, twice, on the final files: with no
resource preload (results (`temp/docs/evidence/code-oss/result.json`)) and with [its fixed library](#resource-preload)
(results (`temp/docs/evidence/code-oss/result-fixed-preload.json`)). Earlier runs of it stopped on the [problems below](#found-by-running-it),
so these are not the only attempts. Both used a short scratch runtime folder, which [hid a real failure](#found-by-running-it).
After fixing that, the local checks passed **27 of 27** with a session-length one (results (`temp/docs/evidence/code-oss/result-session-runtime.json`)).
The SSH checks were not repeated: under the new launcher, the editor's own path is about as short as it was. It reads what happened, such as a file written by a terminal, rather than what the
window says. Other checks were one-off: device checks (`temp/docs/evidence/code-oss/device-checks.txt`).

| Check | Result |
| --- | --- |
| Identity | Bionic, no tracer, no PRoot. 9 processes, all carrying the environment `livecd stop` looks for |
| Startup | The window opens in about 6 s to 8 s, with nothing else running |
| Extensions | All six install from Open VSX with `Signature is valid`. The PR extension activates, with no proposed-API refusals |
| Terminal, task | Run native tools, with `termux-exec` preloaded |
| Git | A commit from the editor runs a hook with an `env` shebang |
| Secrets | Keyring prompt, then stored. On disk it is encrypted (`v11`) and the value is absent |
| Secrets, restarting | Read back after restarting the editor, and after a new session bus and unlocking |
| Keyring lifetime | The daemon ends with its session bus. Nothing was left running |
| Keyring dialog | Shell's own dialog under GNOME Shell, `gcr-prompter` without it. Screenshot (`temp/docs/evidence/code-oss/keyring-prompt-gnome-shell.png`) |
| Launcher | Shell's tracker assigns the window to `code-oss.desktop`, with its own icon |
| URL handler | `gio open code-oss://…` reaches the running editor, which asks first. Screenshot (`temp/docs/evidence/code-oss/url-prompt.png`) |
| SSH FS | Lists, edits and saves a remote file, and its terminal and task ran on the PC. Screenshot (`temp/docs/evidence/code-oss/ssh-fs.png`) |
| Open Remote - SSH, through a relay | Authenticates and reaches its server step using only a stand-in relay command |
| **Server connection** | The phone's Bionic editor connected to the [x86_64 glibc server](#the-server), downloaded and started by the extension, with strict validation. Screenshot (`temp/docs/evidence/code-oss/git-graph.png`) |
| Remote extension | A workspace extension ran on the PC, reporting its hostname, `linux` and `x64`, and its `findFiles` call found a file |
| Remote terminal, task | Both ran on the PC |
| Open VSX on the server | The server installed Git Graph with `Signature is valid`. It ran there and drew its view on the phone, showing the fixture's commit |
| Built-in extensions on the server | `vscode.git` and others activated, with no errors logged (`temp/docs/evidence/code-oss/remote-extension-host-activations.txt`) |
| Cleaning up | The server stopped and its scratch folder was removed. Signature checks leave a `/tmp/ovsx-*` folder holding Open VSX's public key |

## Not tested

- **GitHub.** The user chose to skip signing in, so none of these has happened: `gh` login, HTTPS push
  through its helper, device-code sign-in in the editor, listing a pull request, Settings Sync. That the PR extension
  activates does not show that it works. The login flow itself started correctly: `gh` obtained a device code.
- **A real relay service**, such as `cloudflared` or Tailscale. The relay check used `ssh -W` in its place.
- **Debuggers and language servers on the other machine**, and long-running use: each server session lasted minutes.
- **An ARM64 machine.** That server has only run under emulation: [see below](#the-server).
- **Automated runs of the real desktop session.** The test's rendering was software, with WebGL2 blocked. The user has
  confirmed by hand (`temp/docs/evidence/code-oss/device-checks.txt`) that the editor opens there under Zink, and connects over SSH to
  the PC's real `sshd` with a password. Claude Code's panel works in that window.
- **`livecd stop` itself.** The processes carry its marker, but it was not run with the editor open.
- GitHub Actions, GitLens and Git Graph were installed and loaded, and GitLens drew its commit graph, but
  they were otherwise not exercised. Nor were extension updates, or the OS proxy addon.

## Found by running it

- **The editor could not open in a real session.** Its main socket's path was 118 characters, over the 107 limit, because
  the session's `XDG_RUNTIME_DIR` is long. It exited with code 0 after 2 seconds, and nothing recorded a crash. The overlay's
  [launcher](../../overlays/Text%20Editor+Code%20OSS/filesystem/termux/home/.local/lib/livecd-native/bin/code-oss.overlay.tmpl)
  gives it a short link to the same folder. Details (`temp/docs/evidence/code-oss/device-checks.txt`).
- **Codex `26.1021.22027` cannot start its panel, with or without SSH.** A CPU profile puts 86% of a 52-second freeze in its own
  preload code, over a list of 3,203 files. This is [an upstream bug](https://github.com/openai/codex/issues/58398), not file access
  or SSH. Stable `26.908.40401` reached its sign-in screen in 11 seconds, twice, with nothing patched. Nothing past that screen
  was tried. Details (`temp/docs/evidence/code-oss/device-checks.txt`).
- **The assessment's window class was wrong.** It substituted `com.visualstudio.CodeOSS` from `product.json`,
  without running the editor. A real window reports `code-oss`, because the recipe's `code.mjs` renames the
  application. [The patch](termux-desktop-metadata.patch) is corrected.
- **Outside GNOME, the editor offers weaker encryption.** Without `password-store`, a secret waits on
  a dialog (`temp/docs/evidence/code-oss/weaker-encryption-dialog.png`) offering "Use weaker encryption". The overlay pins the backend.
- **The first secret lookup happens at startup,** so the keyring prompt appears about 5 s after opening. The
  PR extension waits for an answer before it activates.
- **SSH FS checks no host key.** It connected to a host it had never seen without asking, and its own code
  has no `known_hosts` handling or `hostVerifier`. Open Remote - SSH has both.
- **SSH FS has no file search.** The log says `No search provider registered for scheme: ssh`, so Go to File
  and Search are empty there.
- **Crash at launch, not explained.** The launcher dies with `SIGTRAP`, always at the same place, in about 1 launch
  in 50: 6 of 300 when measured. No preload is involved. The test retries and reports the count.
  Details (`temp/docs/evidence/code-oss/device-checks.txt`).
- **Some launches give no editor, with no crash.** Under rapid relaunching only, and the cause is not established.
  The test counts these too. Details (`temp/docs/evidence/code-oss/device-checks.txt`).
- **One run stopped unexplained.** A new session's unlock prompt never appeared, and the window's debugging connection
  had closed, with no crash logged. It did not recur in the next three complete runs. Details (`temp/docs/evidence/code-oss/device-checks.txt`).
- **Windows freeze behind a keyring prompt.** The main process waits for the answer.
- **The resource preload aborts Node.js.** [See below](#resource-preload).

## The server

Open Remote - SSH needs a server built from the editor's exact source, for
reasons shown here (`temp/docs/evidence/code-oss/server-compatibility.txt`). [`build-code-oss-server.sh`](../../tools/build-code-oss-server.sh)
builds one on the phone. Its use is in [SERVER.md](SERVER.md).

| | x86_64 | ARM64 |
| --- | --- | --- |
| Commit, Node.js, glibc floor | `2c33b50b`, 24.22.1, 2.28 | The same |
| Archive SHA-256 | `bd86b0d1…50881` | `12e318a2…2411e` |
| Runtime checks, [`server-smoke.cjs`](../../tests/code-oss/server-smoke.cjs) | 8 of 8, natively on the PC (`temp/docs/evidence/code-oss/server-smoke-x64.txt`) | 8 of 8, under QEMU (`temp/docs/evidence/code-oss/server-smoke-arm64.txt`) |
| Connected to from the editor | **Yes** | **No** |

The ARM64 result is emulation on an x86_64 PC, and no real ARM64 Linux machine has been used.

The server was reachable only through a private `sshd` and a web server, both on loopback, with a throwaway key.

## Resource preload

The earlier build of [`liblivecd-proc.so`](../resources/README.md) **aborts every Node.js program it is preloaded
into**, every time, with `Pointer tag for … was truncated`. That includes the editor's launcher, so the editor
never opens. `src/native/desktop.py` preloads it once it is installed. The phone's installed controller did not yet.

Building it with `-fno-emulated-tls` stops this, and the layer still answers `/proc/stat`. The exact mechanism is not
established. The evidence (`temp/docs/evidence/code-oss/preload-abort.txt`) has the frames and the variants tried.

The recipe now has that flag, which needs Android 10. **The library installed on the phone was left as it was.** The
fixed run above used a scratch build of the same source, preloaded by setting `LD_PRELOAD`. Only `code-oss` and `node`
were tried under the fix.

## Reproduce

In native Termux, with the desktop stopped, from this checkout:

```sh
python src/apply-overlays.py "Text Editor+Code OSS"
# Set this while the installed resource library is older than the fix.
export LIVECD_RESOURCES_COMPAT=0
python tests/code-oss/test-code-oss.py

# Also on another machine over SSH. The folder must not exist: the test deletes it afterwards.
python tests/code-oss/test-code-oss.py --ssh-config CONFIG --ssh-host HOST --ssh-path /tmp/scratch-folder \
  --server-url 'http://127.0.0.1:18088/code-oss-server-${os}-${arch}.tar.gz'
```

It needs `Xvfb`, `openbox`, `xdotool` and `xprop`, and uses the extensions the overlay installed. `--remote-only` skips
the local checks, and `--server-only` also skips SSH FS. The URL is seen from the other machine, which here served
the archive to itself on loopback: `python3 -m http.server 18088 --bind 127.0.0.1 --directory DIR`.
