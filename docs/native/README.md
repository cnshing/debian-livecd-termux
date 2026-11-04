# Native Termux desktop

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

This profile runs GNOME 48 and its applications directly on Android/Bionic in
Termux. **Its startup, terminals and applications do not use PRoot.** A stored
Debian installation is optional recovery data, and stays stopped during native use.

The implementation targets the established arm64 Note10+ / Android 11 rig with
the standard `com.termux` prefix and the Termux:X11 Android app. Other devices and
Android versions need their own validation. See [device results](VERIFICATION.md).

[Shared application acceleration](ACCELERATION.md) adds separate native/glibc
video drivers and application profiles to the existing Turnip/Zink renderer.
It is applied on the phone with runtime tests explicitly disabled; Firefox/mpv
decoding is configured but unverified, and Chromium needs the VA-API-enabled build.

## Install and run

> **This install flow has not run yet.** `install.sh` needs a release from GitHub Actions, and none exists.
> [Device results](VERIFICATION.md) describe the earlier on-device flow, which is kept in
> `.backup/pre-restructure.tar.gz`. The test phone itself now runs the
> GNOME source port, built on the phone ([verification](VERIFICATION.md)).

In native Termux, from this repository:

```sh
# Stop whichever managed desktop is running before installation or updates.
~/.local/bin/livecd stop
bash install.sh
~/.local/bin/livecd-native start
~/.local/bin/livecd-native validate
~/.local/bin/livecd-native select

# Once selected, these commands use the native backend.
~/.local/bin/livecd start
~/.local/bin/livecd status
~/.local/bin/livecd stop
~/.local/bin/livecd start --safe
```

On a new phone, omit the first stop command if no desktop is installed. Install
the Termux:X11 Android APK separately. Setup fetches this project's latest release into a local
apt repository, or uses `--repo-tarball FILE`, installs the packages, connects the packaged runtime,
applies the overlays and audits the recursive ELF dependency closure. It rejects a running session.
`select` runs the native core validation before saving the renderer as the default.

From the PC rig, use the currently connected serial from `adb devices -l`:

```sh
PHONE_SERIAL=CONNECTED_SERIAL bash tools/rig.sh setup
PHONE_SERIAL=CONNECTED_SERIAL bash tools/rig.sh start
PHONE_SERIAL=CONNECTED_SERIAL bash tools/rig.sh validate
PHONE_SERIAL=CONNECTED_SERIAL bash tools/rig.sh select
```

`rig.sh setup` installs this profile. `LIVECD_REPO_TARBALL=FILE` installs a tarball you already have.

## Runtime and build provenance

The normal installer now uses the source-built GNOME 48 recipes in
[`packages/`](../../packages): mozjs-128 128.14.0, GJS 1.84.2, Mutter 48.8 and
Shell 48.8. APT owns their files under `$PREFIX/opt/gnome-48`. The usual
`~/.local/opt/livecd-native/gnome-48` path is a compatibility link. Runtime
selection and per-user profile data stay separate from package ownership.

The source archives and patches come from the independently tested native
source port. Its successful device results do not establish that the new package
recipes cross-compile or that installation of the new release passes acceptance.
See [the package source contract](../../packages/livecd-gnome-runtime/SOURCES.md).

`livecd-desktop` owns the session controller and commands. `livecd-gnome-runtime`
supplies the session and additional schemas; `livecd-gnome-data` and its font
subpackage supply portable assets. GJS, GIR/typelibs and the X11 frame client
are built with their matching sources. The default installer no longer uses the
GI adapter, frame-only replacement, GNOME-Termux executable bundle, `patchelf`
repair or generated-typelib repair.

The remaining `prebuilt/gnome-runtime/` files describe the older bootstrap.
Historical troubleshooting and device evidence below may refer to that path.
Official Termux APT dependencies remain rolling packages; the builder and image
are pinned together in `tools/termux-build.json`.

## Desktop behavior

The profile carries ArcMenu, Dash to Panel, DING, AppIndicator, User Themes,
NoAnnoyance, Tiling Assistant and the owned appearance extension. It uses the
repository's WhiteSur/Colloid assets, wallpapers, font choices, lock restrictions
and startup preferences. Fonts and extension data taken from Debian packages
are architecture-independent assets; Debian executables and libraries are excluded.

