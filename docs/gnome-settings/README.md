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

Screen time does not work yet. Shell's time-limits manager needs logind's user
`State` and `IdleHint`. This session has no `org.freedesktop.login1`, so Shell
falls back to its dummy login manager. That manager's `getCurrentUserProxy()`
never resolves, and Shell's screen-time state machine stops after recording the
session start:

- The Screen Time chart counts every hour since Shell started, idle time included.
- Shell never sends the notifications that apply **Screen Time Limit** and its
  grayscale option, so they have no effect.

The fix belongs in `livecd-gnome-shell`, not in this package: a dummy user whose
`IdleHint` follows the session idle delay. Until then, these Screen Time
controls must not be described as working.

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
Settings set does not rebuild Shell, Mutter or GJS.

In the running native session:

```sh
python tests/native/test-settings.py
# Also exercises real resolution changes, keep/cancel and the 20-second rollback:
python tests/native/test-settings.py --resolution
# Close Settings first; this opens/closes every compiled panel with fatal criticals:
python tests/native/test-settings.py --panels-ui
```

The notification test checks the owning service, notification submission and
preference access. The Wellbeing test turns on a break schedule and waits for
Shell's break manager to report it. Manual UI acceptance also confirmed a visible banner with banners enabled and
suppression with Do Not Disturb enabled. Per-application and lock-screen policies
still require further UI acceptance. The resolution test restores
the original preferences in a `finally` block.

Device validation so far: the package builds/installs on arm64 Android 11; the ten
panels before Wellbeing open and close with fatal GLib criticals enabled; resolution changes to 1280×720, confirmation, cancel,
parent-pipe loss and timeout restore passed without restarting GNOME. The GUI
chooser, confirmation and automatic dismissal after rollback were visually
inspected. Existing appearance lifecycle/accent tests passed. The port also fixes
missing template type registrations and deferred sidebar/window work after
disposal, discovered by the panel smoke test. The Wellbeing panel was opened and
inspected on a private Xvfb display. Break-schedule changes reach Shell. The
`--panels-ui` run has not yet been repeated with Wellbeing, since it opens
windows on the live display. Broader panel functionality remains unfinished.
