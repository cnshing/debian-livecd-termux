# Code OSS on native Termux

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

An **opt-in port**: Termux's own Code OSS 1.144.0 on Android/Bionic, with no PRoot, no root and no changes to
the editor, using extensions from Open VSX in place of Microsoft's. It appears in the
[native desktop](../native/README.md)'s menu. [Tested on one phone](VERIFICATION.md), connecting to one PC, with no GitHub
account signed in. Most checks ran on a private display. The real desktop and a real SSH login were confirmed by hand.

**Local work and both SSH routes work, including extensions running on the other machine.** Open Remote - SSH needs
[a server you build yourself](SERVER.md). Two things remain:

- **Remote Tunnels:** nothing on Open VSX replaces them.
- **GitHub sign-in:** never tried, so pull requests are unproven.

## Install

`install.sh` applies the `Text Editor+Code OSS` overlay by default. To apply it again, with the desktop
stopped, in native Termux, from this repository:

```sh
python src/apply-overlays.py "Text Editor+Code OSS"
```

This installs our `code-oss` recipe, its Open Remote - SSH extension, `git`, `gh` and `gnome-keyring`, and uses the profile wrapper. The recipe resolves the two menu-entry placeholders during packaging; the overlay no longer repairs installed package metadata. It never replaces an existing `~/.vscode-oss/argv.json` or settings file, so
if you ran Code OSS before this, copy the two settings from
[its `argv.json`](../../overlays/Text%20Editor+Code%20OSS/filesystem/termux/home-defaults/.vscode-oss/argv.json) into yours.

**Opening it the first time asks you to choose a keyring password.** Android has no login to unlock a keyring
with, so each new desktop session asks for it again. Your saved sign-ins depend on it, and it cannot be recovered.

## What replaces what

These were the most downloaded extensions on Open VSX for each feature when assessed
(details (`temp/docs/evidence/code-oss/extensions.json`)). All are from verified publishers and ship no native code for Linux or
Android.

Four are packages, pinned to the version tested here and installed as built-in extensions, so they need no network
and `pkg` updates them. `code-oss` recommends Open Remote - SSH, and `install.sh` installs it. The rest are optional:

```sh
pkg install code-oss-extension-vscode-sshfs code-oss-extension-vscode-pull-request-github code-oss-extension-vscode-github-actions
```

GitLens and Git Graph are not packaged, because their licenses do not allow redistributing them: Git Graph's grants no
right to distribute, and GitLens bundles GitKraken's "plus" code, which may not be distributed. Install them from the
Extensions view, which downloads them from Open VSX with signature checks.