Native Nautilus, [Code OSS](../code-oss/README.md), elementary Code, Firefox with signed uBlock Origin,
LibreOffice, mpv-x and [Mission Center](../mission-center/README.md) provide the application workflows.
elementary Code carries the liveCD's theme-sync plugin, which matches its editor colors to the GTK theme
when Code starts; after a theme change, Code shows the new colors from its next start.
Ghostty is the only terminal, with its existing close-button limitation. It uses its package's own launcher and
starts a login shell (`temp/docs/evidence/native/stock-launchers.txt`). Ghostty reads
`~/.config/livecd-native/ghostty/config.ghostty`, which installing keeps, and which
loads the theme from `appearance.ghostty`, which installing replaces.
Nautilus offers **Scripts → Open in Terminal**, passing
decoded local URIs as arguments. Native image thumbnails use FFmpeg because the
official packages do not supply a usable PNG/JPEG thumbnailer here.
The installer pins uBlock's signed 1.67.0 bootstrap XPI; normal Firefox extension
updates remain enabled, and the final device check recorded signed 1.75.0.

```sh
livecd-native terminal "$HOME/Documents"
livecd-native exec -- nautilus "$HOME/Documents"
livecd-native exec -- missioncenter
```

The terminal command can open an independent recovery terminal when GNOME is
stopped, provided Termux:X11 is already running. It uses Ghostty and a
private bus. Native terminals never enter Debian.

[EasyEffects/AutoEq](../audio/README.md) and [GSConnect](../gsconnect/README.md)
remain separately installed opt-in native components. Their existing launchers
use the original native component profiles and shared Termux libraries, avoiding
CJS/GJS library mixing. `livecd-audio exec -- APPLICATION` preserves the native
desktop's settings and session bus while selecting the effects audio endpoint.
Opening a settings window does not route every application through
the effects graph or establish GSConnect Shell-panel integration.
[Chromium, Google Chrome and Firefox's other extensions](../browsers/README.md) are also a
separate opt-in port, and appear in this desktop's menu once installed.
[Mixtapes](../mixtapes/README.md) is another, with its own menu entry.

## Session integrations

Normal `livecd start` on the native backend starts installed optional integrations
through their existing commands after GNOME is ready:

| Integration | Startup action |
| --- | --- |
| Microphone / Bluetooth | Try `livecd-mic-bluetooth on --default`; if unavailable, use `livecd-mic on` |
| EasyEffects | `livecd-audio start` against the desktop's PulseAudio socket |
| GSConnect | `livecd-gsconnect start` on its existing private bus |
| Whole-device resources | `livecd-resources-setup` stages the existing Shizuku reader; clients activate it on demand |

The packages, Android microphone permission and Shizuku authorization must already
be installed/configured. Connect the headset in Android with **Calls** enabled
before startup. Bluetooth is tried once per desktop start; reconnecting later uses
the existing manual commands. An already enabled microphone is preserved.
GSConnect starts listening on the LAN, using its existing pairing settings.
EasyEffects keeps its existing behavior: use `livecd-audio exec -- APPLICATION`
to send an application through the graph. Starting it does not redirect all applications.
Battery/UPower and saved graphics/video acceleration already follow the desktop's
existing startup path; no new acceleration settings are selected.

These startup actions run in the background. An unavailable optional feature does
not prevent GNOME from opening. `livecd status` includes their startup results
under `integrations`; use each feature's own status command for its current health.
The hook log is `~/.local/state/livecd-native/integrations.log`.
`livecd stop` stops desktop-owned integrations before PulseAudio and the buses.
Services already running outside this desktop are reused and left running.
`livecd start --safe` skips the optional startup hooks.

Installed integrations start by default. To disable individual hooks, create
`~/.config/livecd-native/integrations.json`, for example:

```json
{"microphone": false, "gsconnect": false}
```

Supported keys are `microphone`, `bluetooth`, `audio`, `gsconnect`, and `resources`.
Disabling `microphone` also disables Bluetooth microphone startup; disabling only
`bluetooth` leaves ordinary microphone startup enabled. The `resources` key
controls reader staging; `LIVECD_RESOURCES_COMPAT=0` still controls the existing
session preload. Restart the desktop to apply changes.

## Icons

Applications can lose their icons here, but **rarely because icon files are missing**: all 29
visible menu entries resolved an icon when checked. The following causes were found.
This repository now fixes all but the second.

These fixes were confirmed on the phone that night (results (`temp/docs/evidence/native/icon-fixes.txt`),
desktop (`temp/docs/evidence/native/icons-desktop-after-fixes.png`)). They were applied directly to its installed
files, because the phone is still on the older install layout. **`install.sh` and `prepare.py` have not yet
run with them.** The measurements after "Generic dock icon" were taken before the fixes.

| What you see | Cause | What to do |
| --- | --- | --- |
| A generic gear icon in the dock, beside the application's pinned launcher | GNOME Shell could not match the window to a desktop entry | Fixed for windows started from the panel or menu by [a Shell patch](../../packages/livecd-gnome-shell/0205-retain-startup-apps.patch), below |
| Placeholder glyphs inside a window, such as a page with a warning sign on its buttons | The application started outside the desktop's environment, so it cannot find the theme | Start it through the menu or `livecd-native exec` |
| No icons on the desktop | DING crashes at startup: its code calls `GLib.unix_signal_add`, and the session log shows `TypeError: GLib.unix_signal_add is not a function` | Fixed by [a DING patch](../../prebuilt/gnome-runtime/patches/gnome-shell-extension-desktop-icons-ng/0003-glib-2.90.patch) |
| Missing icons in ArcMenu, and a `C` from the theme as its button | Debian's package leaves out the `icons/` directory the extension loads from | [`prepare.py`](../../prebuilt/gnome-runtime/prepare.py) restores them from ArcMenu's source |
| No status icons or quick settings menu in the panel | Shell attaches its indicators only after creating them all, and one needs a missing schema, `org.gnome.settings-daemon.peripherals.touchscreen` | [`prepare.py`](../../prebuilt/gnome-runtime/prepare.py) adds that schema |
| No Trash icon on the desktop, and `trash:///` fails | `gvfs` is not installed | The `File Manager` overlay installs it |

**Generic dock icon.** Shell 48 tries the window's class (`StartupWMClass`, then a desktop file named after
the class), then its sandbox ID, `_GTK_APPLICATION_ID`, other windows of the same process, its startup ID
and its window group. A window that matches none of these gets the generic icon.

