# GNOME Settings on native Termux

`packages/gnome-control-center` builds GNOME Control Center 48.7 and the pinned
Tecla 48.0.2 keyboard layout previewer. It uses the ordinary Termux libraries and
the existing GNOME 48 session. It neither upgrades GNOME Shell nor changes
Android settings for notifications or device power.

## Current implementation and remaining scope

The package builds Appearance, Displays, Notifications, Apps, Sound,
Multitasking, Search, Mouse & Touchpad, Keyboard, Accessibility, Wellbeing,
Privacy & Security and System. Opening a panel is not evidence that every switch
has an effective backend; the sections below say what each one controls.

The agreed exclusions are Network/Wi-Fi/mobile networking, Bluetooth, Users,
Power and Night Light. The existing Shell battery indicator and UPower backend
remain independent of the excluded Power page.

These upstream panels and pages are also left out, because nothing on an
unrooted phone would act on them:

| Panel or page | Reason |
| --- | --- |
| Color | Termux:X11 gives its one virtual output a 256-entry RandR gamma table but no `rrCrtcSetGamma` handler, so gamma ramps are stored and never applied. It publishes no EDID. External monitors are composited by Android's SurfaceFlinger, whose color transforms an app cannot set. |
| Wacom | The S Pen arrives as the **Lorie pen** and **Lorie eraser** X devices. Mutter's X11 tablet settings write only the `xf86-input-wacom` properties (`Wacom Tablet Area`, `Wacom Rotation`, `Wacom Pressurecurve`, `Wacom Pressure Threshold`). The Lorie devices have none of them, so every Wacom control would be a no-op. |
| Region & Language (System) | Termux packages ship no GTK or Settings translations, and Bionic's `setlocale()` rejects locales such as `fr_FR.UTF-8`, so neither the language nor the formats could change. |
| Remote Desktop (System) | GNOME Remote Desktop is not packaged. |
| Sharing | GNOME User Share and Rygel are not packaged, and Avahi runs with publishing disabled, so its device name would not reach the network. |
| Screen Lock, Location, Cameras (Privacy) | Android owns locking; the native profile locks the GNOME lock and idle keys. No GNOME component here reads the location or camera switches. |
| Diagnostics, Thunderbolt, Device Security (Privacy) | ABRT, bolt and fwupd do not exist on Android. |

Online Accounts and Printers are skipped for now. They would need packages this
repository does not have: GNOME Online Accounts and `librest`, and GTK print
backends for CUPS.

The package is not yet added to the default desktop overlay.

## Displays

Mutter's `org.gnome.Mutter.DisplayConfig` describes the virtual X11 output.
Termux:X11 normally publishes only its current size. A phone test demonstrated
that adding RandR user modes and applying one through Mutter can terminate Shell:
Termux:X11's CRTC callback rejects the temporary disabled-CRTC step used by that
apply sequence. Those user modes are not installed by this package.

Instead, **Displays → Desktop Resolution** opens a resolution chooser using
`termux-x11-preference`. Automatic mode follows the Android window size; the
fixed choices are 1280×720, 1600×900, 1920×1080 and 2560×1440. These are desktop
rendering sizes, not physical display modes or refresh-rate controls.

The chooser requires confirmation within 20 seconds. A separate subprocess
restores the previous Termux:X11 preferences on timeout, cancellation or loss of
the parent UI process. It preserves a subsequent independent preference change
made in the Android app. Existing custom/exact/scaled preferences are restored
when a change is rejected. Only the resolution mode and custom size are written;
other Termux:X11 preferences are left alone.

The stock resolution/refresh information remains visible. Rotation, scaling and
output-disable controls for the virtual `builtin` output are suppressed because
they would use the failing Mutter apply path. Fractional/integer display scaling,
physical refresh-rate selection and external-monitor layout are not validated.
Text scaling through the existing XSettings bridge is a separate setting.

## Wellbeing

Wellbeing edits `org.gnome.desktop.break-reminders` and
`org.gnome.desktop.screen-time-limits`. Break reminders work: GNOME Shell's
break manager uses Mutter's idle monitor, and it reports the schedule state on
`org.gnome.Shell.ScreenTime`.

