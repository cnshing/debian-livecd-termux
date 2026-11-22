# android-legacy-dex-fullscreen

Makes Termux:X11's existing fullscreen preference hide the DeX title bar on
Samsung Android 11, using the window's Binder interface. This Termux package
runs a small shell process through Shizuku. It installs no additional Android app,
never modifies an APK, and requires neither a debuggable target nor a particular
Termux:X11 build. It does not attach an agent or access the app's private files.

`install.sh` selects the package by default on **Samsung / API 30 / ARM64**.
The runtime enforces the same gate and shell UID 2000. Verified on Note10+
SM-N975U1, firmware N975U1UES7FUI5. Hidden Android interfaces and Samsung's window
dump format vary across firmware; other builds remain unverified and unsupported
layouts are refused. If manually installed on Android 13+ (or any other unsupported
platform), every command exits successfully with `phase: unsupported`, without
starting Shizuku, creating controller state, or modifying windows. The same gate
runs before cleanup commands, so a stale session record cannot activate it after
an OS upgrade.

Requirements:

- Samsung Android 11 ARM64 and an external DeX display.
- Shizuku or Shizuku+, started and authorizing Termux, with rish exported to
  `~/.local/lib/shizuku/`. Override with `ANDROID_LEGACY_DEX_RISH` if needed.
- A focused, fullscreen Termux:X11 task with its fullscreen preference enabled.

Automatic startup requires **livecd-desktop 0.2.0-26 or newer**. Installing only
this package alongside an older desktop leaves it stopped, even after
`livecd stop` / `livecd start`; upgrade the desktop package too, or use the manual
`start` command below.

The desktop starts this optional integration automatically and stops the
controller it owns during cleanup. A separately started controller is reused
and left running. Opt out in `~/.config/livecd-native/integrations.json` with
`"dex-fullscreen": false`.

```sh
android-legacy-dex-fullscreen check
android-legacy-dex-fullscreen start
android-legacy-dex-fullscreen status
android-legacy-dex-fullscreen stop
```

## How it follows fullscreen

The shell helper uses an ephemeral UiAutomation connection to enumerate windows
across displays. It leaves the user's existing accessibility services enabled.
It only selects a focused application window whose root package is
`com.termux.x11`, on an external display. A targeted WindowManager dump must also
show DeX enabled, fullscreen task mode, and `FLAG_FULLSCREEN` set on that app's
base window. The focused accessibility window must match that base window's frame
to exclude smaller dialogs. The latter follows the app's fullscreen setting without reading
its preferences or depending on its Java classes. Maximizing a window alone
does not enable this workaround. Missing or ambiguous information is refused.

Accessibility's `getWindowToken` returns that window's live `IWindow` Binder
handle. A masked `dispatchSystemUiVisibilityChanged` callback sets `0x1002`
(IMMERSIVE_STICKY | HIDE_NAVIGATION), reaching Samsung's existing caption code.
The helper remembers which bits were absent and clears only those owned bits
when fullscreen ends, focus moves away, the window changes, or the helper stops.
Other UI flags and bits present before activation are preserved.

The helper polls every second, rediscovers recreated windows/processes, and
reapplies flags if the app resets them while still eligible. It waits while
Termux:X11 is absent and does not launch the app. DeX display IDs are discovered;
there is no fixed display number. Normal mouse/keyboard input still goes to the
original app on its original display.

Version 0.2.2 retries timed-out or incomplete window inspections, which can occur
when focus changes or an Activity is recreated, instead of terminating the helper
until the next desktop restart. Status reports `retrying-window-inspection` during
these retries. Failed restoration callbacks retain their owned bits for the next
attempt. Permission and unexpected framework errors still stop the helper.

## Lifecycle and diagnostics

The Termux controller starts one shell helper and renews its lease every three
seconds. A timed-out Shizuku request puts the controller in `recovering` and is
retried. If the outage outlasts the lease, the controller confirms the old helper's
restoration and disconnection before starting a replacement when transport returns.
The desktop does not need to be restarted. `check` reuses the existing controller
while it is recovering, rather than competing for its automation connection.