The startup ID ties a window to its launcher whatever its class is. Shell compares it only with active
startup records, though, and Firefox and LibreOffice Base end theirs before their visible window appears.
[`0205-retain-startup-apps.patch`](../../packages/livecd-gnome-shell/0205-retain-startup-apps.patch)
keeps the launcher behind each ID for the rest of the session, which fixes this for every application
without any per-application data. With it and no per-application entries, all 23 menu entries
tested (`temp/docs/evidence/native/window-tracker-census.txt`) avoided the generic icon: 21 landed on their own
launcher, and two Thunar tools on Thunar's entry.

Two limits remain. A window with no launcher behind it, such as `firefox` started from a terminal, still
gets the generic icon if its class matches nothing. And the patch exists only in the source port, so a
runtime built from the prebuilt bundle still shows Firefox with the generic icon.

Firefox is the case that remains. Official Termux's Firefox 159 has `RemotingName=firefox-default`, so its
windows have the class `firefox-default`, but the same package's `firefox.desktop` declares
`StartupWMClass=firefox`. Without the patch nothing matches, so the running window gets a separate generic entry.

Still open after the fixes:

- With six taskbar entries, the last one slides under the status icons, as
  Ghostty's did (`temp/docs/evidence/native/icons-panel-ghostty.png`).
- The dock's pins changed from GNOME Terminal and GNOME Text Editor to Ghostty and Code OSS, and the new pins
  have not been seen on the phone.
- Chromium's first-run terms dialog sets no `WM_CLASS`, so it depends on its startup ID. One copy on the
  desktop had none and showed the generic icon, and what started that copy is not known. Launched from the
  panel it had one and matched (`temp/docs/evidence/native/window-tracker-census.txt`).
- Home and Trash were missing from two captures of the source-built 48.8 desktop and present in a later one,
  with DING's window present throughout. The cause has not been established.