Screen-time accounting requires `livecd-gnome-shell` and
`livecd-gnome-runtime` **48.8-1 or later**. Earlier builds wait indefinitely for
logind's user proxy, count idle time as active and never apply daily limits.

The native Shell adapter supplies only session activity to the time-limits
manager. It watches Mutter's input idle monitor: after 60 seconds without input,
usage becomes inactive; new input resumes accounting. The threshold is separate
from screen blanking, so the native profile's locked `idle-delay=0` does not
prevent idle time from being excluded. The adapter is event driven and cached
for the Shell lifetime; it grants no user, authentication or power privileges.

A private software-rendered Xvfb/Shell test verified daily-limit notification,
grayscale on reaching the limit, removing those effects, and active/idle history
transitions. This measures **GNOME desktop activity**, not Android application
usage. Android background/suspend behavior is not a source of lifecycle events
for this adapter. Old history is retained; previously overcounted usage is not
retroactively corrected. Disabling screen-time recording clears its saved
history through the existing GNOME controls.

## Notifications and appearance

Notifications edits `org.gnome.desktop.notifications` and its per-application
settings. GNOME Shell implements desktop banners, Do Not Disturb and the message
tray. No Android notification bridge, notification permission or notification
listener is added. Existing optional phone-sync integrations have their own
configuration.

Per-application portal permission synchronization uses the upstream optional
session PermissionStore service. Its absence does not prevent ordinary desktop
GSettings policies from working. Lock-screen controls still need validation
against the port's session-lock support.

Appearance writes the existing GNOME color-scheme, accent and background keys.
The existing `livecd-appearance@local` extension handles WhiteSur/Colloid changes,
and the XSettings bridge forwards GTK theme/font/icon/cursor preferences to X11
applications. Arbitrary theme selection is not a stock Appearance feature.

Every accent selects a matching WhiteSur theme and Colloid icon theme, as in the
Debian LiveCD's accent extensions. Slate uses WhiteSur's and Colloid's grey;
WhiteSur has no teal, so teal uses its default accent. The theme hook installs
all Colloid colors, about 28 MB each beyond the shared base. Earlier installs had
only the default (blue) and yellow, so every other accent fell back to blue
icons. The next overlay application adds the missing colors; until then, the
extension keeps the default icons for an accent whose theme is absent.

## System

System contains About, Date & Time and Secure Shell. Users, Region & Language
and Remote Desktop are left out (see above). Software Updates stays hidden
because GNOME Software is not installed.

**About** reads Android rather than systemd's hostnamed, UDisks and DMI. It
shows the manufacturer and model as the device name, `Android` with the release
from `ro.build.version.release`, the SoC from `/sys/devices/soc0` with the
number of configured CPUs, libgtop's memory total and the size of the data
partition holding the Termux home. The device name is read-only: Android's own
device name is not readable by apps, and nothing here would use a new one. In
System Details, the firmware version is the bootloader (`ro.bootloader`) and the
OS build is `ro.build.display.id`.

**Date & Time** shows Android's date, time and time zone read-only, marked
**Set in Android settings**. Without timedated there are no automatic time or
time zone switches. Termux has no `zone.tab`, so the time zone is shown from
GLib's local zone, for example **PST (Los Angeles)**. Time format, the top bar
clock's week day, date and seconds, and calendar week numbers are ordinary
GNOME settings and do change the Shell clock.

