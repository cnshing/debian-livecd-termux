# How this repository fits together

## The three layers

Every change to a program belongs to exactly one layer:

| Layer | Where | Test | Example |
|---|---|---|---|
| Patch | `packages/<name>/*.patch` | It will not run on Android without this | Nautilus's `getpwent`, gnome-session's no-logind |
| Package | `packages/<name>/build.sh` | Any Termux user would want this default | Build flags, license files |
| Overlay | `overlays/<Feature>/` | This is our preference | dconf settings, themes, wallpapers, uBlock |

A package stays usable on its own, with its upstream defaults. Overlays adjust it afterwards.

## From source to phone

```text
packages/<name>/       GitHub Actions compiles the recipes       release tarball
  build.sh         ->  with termux-packages' builder         ->  livecd-termux-repo-aarch64.tar.gz
  *.patch                                                             |
                                                                      v
overlays/ ------------------------------------------------->  install.sh on the phone
src/native/packages.txt ---------------------------------->    1. unpacks the tarball into repo/
src/ ------------------------------------------------------>    2. installs packages with apt
                                                                3. connects the packaged GNOME runtime
                                                                4. connects packaged controller scripts
                                                                5. applies the overlays
```

The apt repository in `repo/` is local: `install.sh` points apt at it with a `file://` source. Official
Termux packages still come from Termux's own mirrors, so installing needs network access unless those
are already installed.

`install.sh` also pins this repository at priority 1001, so its packages win over any same-named package on
Termux's mirrors, even a newer one. The next `apt upgrade` also replaces a newer copy installed by hand.

## Patches

