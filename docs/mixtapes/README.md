# Mixtapes on native Termux

An **opt-in Android/Bionic port** of [Mixtapes](https://github.com/m-obeid/Mixtapes), a GTK4 and
libadwaita YouTube Music player written in Rust. It runs in native Termux with no PRoot or root, and
appears in the [native GNOME desktop](../native/README.md)'s menu once installed. Tested without an
account on one phone: see [the verification report](VERIFICATION.md).

```text
Mixtapes (Bionic) ─ GTK4, libadwaita, WebKitGTK ─ Termux:X11
   ├── GStreamer ─ curlhttpsrc ─ YouTube's servers
   │       └── pulsesink ─ the desktop's PulseAudio ─ Android
   ├── yt-dlp and Node.js: fallback stream resolver, and downloads with FFmpeg
   └── rustypipe-botguard (glibc): PO tokens for uploaded songs
```

## Build and install

GitHub Actions builds the package from [its recipe](../../packages/mixtapes/build.sh), which downloads
a pinned upstream commit, verifies its SHA-256 and applies the patches. To install it from the local apt
repository, run this in native Termux:

```sh
livecd-pkg install mixtapes
```

`livecd-pkg install mixtapes` also adds Termux's glibc repository, glibc and its OpenSSL, which
uploaded songs need. Everything else works without them.

> **What was tested:** every result below comes from a binary built on the phone by
> an earlier on-phone build script, since removed. The
> recipe uses the same source and patches, but it cross-compiles and has not been built yet.

### Building on the phone

The tested binary was built on the phone with an earlier script, since removed from the repository.
These notes apply if you build on the phone again.
To install a rebuild at the same version, use `dpkg -i`: `apt` can report success and change nothing. **Check the
battery first.** Compiling can draw more than a charger supplies. On the tested phone with a roughly 1 A charger, the
battery fell from 6% to 3% in about a minute with the build on the performance cores (`taskset f0`), while
Android still showed "Charging". On the four efficiency cores (`taskset 0f`) the same build stayed net positive,
but it took far longer. Pause with `SIGSTOP` if you need to: the compiler resumed cleanly after 16 hours stopped.

The core masks are for this phone's Snapdragon 855. After the patch changed one line, a rebuild took 35 minutes
on the performance cores, almost all of it optimising and linking the app itself. The compiler peaked at about
1.5 GB of memory on that final crate, and the build cache grew to about 2.2 GB.

## Run

Use the **Mixtapes** menu entry, or from a shell:

```sh
livecd-native exec -- mixtapes
```

**Start it through the desktop.** A plain Termux shell on the same display runs, but has no route to
the desktop's PulseAudio or session bus, and [cannot find the icon theme](../native/README.md#icons).

Closing the window keeps music playing, as upstream intends. Open the menu entry again to bring the
window back, or quit from the app's menu. **GNOME Shell's media controls**, under the clock, control
playback too.

**Dark style.** The desktop asks for dark, but libadwaita reads that through a settings portal, which
this desktop does not run, so Mixtapes opens light. To force it, for this one application:

```sh
livecd-native exec -- env ADW_DEBUG_COLOR_SCHEME=prefer-dark mixtapes
```

That is a libadwaita debugging variable, so it could change in a later release.

## What works and what does not

Every entry is from [one phone, without an account](VERIFICATION.md).

| Feature | State |
| --- | --- |
| Home, search, covers, preferences | Works, signed out. Artist, album and playlist pages were not opened |
| Playback, pause, seek, background playback after closing the window | Works. Heard from the phone's speaker |
| Fast stream resolving | Works with the header fix below: first audio about 2 s after a click |
| MPRIS and GNOME Shell's media controls | Works |
| Downloads, with tags and the library database | Works, as opus |
| Synced lyrics | Works. Some providers were down during testing, and the app moved on to others |
| Menu entry, icons, second launch reopening the window | Works |
| Sign-in window | Google's page loads. **Signing in was not tested** |
| Library, likes, uploads, scrobbling | **Not tested**: need an account |
| Discord presence | **Not tested**: needs a Discord client on the phone |
| Hardware audio decoding | None: decoding is on the CPU, about 12–16% of one core while playing |
| Screen off, long sessions | **Not tested** |

## Security

**WebKit has no sandbox here.** `bwrap` is not installed, and this kernel has no user namespaces for it
to use. During sign-in, `WebKitWebProcess` ran with the same UID and the same Android seccomp filter as
the app, so a compromised page could reach all of Termux's files. The sign-in window only shows Google's
own page, but keep this in mind before typing an account password. The app then stores that session in
`~/.local/share/livecd-native/muse/headers_auth.json` when started from the desktop.

Upstream's prebuilt `rustypipe-botguard` runs with Termux's full access. Its archive's checksum matched
the [v0.1.2 release](https://codeberg.org/ThetaDev/rustypipe-botguard/releases/tag/v0.1.2).

## Termux changes to Mixtapes

Rust targets `aarch64-linux-android` on Termux, so code gated on `target_os = "linux"` is left out.
[`0001-termux.patch`](../../packages/mixtapes/0001-termux.patch) and the two smaller patches beside it are the complete list:

| Change | Reason |
| --- | --- |
| MPRIS built on Android | Upstream gates it on `linux`, which would select the Windows media-control code's stub |
| PO tokens from a helper program instead of linked V8 | `rusty_v8` publishes no Android library. Upstream's Windows build already works this way |
| Helper's install path | Termux's prefix |
| `rustls-platform-verifier` from a local copy | Its Android module needs a JVM to reach Android's trust store. [`0002-rustls-verifier-no-jvm.patch`](../../packages/mixtapes/0002-rustls-verifier-no-jvm.patch) disables that `cfg`, which selects the Unix module and Termux's CA bundle |
| Menu entry runs `mixtapes` | The program is installed as `mixtapes`, not `muse` |
| HTTP/2 header limit raised to 64 KB | **A bug, not a port issue**, below |

**The header limit.** `music.youtube.com` now sends about 17 KB of response headers, seen identically
from the phone and a PC. The HTTP client's default limit is 16 KB, so the request for visitor data
fails, and every play then falls back to the much slower `yt-dlp`. It should affect other platforms at
this commit too, though only Termux was built here. It is worth reporting upstream.

**PO tokens.** Only uploaded songs and gated formats need them. If the glibc packages are missing, the
helper fails, the app logs it, and everything else still plays. Without V8 linked in, tokens come from
[a small wrapper](../../packages/mixtapes/rustypipe-botguard) around upstream's arm64 glibc program.

**GStreamer's HTTP source.** `souphttpsrc` cannot load here, because its loader only asks for
`libsoup-3.0.so.0` and Termux ships `libsoup-3.0.so`. Playback uses `curlhttpsrc` from `gst-plugins-bad`,
which upstream's code already handles, and seeking works through it.

Harmless log noise: GStreamer warns about two unrelated plugins, `libgstisac` and `libgstwebrtcdsp`,
whose libraries are not installed. `gst-inspect-1.0 openslessink` hangs here, but playback never
uses that element, because `pulsesink` outranks it.

## Tests

Inside the running desktop. Each run uses scratch data directories, and nothing signs in:

```sh
livecd-native exec -- python tests/mixtapes/test-mixtapes.py OUTPUT_DIRECTORY [CHECK ...]
```

**This plays music out loud**, opens and closes windows on the desktop, and moves the pointer. Checks
are `identity`, `tls`, `playback`, `idle_usage`, `download`, `po_token`, `screens`, `lyrics` and `real_use`.
Its `tls` check puts a fake interception server in front of the app and asserts that no request
reaches it. The `playback` check measures the signal before Android's volume, so it cannot show that
sound left the speaker.

## Remove

```sh
apt remove mixtapes
```

Your session, preferences, cache and downloads are kept, in `~/.local/share/livecd-native/muse`,
`~/.cache/livecd-native/muse` and `~/Music/Mixtapes`.