**Secure Shell** controls Termux's OpenSSH listener instead of a systemd unit.
The switch reflects whether the process in `$PREFIX/var/run/sshd.pid` is
`sshd`; turning it on runs `sshd`, and turning it off sends that listener
SIGTERM. OpenSSH 10 runs each connection as a separate `sshd-session` process,
so established sessions survive, as with systemd's unit. Nothing restarts the
listener when Termux or the desktop restarts. The login command is
`ssh -p PORT ADDRESS`, using `Port` from `sshd_config` (Termux's default is 8022)
and the Wi-Fi IPv4 address, else another non-cellular one. Sign in with the
password set by `passwd` or an authorized key. A custom `PidFile` in
`sshd_config` is not followed.

## Privacy & Security

Privacy & Security contains File History & Trash. File History and its duration
write `org.gnome.desktop.privacy`; GTK reads them only through XSettings, so the
desktop's XSettings bridge (`src/native/xsettings.py`) now forwards them as
`Gtk/RecentFilesEnabled` and `Gtk/RecentFilesMaxAge`, as GNOME's own XSettings
daemon does. The running desktop picks up the bridge change when it restarts.
**Clear History** empties GTK's recent files list.

Upstream empties the trash, deletes temporary files and purges both on a
schedule through Settings Daemon's housekeeping service, which is not running.
**Empty Trash** therefore runs `gio trash --empty` directly. Automatic purging
and temporary file deletion are left out; Termux's temporary directory also
holds the running desktop's sockets.

## Wallpaper collection and microphone devices

The Theming overlay includes all 52 wallpapers and their attribution file from
the upstream revision recorded in `overlays/UPSTREAM`. On Termux, the overlay
applier copies them to `~/.local/share/livecd-native/backgrounds`, rather than
Android's unavailable `/usr/share/backgrounds`. Its registration hook generates
`~/.local/share/livecd-native/gnome-background-properties/livecd.xml` with native
absolute filenames. GNOME Appearance reads catalogs in `XDG_DATA_HOME`; merely
copying images into a backgrounds directory does not register them. The hook
refreshes its own catalog and preserves other wallpaper catalogs. Reopen Settings
after adding a catalog.

Choosing a single image in Appearance sets it for both the light and dark styles,
as upstream GNOME does. The catalog therefore starts with **LiveCD default**, the
profile's light/dark pair (`fakurian/unsplash-7Ra7YDFR4Pw.avif` and
`heberdavisphotography/unsplash-ewW6dPCL_Vw.avif`), so that pair can be chosen
again. The hook reads the pair from the profile's dconf defaults. Device checks verified all 52 Appearance entries and AVIF/
JPEG preview decoding.

Sound uses PulseAudio's existing source notifications, including cardless OpenSL
and Bluetooth bridge devices. It does not pair or discover Android Bluetooth
hardware itself. The existing Microphone overlay supplies `livecd-mic` and
`livecd-mic-bluetooth`; these must publish a source before Sound can list it.
`livecd_no_microphone` is an intentional silent fallback, not the phone's microphone.

The current desktop controller starts installed microphone integrations in normal
sessions: it tries any Android-reported Bluetooth call headset, then falls back
to the phone microphone. Both hooks can be disabled in the integration settings.
Older manually staged desktop controllers lack this startup integration. Discovery
runs at desktop startup or when `livecd-mic-bluetooth on --default` is invoked;
there is no continuous headset-connect/reconnect watcher. Pair and enable Calls in
Android. The bridge has no WI-C310-specific device filter. See
[the microphone guide](../mic/README.md) for permission and Shizuku requirements.

On the phone, enabling `livecd-mic` produced a visible **Microphone** input and
level meter in Sound. With an Android-connected WI-C310, the bridge produced
visible **WI-C310 Headphones** and **WI-C310 Microphone** controls in Sound.
The Bluetooth source also delivered 96,000 samples in a two-second capture probe;
the probe discarded the audio. The older test-phone controller's missing
integration hook and component helper were staged for its next start, with
backups; its running desktop was kept alive. The startup integration recognized
and reused the active headset without claiming ownership of its controller.
These checks cover device discovery, sample delivery and the input meter, not a
new end-to-end call-quality test. Only one Android microphone route is exposed
at a time, as intended: phone microphone or Bluetooth call microphone.