Recipes follow the [termux-packages](https://github.com/termux/termux-packages) format, so
`build-package.sh` applies them by itself: every `*.patch` beside `build.sh`, in name order, with `-p1`.
It also fills in `@TERMUX_PREFIX@` and `@TERMUX_HOME@`.

Use these placeholders in patches instead of hardcoding Termux's prefix or home directory,
as required by the [Termux patch guidelines](https://github.com/termux/termux-packages/wiki/Coding-guideline#patches).
Standalone build helpers that apply recipe patches must expand the placeholders too.

ArcMenu and DING patches live in
[`packages/livecd-gnome-data/`](../packages/livecd-gnome-data) and apply during the
package build. WhiteSur's installer is profile-specific, so its
[`overlay patches`](../overlays/Desktop%20Environment+Theming/patches/whitesur)
still apply on the phone, using the same placeholders.

The normal GNOME installation builds mozjs-128, GJS 1.84.2, Mutter 48.8 and
Shell 48.8 from verified source archives. The four recipes install into
`$PREFIX/opt/gnome-48`, which keeps this ABI-matched stack separate from rolling
Termux libraries while retaining APT ownership. The runtime package installs
schemas and the session definition. `livecd-desktop` owns the controller code and
commands; per-user setup only creates compatibility links and preserves replaced
runtime/profile paths in a backup.

The packaged recipes retain the original native source port's patches and the upstream Termux XML dumps
used for cross-compilation of introspection data. The old binary bootstrap in
`prebuilt/gnome-runtime/` remains for historical reproduction and is not called by
`install.sh`. Normal setup does not fetch or rewrite a GNOME executable.

`livecd-gnome-data` deliberately keeps pinned, architecture-independent Debian
archives as inputs for readable extension JavaScript, fonts and cursors. It
preserves attribution and excludes ELF files and Debian package scripts. These
assets are now packaged and upgraded by APT; this is not a rebuild of every font
or every extension's original source release. GSConnect, which has its own build
system, now builds its source archive with Meson and retains Debian's security fix.

Code OSS's generic desktop metadata repair is in its package recipe. Its profile
wrapper and extension choices remain overlays. `packages/code-oss/upstream.json`
records the original recipe checksum: staging requires the pinned upstream tree
and retains that tree's source patches and helper files.

Google Chrome remains a publisher binary, with separate browser/video work.
Theme variants and add-on choices remain profile-specific overlays. The remote
Code OSS SSH server targets Linux machines and keeps its standalone artifact
builder; it is not an Android package. Its Termux patch revision comes from the
same builder configuration as CI.

## Building packages

Use the same Termux package builder locally and in CI:

```sh
# Linux host with Docker, or a configured native Termux build environment:
bash tools/build-packages.sh mission-center

# Native Termux: build and install the generated .debs through APT:
bash tools/build-packages.sh --install mission-center
```

Stop the managed desktop before native builds. The helper takes the same session
lock as setup, and defaults to two build jobs on a phone (`JOBS` or
`TERMUX_PKG_MAKE_PROCESSES` can override it).

The helper checks out the pinned builder, stages our recipes, and includes this
repository's dependencies in build order. `LIVECD_TERMUX_BUILDER` can name an
existing checkout at that exact revision. Termux's ordinary [build environment
setup](https://github.com/termux/termux-packages/wiki/Build-environment) applies.
The compatibility `packages/*/build-on-device.sh` commands now call this helper;
they do not copy over installed package files or add APT holds. UPower's old
`--no-install` option still builds without installing.

A `build.sh` may invoke Python helpers for resources, metadata or other build
steps. The recipe still declares its sources, checksums and dependencies, and
Termux applies its patches and produces the package. Rewriting a correct Python
build step in shell is not a packaging requirement.

## Overlays

Overlays use upstream's feature names and shape, so they can be compared with
[upstream's](https://github.com/cnshing/debian-livecd/tree/main/overlays).
[`overlays/UPSTREAM`](../overlays/UPSTREAM) records the commit that the copied files came from.
Termux reads these from each overlay:

| Path | Effect |
|---|---|
| `packages/termux.yaml` | Termux packages to install |
| `filesystem/termux/home/` | Copied to `$HOME`, replacing what is there |
| `filesystem/termux/home-defaults/` | Copied to `$HOME` only where nothing exists yet, so user changes survive |
| `filesystem/termux/prefix/` | Copied to `$PREFIX` |
| `hooks/termux/NNNN-*` | Run last, in number order across all overlays, as upstream's hooks are |
| `*.overlay.tmpl` | Any of the above: `@TERMUX_PREFIX@` and `@TERMUX_HOME@` are filled in and the suffix is dropped |

Some of upstream's own files are used unchanged, such as its dconf fragments. The list is in
[`apply-overlays.py`](../src/apply-overlays.py).

[`overlays/termux.yaml`](../overlays/termux.yaml) lists the overlays applied by default. To add an opt-in
overlay later, run this in native Termux with the desktop stopped:

```sh
python src/apply-overlays.py "Audio Effects"
```

## GitHub Actions

[`.github/workflows/packages.yml`](../.github/workflows/packages.yml) does the compiling:

| To build | Do this |
|---|---|
| One package | `gh workflow run packages.yml -f packages=nautilus` |
| Several packages | `gh workflow run packages.yml -f packages="nautilus easyeffects"` |
| Everything | `gh workflow run packages.yml` |
| Everything, and publish a release | Push a tag such as `v1`, or add `-f release=v1` |
| Only what changed | Automatic on pushes to `main` and on pull requests that change `packages/`. A push builds everything changed since the last push whose run succeeded, so nothing from a cancelled or failed run is skipped |

Only a full build can publish, because `install.sh` takes the latest release as complete. The result of any
other run is available as a workflow artifact, and `install.sh --repo-tarball` can install it.

**Parallel jobs.** Each group of recipes that depend on each other is one job, and groups run at the same time,
up to 20. A job always includes the recipes from this repository that its target needs, so
`packages=nautilus` also builds `gnome-autoar`. Chromium is the exception: it alone takes most of a job's six
hours, so it always gets a job of its own, with only `libva`, and the full 360 minutes. Recipes that share
`libva` with it build in another job. To see the plan without running anything:

```sh
python3 tools/recipes.py plan --all
```

**Caching.** Builder dependencies are kept with `actions/cache`, even when a build fails. The toolchain and
host tools share one entry. Downloaded dependency packages and source archives have one entry per job, and
a new job can start from another job's. All of them are tied to the pinned builder revision. The
container image and Rust's crate registry are not cached. The image and revision are pinned together in `tools/termux-build.json`, because the image holds the matching NDK. CI and the local helper read the same file.

To check that every patch still applies to its pinned source, without building anything:

```sh
python3 tools/recipes.py check-patches
```

## GitHub limits and access

This repository is public, so standard runners are free. These were GitHub's published figures when assessed.
Check [its documentation](https://docs.github.com/en/actions/reference/limits) for current ones.

| Limit | Value |
|---|---|
| Standard runner | 4 CPUs, 16 GB RAM, 14 GB SSD |
| Concurrent jobs | 20 on the Free plan |
| One job | 6 hours, however high `timeout-minutes` is set; this workflow stops at 350 minutes so the caches still save, and Chromium's job at 360 |
| Cache | 10 GB per repository; a job that restores nothing downloads everything again |

Anyone can read this repository, its releases and its run status without logging in. Starting a build from the
command line, reading raw logs or pushing needs a token. For a fine-grained token limited to this repository:

| Use | Repository permissions |
|---|---|
| Run builds, read logs, download artifacts | Actions: read and write; Contents: read; Metadata: read |
| Also push commits and tags | Add Contents: read and write; add Workflows: read and write to change `.github/workflows/` |

Pull requests from forks run with a read-only token and cannot publish, and GitHub asks for approval before
running one from a first-time contributor. Published packages are covered by each program's license. Their exact
sources are pinned in `packages/`, beside the patches applied to them.

## Adding a package

1. Create `packages/<name>/build.sh`. A recipe in [termux-packages](https://github.com/termux/termux-packages)
   is the best starting point.
2. Add patches beside it as `0001-*.patch`, with paths that apply using `-p1` from the source root.
3. Run `python3 tools/recipes.py check-patches <name>`.
4. Add the package to an overlay's `packages/termux.yaml`, or to
   [`src/native/packages.txt`](../src/native/packages.txt) if the desktop needs it.
5. Run the workflow with `packages=<name>`.

## Status

The original native GNOME source port passed device acceptance (see
[native verification](native/VERIFICATION.md)). Those results do not establish that the new package recipes
cross-compile or that installation of the new release works on a phone.

The standardized packaging path has host checks for source patch application,
build ordering, upstream recipe staging, Code OSS desktop metadata, and runtime
migration. It still requires complete Termux builds, package installation and
device acceptance before release. No new release or device deployment is implied
by these changes.

The specialized browser/video work, the optional glibc Mixtapes token helper,
and profile-specific themes/add-ons retain their separate purposes. The Debian/PRoot
profile and its backend have been removed; `livecd` and `livecd-native` both run
the native desktop.