If the controller dies or Shizuku transport is lost, the helper stops
and restores its owned bits after approximately 15 seconds without renewal,
plus any in-progress lookup (bounded to several seconds). A reboot requires a
new desktop session or manual start. Normal stop waits for the helper to request restoration and disconnect
UiAutomation before reporting success. Binder/cleanup errors are reported. The
window callback is asynchronous: an unresponsive app can delay applying it.

The controller uses a private, random shell-owned directory under
`/data/local/tmp/android-legacy-dex-fullscreen.*`. It verifies the staged DEX
checksum and makes it read-only. Status, a lease, and diagnostic stack traces
live there while running. Normal stop removes this directory. Failed sessions
retain it for diagnosis; its path is recorded in the controller's session file.
No app view contents are persisted or logged: a root view dump is consumed once
per activation to read the original UI bits, and the rest is discarded.

Controller status/logs live under
`~/.local/state/android-legacy-dex-fullscreen/`. The status may lag the shell
helper by about three seconds. `check` validates the firmware, shell permissions,
Binder methods, and ability to establish UiAutomation; when already running it
uses that controller's status. Another UiAutomation client can prevent startup,
so stop this helper before using tools that require their own automation
connection. Existing ordinary accessibility services can stay enabled.

A hard kill of the shell helper itself cannot run restoration. Restarting the
app clears its window state. Regular stop, fullscreen exit, focus changes, and
controller-loss lease expiry are the supported cleanup paths. No persistent
system settings are changed.

## Upgrade from 0.1

Version 0.2 replaces the debuggable-only ART agent with the standalone shell
Binder helper. Package upgrade/removal asks the previous controller to stop.
Previously staged files inside Termux:X11 are not used by 0.2; old loaded agent
code remains idle until that app process exits. The package no longer ships a
native library or performs `run-as`/`am attach-agent` operations.

## Evidence and checks

The phone's extracted Samsung framework requires a legacy immersive bit
(`0x1800`) together with navigation-hide (`0x0002`) for its normal DeX caption.
The initial direct Binder prototype removed/restored the caption in both
Termux:X11 and the existing non-debuggable Settings app. It survived a focus
round trip, with the same root view changing from `0x0` to `0x1002` and back.
Termux:X11's APK hash stayed unchanged. This demonstrates that the mechanism
uses framework window behavior rather than a target app's debuggable status.

Version 0.2 was built into a `.deb`, installed in the phone's existing Termux,
and checked/started/stopped from that app through its exported rish client.
The packaged helper passed fullscreen on/off (including Activity recreation),
focus away/back, a Termux:X11 process restart, and stop while fullscreen remained
enabled. The same shell helper discovered the replacement app process without
attachment or app-private access. A killed-controller test also confirmed lease
expiry and shell-helper shutdown. Termux:X11's APK hash stayed unchanged.

The 0.2.2 investigation found repeated eight-second `rish` lease-renewal timeouts
in the affected phone's controller log. Earlier controllers exited on these
timeouts, leaving no controller to reapply fullscreen when the app regained focus.
On-device regression checks verified three focus round trips with UI bits changing
from `0x1002` to `0x0` and back. A deliberately delayed `rish` client then exercised
an outage beyond the helper lease: the old helper restored and stopped, and the
same controller recovered with a replacement fullscreen helper when transport
returned.

The recipe compiles all Java sources against Android 35 and converts them with
D8 at minimum API 30. There are no native agents, prebuilt helper binaries, or
target APK build inputs. Host checks cover hardware qualification, shell-only
permissions, session supervision, path validation, owned-bit restoration,
window replacement, and refusal of ambiguous/ineligible window dumps:

```sh
python3 tests/dex-fullscreen/test-controller.py  # requires a JDK
python3 tests/native/test-integrations.py
```