Before the fixes, [`test-window-icons.py`](../../tests/native/test-window-icons.py) opened real applications with scratch profiles: **15 of 17
windows matched** (output (`temp/docs/evidence/native/window-icons.txt`)). A smaller re-run after them (`temp/docs/evidence/native/window-icons-after-fixes.txt`)
matched Firefox and the Ghostty menu entry through `StartupWMClass`; its one unmatched window is Mutter's internal `mutter-x11-frames`. The full sample has not been repeated. This was reported as affecting many applications,
and the sample found these two, so others may remain among what it left out. It estimates Shell's matching
rather than asking Shell, which refuses `GetWindows` to outside callers. It skipped the EasyEffects and
GSConnect launchers, which start an audio graph and a LAN listener, along with most LibreOffice entries.
A window with no desktop entry at all, such as a test script's, always gets the generic icon.

A later census (`temp/docs/evidence/native/window-tracker-census.txt`) asked Shell's tracker directly on a private
display, launching menu entries the way the panel does. Before the patch, 20 of 21 landed on their own entry,
in a run stopped early that did not reach 7 entries.

Firefox's own `_NET_WM_ICON` holds the correct logo, yet the dock still showed the generic icon. That is
Shell 48's behaviour, not a fault here: `shell_app_get_icon` returns `application-x-executable` for every
window it cannot match, and ignores the window's own icon.