The wallpaper update and catalog regression check passed the single
[Settings build set](https://github.com/cnshing/debian-livecd-termux/actions/runs/41804013338)
at source revision `a0207b2`. All 52 wallpaper files were checked against their
Git blob hashes at the pinned upstream revision before inclusion.

## Build and validate

```sh
bash tools/build-packages.sh gnome-control-center
python3 tools/recipes.py check-patches gnome-control-center
```

For one GitHub Actions build set, without a release or unrelated package builds:

```sh
gh workflow run packages.yml --ref BRANCH -f packages=gnome-control-center -f rebuild=true
```

The planner produces exactly one build set, `gnome-control-center`. Runtime
`upower` dependencies can be satisfied by the existing Android-backed package;
the Settings package does not require replacing or unholding the phone's UPower.
The packaged GNOME runtime is recommended, rather than a build dependency, so the
Settings set does not rebuild Shell, Mutter or GJS. The Shell/runtime change
has a separate GNOME runtime build set; select `livecd-gnome-runtime` to build it.

In the running native session:

```sh
python tests/native/test-settings.py
# Also exercises real resolution changes, keep/cancel and the 20-second rollback:
python tests/native/test-settings.py --resolution
# Close Settings first; this opens/closes every compiled panel with fatal criticals:
python tests/native/test-settings.py --panels-ui
# Decode every registered LiveCD wallpaper preview:
python tests/native/test-settings.py --backgrounds-only
# Run a separate software-rendered Shell with temporary settings/history:
python tests/native/test-screen-time.py --panels-ui
# Check About, Date & Time, Secure Shell and File History & Trash on a private display:
python tests/native/test-system-panels.py
# Also turn Termux's real sshd off and on with the switch (open sessions survive):
python tests/native/test-system-panels.py --sshd
# Unit checks for idle/resume and watch cleanup, in the GNOME 48 GJS environment:
gjs -m tests/native/test-session-activity.js
```

The private screen-time test checks actual Shell banners, per-application banner
suppression, Do Not Disturb and disabled applications. The session test also
checks notification service ownership and turns on a break schedule, waiting for
Shell's break manager to report it. Lock-screen notification policies still need
validation. The resolution test restores the original preferences in a `finally`
block.

`test-system-panels.py` runs Settings on its own Xvfb display, session bus and
AT-SPI bus, with temporary configuration and data directories, so its switches
and its trash do not touch the desktop's. It compares About with Android's
properties, `/sys/devices/soc0` and `statvfs()`, and checks that Date & Time is
read-only, its clock switches write GSettings, Privacy hides the unsupported
pages, Empty Trash empties a trashed test file, the XSettings bridge changes
GTK's recent-file settings, and the SSH login command and switch match `sshd`.

The System and Privacy panels were validated on the arm64 Android 11 phone
with a local build: `test-system-panels.py --sshd` passed, including stopping
and restarting the real listener from the switch while the SSH session running
the test stayed connected. With the extracted CI runtime,
`test-screen-time.py --panels-ui` opened and closed all thirteen compiled panels
with fatal GLib criticals. The About, System Details, Date & Time, Secure Shell
and File History & Trash pages were inspected in screenshots. GitHub Actions passed
the single [Settings build set](https://github.com/cnshing/debian-livecd-termux/actions/runs/41812177976),
including the wallpaper catalog test, at source revision `3aa8686`.

Earlier device validation: the package builds/installs on arm64 Android 11, and all eleven
compiled panels open and close with fatal GLib criticals enabled. Resolution
changes to 1280×720, confirmation, cancel, parent-pipe loss and timeout restore
passed without restarting GNOME. The GUI chooser, confirmation and automatic
dismissal after rollback were visually inspected. Existing appearance
lifecycle/accent tests passed. The port also fixes missing template type
registrations and deferred sidebar/window work after disposal, discovered by the
panel smoke test. Break-schedule changes reach Shell.

GitHub Actions passed for both the single [Settings build set](https://github.com/cnshing/debian-livecd-termux/actions/runs/41798801984)
and the single [Shell/runtime build set](https://github.com/cnshing/debian-livecd-termux/actions/runs/41798806145)
at source revision `7e56fb76d3d19fd503d996b284f508f4de97428f`.
The Settings artifact installed successfully on the phone. The extracted CI
runtime passed notification policies, daily-limit notification and grayscale,
idle/resume history, break-schedule integration and all eleven panel lifecycle
checks. Process mappings confirmed that GJS, SpiderMonkey and Mutter came from
the extracted artifacts. This validates the packaged runtime in a private session;
the running desktop has not been switched to it.

The runtime acceptance test uses a fresh bus, display, settings profile and
history directory; Eval access is enabled only in that temporary Shell. Use
`--runtime DIR` to validate an extracted CI runtime without replacing the running
desktop. The harness relocates private copies of activation launchers and
reserves Mutter's fallback frame-client path exclusively, removing it afterward;
it never replaces an existing file there. Broader panel functionality remains
unfinished.
