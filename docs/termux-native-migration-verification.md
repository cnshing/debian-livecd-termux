# Verification of the native Termux migration assessment

**Later implementation:** [native desktop verification](native/VERIFICATION.md)
records the subsequent GNOME port and phone changes. This document remains the
historical audit of the migration assessment, not verification of that code.

Verified against
[termux-native-migration.md](termux-native-migration.md) and its evidence folder. Graded
for factual correctness, sanity of reasoning, and whether the tests it ran show what it
says. This was a check of the document only. Nobody was working on the phone, and no
native desktop was built or installed.

**Follow-up:** the assessment has since been revised to address N1–N6 and to record the user's current GNOME 48 preference; see its section 13. The findings below describe the original version (SHA-256 `bd6fd5ca…`).

**Later implementation:** a separate [native EasyEffects/AutoEq prototype](audio/VERIFICATION.md)
was built and tested after this document-only audit. Its package installations
and audio tests are recorded there; they do not change this audit's historical
phone-state claims.

**Verdict: accurate, with one material gap.** I re-checked about 60 specific claims
against upstream sources, the package indexes, our code and the phone. Nearly all hold
exactly. The gap: the document never mentions that official Termux deliberately removed
its Mutter package in August 2026 because X11 support was abandoned. That fact explains
one of the document's own findings, and it bears on the long-term maintenance cost of
the route it recommends. The recommendation still stands, but its maintenance cost is
understated. The other findings are small.

## Findings

### N1 (Medium): The document omits that official Termux removed Mutter

The document says Mutter is absent from the official repositories. It treats this as a
packaging gap that a community package may fill "until suitable packages become
official" (sections 4.2 and 11). The recipe tree it pinned shows that official Termux
used to ship Mutter and removed it on purpose.

```
$ curl -s "https://api.github.com/repos/termux/termux-packages/git/trees/6016cd09…?recursive=1"   # paths matching */mutter/*
disabled-packages/mutter/build.sh, 0001…0006 *.patch, gir/{Clutter,Cogl,Meta,Mtk}-16.xml
$ curl -s https://raw.githubusercontent.com/termux/termux-packages/6016cd09…/disabled-packages/mutter/build.sh | grep VERSION=
TERMUX_PKG_VERSION="48.1"
$ curl -s https://api.github.com/repos/termux/termux-packages/commits/739766d051
2026-08-28  Robert Kirkman  rmpkg(x11/mutter): X11 support abandoned
  - It will not be possible to update to the newest version anymore because it is not an X11 window manager anymore
```

The evidence file `packages.tsv` lists `mutter` with no recipe because its method only
looked at the main and X11 recipe folders, which leaves out `disabled-packages/`.

What I expected: the assessment to record this removal, because it affects three of its
conclusions.

- **The GNOME-Termux release gap:** that release was published on 2026-08-14, while
  official `mutter` 48.1 still existed. That is why its manifest asks for `mutter` and
  the archive leaves out the Mutter libraries. The document instead calls it "a
  previously prepared author's environment" (section 4.1). The gap is real today, but
  the cause is the official removal, not an author's packaging mistake.
- **The GNOME 48 route:** an official Mutter 48.1 recipe with Android patches still
  exists in `disabled-packages/`. Section 11 rates recovering a build for this route as
  "moderate-to-higher" effort without mentioning this recipe.
- **The GNOME 49 route:** the recommended pull request adds X11 Mutter back, the very
  thing the maintainers removed. One contributor in the request's own discussion
  doubts it will be merged:
  > "i don't think it will get merged until we find some way to keep it up to date …
  > we will need to make a lot of backports to keep it running, which i don't think
  > anyone will want to do" (`sabamdarif`, 2026-10-24)

  The "until suitable packages become official" framing in sections 4.2 and 11 is
  therefore optimistic. Without official packages, this project would maintain its own
  GNOME 49 X11 build indefinitely, which goes beyond the "community patch/build
  ownership" that section 11 lists as the ongoing cost.

### N2 (Low): The "startup" figure is actually a start-and-stop cycle

Section 2 says the round 2 verification established "startup around 37–39 seconds in the
repeated lifecycle exercise". In the PRoot profile's `test-lifecycle.py` (since removed), the timer starts before
`start` (line 34) and is read after the stop or logout finishes (line 59). The 37.3–38.8
seconds are full start-and-stop cycles.

What I expected: the figure to be labelled as a cycle time. This matters because
section 10 makes "desktop readiness" a baseline for later comparisons. The document
does not use the number for any calculation.

### N3 (Low): One package version is wrong