**Placeholder glyphs.** The desktop's XSETTINGS name the `Colloid-Yellow-Dark` theme, which is
installed under `~/.local/share/livecd-native/icons`. Only the session's `XDG_DATA_HOME` points there.
An application started from a plain Termux shell on the same display gets the theme's name but not its
directory: it resolved 6 of 9 sample icons, against 9 of 9 through `livecd-native exec`. Overriding
`XDG_DATA_HOME` for one application has the same effect. To isolate an application's data without
hiding the theme, add the session's value to `XDG_DATA_DIRS`, as
[Mixtapes' tests](../../tests/mixtapes/test-mixtapes.py) do.

**Theme coverage is not the cause.** `Colloid-Yellow-Dark` inherits `hicolor` and `breeze`, not Adwaita,
and `breeze` is not installed. Even so, 562 of Adwaita's 587 symbolic icons resolve. The other 25 are
mostly emoji faces, and a search of the Nautilus, Text Editor, libadwaita and GTK binaries found none of
them requested. Icons compressed inside an application's resources would not show up in that search.

## Native Turnip + Zink

The Note10+ Adreno 640 has an optional native GPU profile. A fresh install still
defaults to software rendering until a renderer is explicitly selected. The GPU
profile uses official Termux's Bionic Turnip 26.2.6 and the installed native Mesa
Zink driver. It runs entirely outside PRoot.

```sh
# Run from this checkout in an independent native Termux shell.
livecd stop
python prebuilt/turnip/gpu-setup.py
livecd start --renderer zink
livecd validate
# Persist the currently running, validated renderer and native backend.
livecd select
```

`gpu-setup.py` verifies the package hashes in `gpu-sources.lock.json` and stages
the driver and Vulkan tools under `~/.local/opt/livecd-native/gpu-26.2.6`, selected
by the owned `gpu` symlink. It checks native dependencies and rejects an active
desktop. Shared Mesa and the system Vulkan configuration remain under APT.
This private staging also works while an unrelated APT download holds its lock.

The GPU profile selects Turnip explicitly, clears inherited software overrides,
and uses Zink for OpenGL. `COGL_DRIVER=gles2` selects Mutter's EGL/GLES compositor
path; its GLX path produced black application windows on this rig. GTK4 uses its
GL renderer. GPU sessions start Termux:X11 without `-legacy-drawing`; software
sessions retain the earlier display configuration. This does not establish a
zero-copy display path or hardware video decoding.

Recovery and per-application overrides stay native:

```sh
livecd stop
livecd start --safe                # Software rendering; extensions disabled.
livecd stop
livecd start --renderer software   # Normal desktop with software rendering.
# Optional: persist software as the default again.
livecd select

# In a running desktop, choose the renderer for a new client process.
livecd exec --renderer zink -- glxinfo -B
livecd exec --renderer software -- APPLICATION
```

Existing application instances and D-Bus services retain their original
environment. Restart the desktop to change its compositor and activation
environment together. `livecd status` reports the active renderer; a conflicting
`start --renderer` request asks for a stop first. `--safe` always uses software,
even when Zink is the saved default. Standalone recovery terminals also use
software rendering.

GPU frames can be absent from X11 framebuffer readback. Capture the compositor
directly, or use the rig's Android screenshot while Termux:X11 is visible:

```sh
livecd exec -- python src/native/capture.py "$HOME/Pictures/native-desktop.png"
livecd exec -- python tests/native/test-gpu.py
```

The GPU test opens real GTK, Ghostty, mpv, Vulkan cube and GLX animation windows,
checks their actual Turnip mappings and KGSL descriptors, and exercises a minute
of rendering and overview transitions. See [GPU verification](GPU-VERIFICATION.md)
for accepted results and remaining limits.

LAN hostname lookups follow Android's DNS configuration. The
[LAN hostname investigation](LAN-HOSTNAMES.md) records working LAN DNS with
Private DNS off, the phone's separate `.local` resolution failure, the stock GVfs
backend limitations, and the separate glibc resolver configuration. The
[project network packages](../network/README.md) add verified SMB access and
DNS-SD discovery on this rig.
[Shared storage and microSD checks](STORAGE.md) describe the ADB permission
grants and verified native desktop read/write access on this rig.

## Reproduce validation

With the native desktop running, from this checkout in native Termux:

```sh
livecd-native validate
livecd-native exec -- python tests/native/test-apps.py
livecd-native exec -- python tests/native/test-terminal.py
livecd-native exec -- python tests/native/test-thumbnails.py
livecd-native exec -- python tests/native/test-media.py
livecd-native exec -- python tests/native/test-appearance.py
```

The application tests use disposable fixtures under
`~/Documents/livecd-native-validation` and save evidence under
`~/.local/state/livecd-native`. Appearance validation temporarily switches the
profile's theme and accent and restores its previous settings. Run the lifecycle
and recovery-terminal tests from an independent native Termux shell, since
desktop shutdown also terminates processes launched through its environment:

```sh
livecd-native stop
python tests/native/test-lifecycle.py
python tests/native/test-standalone.py
livecd-native start
```

The lifecycle test performs ten cycles, then Shell crash recovery and safe-mode
checks. The recovery-terminal test starts and stops its own X11 fixture server
with the desktop stopped.

## State, data and recovery

Private GNOME libraries live in `~/.local/opt/livecd-native/gnome-48`; profile
configuration and data live in `~/.config/livecd-native` and
`~/.local/share/livecd-native`. Logs and evidence inventories are in
`~/.local/state/livecd-native`. Shared document directories stay under the real
Termux home. The selected Firefox profile is private to this desktop.

The owner shares the existing setup/session lock, creates private session and
compatibility buses, uses a Unix PulseAudio socket, and removes its own tagged
children on shutdown. The compatibility system bus supplies no privileged
services; its one service is [UPower](../battery/README.md), which reports the
battery. Android remains responsible for locking, power and network policy.
Software rendering remains the recovery baseline. The GPU profile above uses
native Bionic drivers; Debian GPU libraries cannot be loaded here.

Before the first dependency installation, setup saves native package/settings
inventories and a prefix archive under `~/.local/state/livecd-native/baseline`.
The archive excludes stored PRoot guests and temporary files. It is a recovery
artifact, not an automatically tested host restore. It cannot undo arbitrary
shared Termux package upgrades.

## System resource access

The System Monitor overlay installs the [shared resource backend](../resources/README.md).
With this controller version installed, after `livecd-resources-setup` and a desktop restart, native session applications inherit its
on-demand `/proc` and supported `/sys` compatibility layer. This enables whole-device CPU
and Android process data in ordinary monitors, including `top`, `htop` and libgtop clients.
The reader has no sampling timer. To disable interception for a session, start it with
`LIVECD_RESOURCES_COMPAT=0`; Mission Center can still use the shared library directly.
The source changes have been tested with standalone clients; the complete desktop startup
with interception enabled has not been run.
