# GNOME Settings on native Termux

`packages/gnome-control-center` builds GNOME Control Center 48.7 and the pinned
Tecla 48.0.2 keyboard layout previewer. It uses the ordinary Termux libraries and
the existing GNOME 48 session. It neither upgrades GNOME Shell nor changes
Android settings for notifications or device power.

## Current implementation and remaining scope

The package currently builds Appearance, Displays, Notifications, Apps, Sound,
Multitasking, Search, Mouse & Touchpad, Keyboard, Accessibility and Wellbeing. This inventory
is an initial implementation, **not completion of the requested broader Settings
port**. Opening a panel is not evidence that every switch has an effective backend.

The agreed exclusions are Network/Wi-Fi/mobile networking, Bluetooth, Users,
Power and Night Light. The existing Shell battery indicator and UPower backend
remain independent of the excluded Power page.

Other upstream panels still need porting: Color, Online Accounts, Printers,
Privacy & Security, Sharing, System (apart from the excluded Users page) and
Wacom. They are not compiled in this build. Their missing Linux
services and libraries must be handled before those panels can be considered
functional. In particular, shipping a panel must not be taken to mean Android
system time, system services or hardware devices can be administered from Termux.
The package is not yet added to the default desktop overlay while this scope is
incomplete.

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
# Run a separate software-rendered Shell with temporary settings/history:
python tests/native/test-screen-time.py --panels-ui
# Unit checks for idle/resume and watch cleanup, in the GNOME 48 GJS environment:
gjs -m tests/native/test-session-activity.js
```

The private screen-time test checks actual Shell banners, per-application banner
suppression, Do Not Disturb and disabled applications. The session test also
checks notification service ownership and turns on a break schedule, waiting for
Shell's break manager to report it. Lock-screen notification policies still need
validation. The resolution test restores the original preferences in a `finally`
block.

Device validation: the package builds/installs on arm64 Android 11, and all eleven
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