Section 5 lists `ffmpegthumbnailer` as "Official 2.4.0". The same index file (identical
hash `f7f4fb8e…`) contains two records, 2.4.1 and 2.4.0. APT installs 2.4.1. Of the 227
packages in `packages.tsv`, this is the only one where the recorded version is not the
newest in the index. It looks like the parser kept the last record instead of the
newest.

### N4 (Low): The GNOME-Termux release is missing more than two libraries

The document names two dependencies the v48.1 archive needs but cannot get from the
official repositories: Mutter and `libmozjs-128.so`. There are more. The archive's
`gnome-shell-calendar-server` needs `libecal-2.0.so.3`, `libedataserver-1.2.so.27` and
`libical-glib.so`. The official repositories don't publish `evolution-data-server`, and
the official `libical` recipe builds with `-DLIBICAL_GLIB=false`. The official
`spidermonkey` package is version 140, so it doesn't provide `libmozjs-128.so` either.
This strengthens the document's conclusion. It shows that the document's dependency
check did not cover every library, a check the document itself lists as the first step
for this route (stage 1).

### N5 (Info): The only performance test measures the wrong thing, and a better one supports the document

The document's only timing compares starting a native command with starting one through
`proot-distro login`. It correctly says this "does not isolate steady-state syscall
overhead" and leaves application gains unmeasured. I repeated its test and added a
steady-state comparison: Python inside one running Debian PRoot, against native Python,
with the desktop running in both cases.

| Operation | Inside PRoot | Native | Ratio |
| --- | ---: | ---: | ---: |
| `os.stat` on the home directory (20,000 calls) | 654–676 µs | 5.3–5.4 µs | about 120× |
| Create and delete a file (2,000 times) | 3.26–3.47 ms | 0.12–0.14 ms | about 25× |
| Run `true` (median of 50) | 12.9–13.5 ms | 8.3–8.5 ms | about 1.5× |
| Repeat of the document's entry test (median of 10, two runs) | 480–484 ms | 17–19.5 ms | — |

The entry test reproduces in direction, with higher absolute numbers than the
document's (7.69 ms and 366 ms), probably from differing phone load. File and path
syscalls inside PRoot cost one to two orders of magnitude more. That supports the
document's main expected gain more strongly than the evidence it actually cites.
Probe scripts and raw output were kept in temporary local storage. The table
above quotes the second script's output from the console.

### N6 (Info): Facts in the recommended pull request that the document understates

- **LocalSearch:** the request's LocalSearch recipe already sets `-Dlandlock=disabled`.
  Section 7 only says a native build "may need feature changes" for the Landlock failure.
- **Shared packages:** the request modifies two packages that are already official,
  `libical` (turning on its GLib bindings) and `guile` (adding a `WAIT_ANY` patch).
  Section 4.2 calls shared-library updates "potential". For this route they are
  certain, which raises the risk to the shared `$PREFIX` that section 9 describes.
- **Runtime requirements:** one tester in the request's discussion (`Collalaoo`,
  2026-10-25) needed three things to start GNOME Shell 49.3 on Termux:X11:
  - `-legacy-drawing`;
  - `MESA_LOADER_DRIVER_OVERRIDE=swrast` (they report that `llvmpipe` alone crashes in
    `cogl_renderer_connect`);
  - a running `dbus-daemon --system`.

  These are a single person's reports, not verified here, but they apply directly to
  stage 2.

## Claims I verified as correct

