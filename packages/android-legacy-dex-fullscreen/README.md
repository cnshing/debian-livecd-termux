# android-legacy-dex-fullscreen

Restores Termux:X11's fullscreen preference behavior on Samsung Android 11 DeX
without changing, replacing, or re-signing its APK. The package installs a native
ART agent, a small Java helper, and a Shizuku-backed supervisor.

`install.sh` selects this package by default on **Samsung / API 30 / ARM64**.
Other devices do not receive it by default. The runtime checks the same platform
gate, shell UID 2000, and `run-as com.termux.x11` before staging or attaching code.
A non-debuggable app is unsupported: the controller reports the missing feature;
it never changes the APK or attempts a privilege bypass. Firmware/class layouts
other than the verified build may be refused safely.

Requirements:

- Samsung Android 11 ARM64; verified on Note10+ SM-N975U1, N975U1UES7FUI5.
- A **debuggable** Termux:X11 APK exposing MainActivity.getFocusedOrAnyInstance,
  its effective prefs.fullscreen getter, and Samsung's caption getters. Verified
  with version 1.03.01-6dfb8b4-27.10.26, code 15. Updates need revalidation.
- Shizuku or Shizuku+, started and authorizing Termux, with rish exported to
  `~/.local/lib/shizuku/`. Override with `ANDROID_LEGACY_DEX_RISH` if needed.
- An external DeX display and a maximized/fullscreen task (windowing mode 1).

The desktop starts this optional integration automatically when the package is
installed, and stops the controller it owns during cleanup. A separately started
controller is reused and left running. Opt out in
`~/.config/livecd-native/integrations.json` with `"dex-fullscreen": false`.

Manual commands, from ordinary Termux after configuring Shizuku:

```sh
android-legacy-dex-fullscreen check
android-legacy-dex-fullscreen start
android-legacy-dex-fullscreen status
android-legacy-dex-fullscreen stop
```

The package never changes the fullscreen preference. Switch it on/off in
Termux:X11 normally; the caption follows. The in-app helper checks effective
per-display preferences on the main thread every 250 ms. It applies 0x1002
(IMMERSIVE_STICKY | HIDE_NAVIGATION) only when the external Activity's own Samsung
DecorView reports DeX enabled and fullscreen mode. It restores the previous
values of those two bits on disable, leaving other bits alone. New decor views
and focus changes are handled without reattaching.

The supervisor checks the app PID through Shizuku every five seconds and
reattaches after process restart. It waits if the app is not running, rather
than launching it. A reboot requires starting a new desktop session or manually
starting the controller. Status reports a supervisor record that may lag the
in-app state by up to five seconds. Controller logs are in
`~/.local/state/android-legacy-dex-fullscreen/controller.log`.

This is runtime instrumentation of **Termux:X11 only**, not a device-wide
framework hook or a universal fullscreen Binder command. Android explicitly
permits ART agent attachment only to debuggable apps. Shizuku supplies the shell
transport; it does not remove that restriction. See
[ART TI](https://source.android.com/docs/core/runtime/art-ti).

Helper files are staged under Termux:X11's own
`files/android-legacy-dex-fullscreen/`, in content-addressed payload directories.
The payloads have no Termux shared-library dependencies. Native code resolves
only Samsung's two caption-state getters and registers a JNI eligibility check;
it does not disable hidden-API enforcement or replace a framework method.
Stop restores flags and cancels polling, but loaded code remains until app
process exit. If Shizuku dies, restoration cannot be requested across that lost
transport; restart Shizuku and run stop, or restart Termux:X11. Removal/upgrade
requests a best-effort stop; app-side payload files remain available until
explicitly removed or the app's data is cleared. No system settings are changed.

## Evidence and limits

The actual Android 11 framework was extracted from the test phone. Its normal
caption requires `(systemUiVis & 0x1800) != 0` and navigation-hide bit 0x0002.
An isolated probe demonstrated caption visible with 0 and browser mask 0x060F,
hidden with 0x1002, and reversible behavior in the same Activity.

The original runtime helper then passed on the unmodified installed Termux:X11:
fullscreen on/off, Activity recreation, focus away/back, and helper stop/restart.
The installed APK SHA-256 stayed
`6a35610c05c1a8c09f603c4407f54b8e70831b7866fa0f9c3bcdc9f3bb1bfd34`.
The packaged implementation additionally validates the DeX/fullscreen getters
through JNI. Its device tests use the same shell UID and command script through
ADB; separate Shizuku-client authorization behavior is covered by the repository's
existing rish transport conventions, rather than claimed as a new device test.

Host checks: `python3 tests/dex-fullscreen/test-controller.py` and
`python3 tests/native/test-integrations.py`. The recipe compiles all source:
there are no opaque/prebuilt helper binaries in the repository. The agent uses
NDK jni.h, and the Java helper is compiled against Android 35 then converted
with D8 at min API 30. The installed APK is never a build input.