| In VS Code | Here | Tested |
| --- | --- | --- |
| Editing, terminal, tasks, Git | Built in | **Yes** |
| GitHub pull requests and issues | GitHub Pull Requests (`code-oss-extension-vscode-pull-request-github`) | Installs and activates. Not signed in |
| GitHub Actions | GitHub Actions (`code-oss-extension-vscode-github-actions`) | Installs and loads |
| Git history, blame | GitLens, Git Graph, from the Extensions view | Installs and draws its graph. GitLens promotes its paid tier |
| Remote - SSH | Open Remote - SSH (`code-oss-extension-open-remote-ssh`, installed) | **Yes**, with [a server you build](SERVER.md) |
| Remote files without a server | SSH FS (`code-oss-extension-vscode-sshfs`) | **Yes** |
| Remote Tunnels | **Nothing** | [See below](#remote-tunnels) |
| Settings Sync, Copilot | **Nothing** | Not available in this build |

Only two extensions get proposed APIs, named one by one in `~/.vscode-oss/argv.json`, and no signature checking is
turned off. Anything an extension runs natively still has to work on Android: this is covered in the assessment below.

## Working on another machine

| | SSH FS | Open Remote - SSH |
| --- | --- | --- |
| Needs on the other machine | Only an SSH server | [A server built for this exact editor](SERVER.md) |
| Editing, terminal, tasks | **Tested** | Terminal and tasks **tested** |
| The other machine's extensions | No | **Tested**. Debuggers and language servers were not tried |
| Go to File and Search | **No** | File search **tested** |
| Checks the host's key | **No** | Yes, by its source. Not tried with a wrong key |
| Honors `ProxyCommand` | No | Yes, tested with a stand-in (`temp/docs/evidence/code-oss/device-checks.txt`) |

**SSH FS does not verify who it connects to.** Someone able to intercept the connection could impersonate the
machine and collect what you send. Use it only on a network you trust, or inside a VPN or tunnel that
authenticates the other end. To set it up, add this to your settings, then open `ssh://dev/home/you/project`:

```json
"sshfs.configs": [{"name": "dev", "host": "HOST", "username": "YOU", "privateKeyPath": "/data/data/com.termux/files/home/.ssh/KEY"}]
```

**Open Remote - SSH needs its own server,** which runs on the other machine. A server refuses any editor whose commit
differs from its own. Termux's editor is at `2c33b50b`, and nothing suitable can be downloaded (`temp/docs/evidence/code-oss/server-compatibility.txt`):

- VSCodium's newest is 1.143.1. The extension's `serverValidation: "force"` rewrites the check, but cannot work here:
  1.144.0 renumbered the messages the two sides exchange. Do not use it across versions.
- Microsoft's server exists at this commit, but its license allows use "with each validly licensed copy of Microsoft
  Visual Studio Code". This editor is not one.

So [`build-code-oss-server.sh`](../../tools/build-code-oss-server.sh) builds one, on the phone, in about two minutes.
The phone's C library does not matter: the editor and server only exchange messages, so a Bionic editor works with
a glibc server. **Each editor update needs a rebuild,** because Termux's package is rolling. [How to build and use it](SERVER.md).

### Remote Tunnels

Nothing on Open VSX speaks Microsoft's tunnel protocol, and Microsoft's extension may only be used with Microsoft's
editor. Its [license says so](https://ms-vscode.gallery.vsassets.io/_apis/public/gallery/publisher/ms-vscode/extension/remote-server/1.6.2026092109/assetbyname/Microsoft.VisualStudio.Services.Content.License).

The nearest equivalent is **SSH over something that crosses networks**, such as Tailscale's Android app or Termux's
`cloudflared`. Open Remote - SSH reached a machine using only a relay command in
a stand-in test (`temp/docs/evidence/code-oss/device-checks.txt`), with a host name that could not resolve. No real relay service has been
tried, it needs that same server, and each service has its own account and trust model. Open VSX's Tailscale extension
was not tried, and Termux packages no `tailscale` command.

`vscode.dev` in a browser remains the working route to a real tunnel. It needs no part of this port.

## Other limits

- **Codex `26.1021.22027` says "Codex could not start",** with or without SSH. [An upstream bug](https://github.com/openai/codex/issues/58398)
  in that build preloads 3,203 files in a way that freezes its panel for longer than its 30-second limit here. **Install
  `26.908.40401` instead**, from the extension's gear menu, or on the remote machine with
  `~/.vscode-server-oss/bin/COMMIT/bin/code-server-oss --install-extension openai.chatgpt@26.908.40401 --force`. It reached the
  sign-in screen in 11 seconds, unpatched, and stays pinned, so it also gets no updates until you unpin it. A real sign-in
  was not tried. Details (`temp/docs/evidence/code-oss/device-checks.txt`).
- **The launcher crashes in about 1 launch in 50**, and the editor does not open. Try again. It was 6 of 300 when
  measured, and the cause is not known (`temp/docs/evidence/code-oss/device-checks.txt`).
- **Start it as `code-oss` from inside the desktop, or from the menu.** Both use this overlay's launcher, without which the
  editor exits at once and silently there. A terminal open since before installing must open a new one, or run `hash -r`.
- **The editor freezes while a keyring prompt is open,** until you answer it. Check for a prompt if it stops responding.
- **A `android-procfs` library built before the compatibility fix stops the editor from opening**, once the desktop controller
  preloads it, and stops every other Node.js program too. [Rebuild it](../resources/README.md), or set
  `ANDROID_PROCFS_COMPAT=0`. Details (`temp/docs/evidence/code-oss/preload-abort.txt`).
- Copilot's first-run prompt is turned off with `chat.disableAIFeatures`, since this build has no Copilot to sign in to.
- `gh` keeps its token in the keyring when one is running, and otherwise in a plain file under `~/.config/gh`. Android's
  app sandbox is then the only protection.
- Electron here has no sandbox, as with [the browsers](../browsers/README.md#security): a compromised extension or
  page can reach everything in Termux, including SSH keys and tokens. Extensions run with your full access
  anyway, and update themselves from Open VSX, so install only those you trust.

---

# Initial assessment

This is the investigation behind the port, from before anything ran on a device. It predicted some things that
[device results](VERIFICATION.md) now settle, and its plan for Microsoft's tunnel client in Code OSS was not followed:
the user chose Open VSX instead, because of the license above. Official VS Code remains the fallback, and has not been attempted.

Investigated for native Termux, with the phone **connecting to another
development machine through a native editor window**, including the UI of workspace
extensions executing on that machine. Remote Tunnels supports this architecture.
The investigation does not establish that patching the official application is
strictly necessary: a Code OSS client is technically plausible, but unproven here.
For the closest match to Microsoft's complete client integration, the strongest
next prototype is its official ARM64 desktop build on Termux's glibc loader.
`vscode.dev` is a supported fallback, rather than the requested native-client result.

This is a source and published-package inspection, not an installation or a successful
end-to-end test. No packages or credentials were installed on the phone. The proposed
packaging patch below was tested locally against downloaded inputs only.

## Inputs and reproducibility

| Input | Inspected version |
|---|---|
| termux-packages | `ed2ff96a1160c710303c260e08eb62786bfcfda1` |
| This repository's CI pin | `538685c906074926fd19650e38c6dad91379eb0f`; its Code OSS recipe is byte-identical |
| Code OSS source | `1.144.0`, commit `2c33b50b16c472efe58357d1d2a8a5414bc23fbf` |
| Published aarch64 package | `code-oss_1.144.0_aarch64.deb`, 58,538,112 bytes; 321,120 KiB installed, before dependencies |
| Electron dependency | `electron43`; recipe inspected at `43.7.11` |
| GitHub Pull Requests, Open VSX | `GitHub.vscode-pull-request-github` `0.174.0` |
| Microsoft Remote - Tunnels manifest | `ms-vscode.remote-server` `1.6.2026092109` |
| Microsoft Remote Explorer manifest | `ms-vscode.remote-explorer` `0.6.2026100809` |
| Official Microsoft ARM64 desktop | `1.144.0`, same source commit; archive hash verified against Microsoft's update API |

The `.deb` SHA-256 matches the current Termux aarch64 X11 index:
`503b2735ea20cb553752407e164209c57fa4f9f97b530ca71f1fe95cc39d2409`.
Package metadata and selected static checks are preserved in [evidence.json](evidence.json).
The original downloads and extracted sources were inspected under
`/tmp/termux-code-oss-audit`; that directory is temporary and is not required by this project.

Primary inputs: [Termux recipe](https://github.com/termux/termux-packages/blob/ed2ff96a1160c710303c260e08eb62786bfcfda1/x11-packages/code-oss/build.sh),
[aarch64 package index](https://packages.termux.dev/apt/termux-x11/dists/x11/main/binary-aarch64/Packages.gz),
[source tag](https://github.com/microsoft/vscode/tree/1.144.0),
[Open VSX version metadata](https://open-vsx.org/api/GitHub/vscode-pull-request-github/0.174.0).

## What should work, and what needs attention

| Capability | Assessment | Required action |
|---|---|---|
| Local editing, Git UI, terminal, tasks | Included in the desktop package; runtime untested here | Install native tools and run inside the X11 desktop |
| Themes and extensions using stable JavaScript APIs | Good compatibility candidates | Check availability in Open VSX and the extension's engine version |
| Extensions launching language servers or debuggers | Depends on executable compatibility | Prefer Termux binaries and explicit executable-path settings |
| Native Node addons bundled by an extension | Linux arm64 binaries generally cannot load into this Bionic Electron | Rebuild for Android and the matching Electron ABI, or replace the dependency |
| GitHub HTTPS clone/push | Git credential helper can provide credentials | `gh auth login` followed by `gh auth setup-git` |
| GitHub account in Code OSS | Built-in provider exists, with device-code flow | Test device login and persistence; no custom OAuth app indicated by the inspected source |
| GitHub Pull Requests GUI | Available on Open VSX, but declares proposed APIs | Enable APIs for this extension explicitly; test the exact version |
| Microsoft Settings Sync | Product configuration is absent | Do not assume GitHub login enables Microsoft's sync service |
| Microsoft Remote Tunnels client inside Code OSS | Not supplied; absent from Open VSX; resolver API required; no native payload in inspected client VSIX | Requires a client integration experiment, described below |
| `code-oss tunnel` | Native tunnel executable is absent | This hosts a workspace and is unnecessary for the requested client use |
| Copilot parity with official VS Code | Not established | The recipe removes bundled Copilot and some native SDK/runtime components |

The extension platform list has Linux and Alpine targets, with no Android target.
Matching `linux-arm64` does not establish Bionic compatibility. Changing a marketplace
URL or spoofing the platform does not translate native executables, supply private
APIs, or make unavailable services work.
[Target selection source](https://github.com/microsoft/vscode/blob/1.144.0/src/vs/platform/extensionManagement/common/extensionManagement.ts).

For C/C++, the official repositories already provide Android-built
`code-oss-extension-codelldb`, `vsix-package-codelldb`, and `codelldb` (`1.12.3` in
the inspected index). The maintainer has confirmed breakpoints with a minimal debug
build. This is a useful example of fixing an extension's native dependency separately
instead of patching the editor for every extension.
[Package request](https://github.com/termux/termux-packages/issues/24715),
[working configuration](https://github.com/termux/termux-packages/issues/27463#issuecomment-3592023141).

## Remote Tunnels: phone to development machine

The intended arrangement is:

```text
Phone: native editor window + UI extensions + Remote - Tunnels client
                 | authenticated tunnel
Dev machine: VS Code Server + workspace + workspace extension host + tools
```

Remote workspace extensions can contribute commands, views, webviews, completions,
diagnostics, and debugger UI to the phone's editor while their workspace operations
execute on the development machine. UI extensions still execute on the phone.
The server is independent of the development machine's existing desktop editor:
do not assume its desktop extension directory is automatically reused. Install the
required workspace extensions in the connected remote environment. This is an
extension-host connection, not streaming the PC's entire editor process.
[Remote extension placement](https://code.visualstudio.com/docs/remote/faq#_can-an-extension-access-local-resources-or-apis-when-a-user-is-connected-remotely),
[independent server](https://code.visualstudio.com/docs/remote/tunnels).

**Native Code OSS route: a plausible experiment, not a demonstrated solution.**
Static inspection of the Remote - Tunnels VSIX found no native `.node`, `.so`, `.dll`,
or `.exe` payload. Its Node entry registers a remote authority resolver, authenticates
through the editor's GitHub provider, and starts a JavaScript proxy with
`process.execPath`. GitHub scopes are `user:email` and `read:org`. Connection setup
passes the client commit and quality to the remote host. Both of those product
values exist in the Termux package and match this upstream release.

I found no direct Code OSS name rejection in the inspected bundle. The definite
source-level blocker is the disabled `resolvers` proposal, not a proven need for a
native tunnel executable on the phone. Remote Explorer separately declares
`contribViewsRemote` and `extensionsAny`. Once the Microsoft extensions are installed
under their applicable terms, the API-enablement experiment would use a fresh process:

```sh
code-oss --enable-proposed-api ms-vscode.remote-server \
  --enable-proposed-api ms-vscode.remote-explorer
```

These flags do not install the extensions, change their licenses, or demonstrate
successful authentication and transport. The inspected client bundle does not read
the host-only `tunnelApplicationConfig` field directly; its absence is not evidence
that client connections are impossible. Test resolver registration, device login,
proxy child startup, connection, and a real remote extension before deciding that
additional core patches are necessary.
[Client package](https://marketplace.visualstudio.com/items?itemName=ms-vscode.remote-server),
[resolver API gating](https://github.com/microsoft/vscode/blob/1.144.0/src/vs/workbench/services/extensions/common/extensionsProposedApi.ts).

**Official VS Code route: adapt the runtime and launcher first.** Microsoft's
ARM64 stable archive was downloaded and verified against its
[update metadata](https://update.code.visualstudio.com/api/update/linux-arm64/stable/latest).
Its product already enables the relevant API proposals for Remote - Tunnels,
Remote Explorer, and GitHub Pull Requests, and includes Marketplace and Settings
Sync configuration. This removes several Code OSS integration differences.
The archive was 344,842,433 bytes, SHA-256
`c1758f2144c68b295fb2a3543e93bc03ab99f8ea715cfd0560377092aba0f198`.

Its main executable requests `/lib/ld-linux-aarch64.so.1` and glibc libraries.
It cannot simply be launched as a Bionic Termux executable. The existing
[Chrome installer](../../overlays/Browser+Chromium/browsers/install-chrome.py) is a
relevant local precedent for supplying Termux's glibc loader, private Linux
libraries, ELF interpreter/RUNPATH adjustments, and an X11 launcher without PRoot.
It does not establish that VS Code already works this way.

A prototype must cover the main Electron executable, crash handler, any executed
helpers, and native addon dependency lookup; isolate Bionic preload/library paths;
handle the X11 socket and writable temporary directories; and test keyring access
and proxy subprocesses. Sandbox availability also needs the same Android-specific
assessment as this project's Chrome launcher. Do not replace the official
`product.json` with the OSS one or rebuild the official app's resources merely to
change branding. Prefer loader, library, and launcher adaptation first. The remote
workspace itself continues to use the development machine's tools, reducing the
need to make local terminals and language servers fully Linux-compatible.

This is currently a feasibility assessment. The official ARM64 application was not
launched on the phone, so no complete official-client port is claimed.
[Microsoft Linux installation](https://code.visualstudio.com/docs/setup/linux).

**Browser fallback.**
On the development machine, enable Remote Tunnel Access in official VS Code, or run
the official `code tunnel` CLI there. Open its emitted
`https://vscode.dev/tunnel/...` link in Chrome on the phone and sign in with the
same account. The tunnel client is included in that web application; the phone does
not need the tunnel CLI or a local Code OSS installation for this route.
[Microsoft's tunnel instructions](https://code.visualstudio.com/docs/remote/tunnels).

With a tunnel connection, workspace extensions execute on the development machine.
Their Linux/Windows/macOS dependencies therefore need to match that machine, which
avoids most Android binary problems. Browser/UI extensions still have browser
restrictions; this does not promise that every desktop-only extension works.
[Extension placement](https://code.visualstudio.com/docs/remote/faq#_can-an-extension-access-local-resources-or-apis-when-a-user-is-connected-remotely).

For the desktop alternative, the downloaded Remote - Tunnels manifest declares
`extensionKind: ["ui"]`, proposed API `resolvers`, and the Remote Explorer extension
pack. Termux's product has no `extensionEnabledApiProposals` allowlist, and the Open
VSX endpoint for `ms-vscode.remote-server/latest` returned 404. Sideloading alone
therefore does not establish a working client. Microsoft also distributes this
extension under its Remote Development terms, associated with its VS Code product;
this assessment does not propose modifying those product checks or redistributing it.
[Marketplace entry](https://marketplace.visualstudio.com/items?itemName=ms-vscode.remote-server),
[extension license](https://ms-vscode.gallery.vsassets.io/_apis/public/gallery/publisher/ms-vscode/extension/remote-server/1.6.2026092109/assetbyname/Microsoft.VisualStudio.Services.Content.License).

For completeness, source `src/vs/code/node/cli.ts` dispatches `tunnel` to a native
`code-tunnel-oss` executable. The published package contains none. Building that
Rust CLI would still leave service configuration and a compatible server to solve.
The existing Termux request documents Android compilation failures and explicitly
distinguishes Coder's `code-server` from Microsoft's CLI. That host-side port is
outside the requested phone-as-client workflow.
[CLI source](https://github.com/microsoft/vscode/blob/1.144.0/src/vs/code/node/cli.ts),
[Termux discussion #27660](https://github.com/termux/termux-packages/issues/27660).

## GitHub integration and extension APIs

There are two separate authentications: credentials used by the Git executable and
the editor's GitHub authentication sessions. Configuring `gh` as Git's helper
supports HTTPS operations in the editor but does not sign its PR extension in.
[GitHub CLI login](https://cli.github.com/manual/gh_auth_login),
[Git credential setup](https://cli.github.com/manual/gh_auth_setup-git).

The package includes `vscode.git`, `vscode.github`, and
`vscode.github-authentication`. Authentication source has a public OAuth client ID,
supports device codes without a client secret, and has a PAT fallback for unsupported
clients. `code-oss` is deliberately excluded from the standard browser callback
scheme allowlist, so adding Microsoft's secret or changing the product identity is
not the indicated fix. Device login is the first route to test. The setting
`"github-authentication.preferDeviceCodeFlow": true` is available if needed.
[Authentication configuration](https://github.com/microsoft/vscode/blob/1.144.0/extensions/github-authentication/src/config.ts),
[flow selection](https://github.com/microsoft/vscode/blob/1.144.0/extensions/github-authentication/src/flows.ts),
[callback recognition](https://github.com/microsoft/vscode/blob/1.144.0/extensions/github-authentication/src/common/env.ts).

The Open VSX PR extension has no `.node`, `.so`, `.dll`, or `.exe` files in the
inspected VSIX. Its main obstacle identified here is API enablement: it declares
32 proposed APIs, all present in Code OSS 1.144.0. The published product lacks a
proposal allowlist. Source explicitly clears proposed APIs for ordinary installed
extensions unless individually enabled. Start a fresh Code OSS session with:

```sh
code-oss --enable-proposed-api GitHub.vscode-pull-request-github
```

This permits the declared proposals; it is not an end-to-end PR functionality test.
Do not globally enable proposed APIs. If this becomes a default, use a scoped launcher
or the user's runtime arguments after device validation. No editor fork is needed
just to try this extension. The current PR extension requires `^1.144.0`, so older
editor versions need a compatible extension release.
[API enforcement](https://github.com/microsoft/vscode/blob/1.144.0/src/vs/workbench/services/extensions/common/extensionsProposedApi.ts),
[exact PR manifest](https://open-vsx.org/api/GitHub/vscode-pull-request-github/0.174.0/file/package.json).

Persisted editor login also depends on working secret storage and a session D-Bus.
The recipe depends on `libsecret`, which alone does not prove that a Secret Service
is running. Verify login survives restart in the project's actual GNOME session.
Do not work around a keyring failure by silently weakening credential storage.

## Concrete patch findings

**Desktop metadata: confirmed packaging defect.** The published
`code-oss-url-handler.desktop` contains
`MimeType=x-scheme-handler/@@URLPROTOCOL@@;`, which `desktop-file-validate` rejects.
`code-oss.desktop` also retains `StartupWMClass=@@DESKTOP_NAME@@`.
The recipe installs the source templates but omits these two substitutions.
[Upstream's Linux packaging](https://github.com/microsoft/vscode/blob/1.144.0/build/gulpfile.vscode.linux.ts)
does substitute both from `product.json`.

[termux-desktop-metadata.patch](termux-desktop-metadata.patch) fixes the Termux
recipe and increments its package revision. It applies to the inspected Termux
checkout, **not** to the VS Code source tree. The substitutions produce
`x-scheme-handler/code-oss` and `code-oss`, with no template tokens left in either
desktop file. Its first version used `com.visualstudio.CodeOSS`, which a device test
showed to be wrong. This fixes generic desktop URL handling; device-code GitHub login
does not depend on a `code-oss://` callback.

**OS proxy integration: confirmed incompatible bundled binary, runtime impact
unverified.** The package contains
`@vscode/os-proxy-resolver-linux-arm64-gnu/os_proxy_resolver.node`. `readelf -d`
shows `libc.so.6`, `libpthread.so.0`, and `ld-linux-aarch64.so.1` dependencies.
The wrapper's platform map has no Android entry. The native host imports this
package for `resolveProxyWithPackage` and `readProxyConfigWithPackage`; it also has
a separate Electron proxy resolution path. This deserves an upstream issue and a
targeted Android implementation/fallback if the package path is used. It does not
establish that ordinary direct GitHub connections fail.
[Proxy package source](https://github.com/microsoft/os-proxy-resolver),
[native host calls](https://github.com/microsoft/vscode/blob/1.144.0/src/vs/platform/native/electron-main/nativeHostMainService.ts).

**Already fixed upstream:** patch `0009` uses `node-ovsx-sign` for Open VSX signatures;
that module is present in the published ASAR. The historical signature problem is
not a reason to disable verification globally. Patch `0013` preserves `LD_PRELOAD`
so Git hooks retain `termux-exec` shebang handling.
[Signature issue](https://github.com/termux/termux-packages/issues/24739),
[signature patch](https://github.com/termux/termux-packages/blob/ed2ff96a1160c710303c260e08eb62786bfcfda1/x11-packages/code-oss/0009-openvsx-extension-signature.patch),
[Git hook fix](https://github.com/termux/termux-packages/pull/32912).

Older reports need version context. The 2024 Python issue concerns TUR's 1.90.0
build, while a later update discussion records Electron/NDK build constraints.
Neither proves the inspected 1.144.0 package is unusable.
[Python discussion](https://github.com/termux-user-repository/tur/issues/1197),
[update discussion](https://github.com/termux/termux-packages/issues/30579).

## Installation and remaining verification

[The overlay](#install) and [device results](VERIFICATION.md) replace this section, which is kept as written.

For a local Code OSS trial, run these in native Termux. They are instructions, not
commands executed during this investigation:

```sh
pkg install x11-repo
pkg update
pkg install code-oss git gh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
code-oss --install-extension GitHub.vscode-pull-request-github
code-oss --enable-proposed-api GitHub.vscode-pull-request-github
```

Launch the last command from the running X11 desktop's terminal so it inherits
DISPLAY and the session D-Bus. `code-is-code-oss` is optional and only supplies
`code`/`vscode` aliases; it does not install Microsoft's tunnel executable.
Keep executable tools and projects needing execution in Termux's private filesystem.

Before adding Code OSS to the project's default installation, verify:

1. Terminal and tasks execute native Termux tools, and a Git hook with an env shebang runs.
2. HTTPS clone/push works through the configured Git helper, without publishing test commits.
3. The PR extension signs in through device flow, lists a private repository and PR,
   and still works after restarting the editor and the desktop session.
4. A signed Open VSX extension installs and updates normally; inspect extension-host logs
   for API and native-module errors.
5. The corrected URL handler is registered, and GNOME associates windows with the launcher.
6. For the requested native-client result, connect from a phone editor window to a
   real development-machine tunnel, execute a remote task, and confirm the required
   extension runs in the remote extension host while its views appear on the phone.
   Check UI extensions separately in the local extension host. Use `vscode.dev` only
   as a baseline to separate host/tunnel/account failures from native-client failures.

The static checks establish package contents, API gating, and the metadata defect.
GUI startup, keyring persistence, OAuth completion, remote connectivity, and individual
extension behavior remain untested.