| Area | Claim checked | Result |
| --- | --- | --- |
| Evidence integrity | `SHA256SUMS` (12 files) and `local-source-sha256.tsv` (31 files) | All match the current files |
| Package indexes | Download hashes `f7f4fb8e…` and `403f881e…`; 4,219 distinct names | Identical when re-downloaded later the same day |
| Recipe tree | Commit `6016cd09…` not truncated; 3,278 recipes | 3,457 `build.sh` files minus 179 disabled = 3,278 |
| Recipe hashes | All 18 recipe hashes in `recipes.json` | All match |
| Recipe contents | `mpv-x` conflicts with and replaces `mpv`, with GL and Vulkan on; main `mpv` has X11, GL and Vulkan off; both have `android-media-ndk` off. LibreOffice: GTK3 on, GTK4, dconf and Skia off, no bundled fonts. Chromium sandbox note. GTK4 X11 backend on. Mesa Zink, Freedreno and KGSL. htop's fallback copy of `/proc/stat`. GNOME Terminal's Nautilus extension and search provider off. `xfce4` dependencies | All as described |
| Versions | Ghostty 1.3.1, GNOME Terminal 3.60.0, Text Editor 51.0, Firefox 159.0, Chromium 156.0.8078.47, LibreOffice 26.8.2.2-1, `mpv-x` 0.41.0-7, Thunar 4.20.10, Tumbler 4.20.2, GTK 4.24.1, libadwaita 1.10.0 | Correct (`ffmpegthumbnailer` aside, N3) |
| Absent packages | GNOME Shell, Mutter, gnome-session, Nautilus, GJS, Mission Center and Flatpak are absent. Fonts: only `ttf-dejavu` and `otf-noto-sans-cjk`; no Unifont, Hanazono or Cantarell | Correct |
| GNOME-Termux repository | Commit `42a890c…` is still the head. The installer hard-codes `48.0` and `…-48.0-native-termux-…`, expects `GNOME-Termux/`, never reads `$1`, and uses display `:1` with `pkill` on gnome-shell, mutter and termux-x11 and `killall pulseaudio`. The README shows a positional-argument install and lists Shell 48.0, GJS 1.85.1 and Mutter 48.1. `dist/` contains Mutter and mozjs-128 libraries, and its `gnome-termux-env.sh` points at `/data/…/home/gjs-install-test/…` | All correct |
| GNOME-Termux release | Only v48.1 exists. SHA-256 `f89f8ab2…`, 3,629,256 bytes, 590 entries matching the `.tsv` list exactly, top-level folder `GNOME-Termux-48.1-aarch64`. The Shell executable uses `/system/bin/linker64`. Meson reports `gnome-shell 48.0`. No Mutter or mozjs files. The archive's `install.sh` copies GJS into `$PREFIX`, replaces the Shell symlinks, recompiles the global schemas and moves the Pulse policy file. Its scripts use `:0` and `$HOME/GNOME-Termux` | All correct |
| GNOME 49 pull request #32883 | Open, unmerged, created 2026-10-23, 110 files, head `b3c8d590…`. Mutter 49.8 (X11 on; logind, udev and native backend off). Shell 49.3 (systemd, polkit and NetworkManager off). Settings daemon (systemd, elogind, gudev, rfkill, WWAN and NetworkManager off). Shepherd session. Nautilus 49.3 with Android patches. The `gnome` metapackage pulls in extra apps. Every runtime dependency is either official or in the request. The author reports testing a full session | All correct |
| Older request #24585 | Closed without merging | Correct |
| Anland | Commit `140fb63…`. The guide describes the display APKs (standard and F-Droid-compatible), the daemon, a custom Mutter and a patched Xwayland. Its session helper handles a private system bus and XSettings. The latest release is 5.13.4, with no 6.0 | Correct |
| Mutter 50 | `NEWS`: "Drop the X11 backend" under 50.alpha | Correct |
| Termux and Termux:X11 READMEs | Android 12+ process warning; the shared-UID variant ("Avoiding slowdowns") | Correct |
| Our code | `guest()` builds every PRoot entry, and startup enters the guest for `check`, `pid` and `ready`. Ghostty is forced to llvmpipe. Appearance metadata says `"shell-version":["48"]`. `themes.sh` writes to `/usr/share`, `/var/cache` and `/etc/dconf`. `livecd` has no backend option. The guest's `MOZ_FAKE_NO_SANDBOX=1` is recorded in the evidence. The earlier reports describe the Unix-socket Pulse failure and the Landlock failure | Correct (N2 aside) |
| Guest versions | GTK 4.18.6, libadwaita 1.7.6, Shell 48.7, gnome-session 48.0 | Correct |
| Phone probes | `/proc/stat` permission denied natively. A native busy process stopped by SIGSTOP stays in state `T` with its ticks frozen (70→70) and resumes on SIGCONT. Entry cost difference | Reproduced (timings vary, N5) |
| "No changes" claim | The last APT run predates the assessment. The desktop processes are the same. The containers are `debian` and `livecd-clean`, and the config still selects `debian`. `fc-list` is not installed | Correct; the phone was not modified |

## What I could not verify

- **Anland "wait for 6.0" constraint:** the document says this is your requirement:
  wait for a stable 6.0 that needs no compositor repatching. It doesn't appear anywhere
  in the repository, so only you can confirm it. As of today it isn't met either way,
  because the latest Anland release is 5.13.4.
- **Not built, as the document says:** none of the community GNOME builds (48 or 49)
  were built or run, by the document's author or by me. Every statement about them
  working rests on source code and other people's reports.

## Phone changes made during this verification

- Ran read-only checks on status, the package log and the config.
- Ran one disposable native busy process, which was stopped, resumed and terminated.
- Made about 45 `proot-distro login debian … true` or `python3` entries.
- Created and deleted a temporary file `.probe-x` 2,000 times, both in the guest's
  `/home/desktop` and in the native home. Neither file remains.
- Nothing was installed and no settings were changed. The desktop was the same before
  and after (owner 2512, Shell 2771).
