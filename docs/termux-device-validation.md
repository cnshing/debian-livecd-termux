# Termux device validation

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](privacy.md).

**Later native migration:** the phone now runs the selected
[native Termux desktop](native/README.md). Its
[verification report](native/VERIFICATION.md) records the new state;
this document preserves the preceding Debian/PRoot results.

The separate Termux profile (since removed) implemented a reduced Debian
Trixie GNOME desktop on the physical phone. This report records observed
results; the three initial assessments remain historical source reviews.
Its verification report (since removed) recorded the current verification round and
reproduction commands. An implementation result here is not an external
verifier's endorsement.

## Device and version boundary

The rig is a **Galaxy Note10+ SM-N975U1**, not an S10+. It runs Android 11 / SDK
30, arm64, kernel `4.14.190-22338387-abN975U1UES7FUI5`, with an Adreno 640. USB
ADB and the existing `ssh termux` alias were used. No root or Shizuku was used.
The pre-existing rig provides the Android apps, SSH access, a wake lock, and
Termux's Doze exemption; the profile does not configure those prerequisites.

Versions observed: PRoot 5.1.107.101, PRoot-Distro 5.10.3, Termux:X11 companion
1.03.01-6, native Ghostty 1.3.1, native Mesa 26.2.6, Debian 13/Trixie, GNOME
Shell 48.7, gnome-session 48.0, GTK 4.18.6, libadwaita 1.7.6, and guest Mesa
25.0.7. The `desktop` account has home `/home/desktop`; its fake guest UID was
10310 in the existing guest and is allocated by `useradd`, not hardcoded.
Every guest process still has Termux's Android permissions.

Evidence: platform (`temp/docs/evidence/proot/android-platform.txt`),
versions (`temp/docs/evidence/proot/rig-versions.txt`), and
GPU/device access (`temp/docs/evidence/proot/gpu-inventory.txt`).

## Results and changes to the assessments

| Area | Observed result and implementation decision | Evidence |
| --- | --- | --- |
| GNOME session | A trimmed gnome-session 48 starts Shell as the X11 window manager, XSettings, and DING without logind or a systemd user manager. A private message bus supplies the system-bus endpoint, without supplying privileged system services. | Core check (`temp/docs/evidence/proot/core-clean-final.json`), prototype log (`temp/docs/evidence/proot/session-prototype.log`) |
| Extensions | ArcMenu, Dash to Panel, DING, AppIndicator, User Themes, NoAnnoyance, Tiling Assistant, and the replacement appearance extension report active state 1 without extension errors. ArcMenu was also clicked open and launched the Debian Ghostty profile. This establishes selected menu behavior and combined activation, not every interaction of each extension. | Core check (`temp/docs/evidence/proot/core-clean-final.json`), menu (`temp/docs/evidence/proot/arcmenu-final.png`), launched shell identity (`temp/docs/evidence/proot/menu-identity-final.txt`) |
| Appearance | WhiteSur/Colloid and two attributed AVIF wallpapers render. Live accent/style switching, disable/re-enable, rapid changes, regular user CSS, and an unrelated broken CSS symlink passed. The three bundled accent extensions are replaced in this profile; the liveCD extensions themselves are unchanged. | Lifecycle results (`temp/docs/evidence/proot/appearance-validation.json`), desktop (`temp/docs/evidence/proot/desktop.png`) |
| Native Ghostty | Ghostty loads native llvmpipe OpenGL 4.6. Separate Termux and Debian windows, tabs, and splits retain the chosen shell identity. Native windows have their own settings bus; guest shells join the desktop bus. | Renderer (`temp/docs/evidence/proot/ghostty-native-smoke.txt`), six surface identities (`temp/docs/evidence/proot/terminal-identities.txt`) |
| Terminal bridge | Nautilus's new action opens native Ghostty in the selected guest directory. Paths containing spaces, Unicode, quotes, semicolons, and shell syntax remain literal. Invalid modes/directories/JSON shapes are rejected without killing the bridge. | Context menu (`temp/docs/evidence/proot/nautilus-context.png`), launch (`temp/docs/evidence/proot/nautilus-terminal-launch.txt`), path (`temp/docs/evidence/proot/unusual-path-pwd.txt`), bridge checks (`temp/docs/evidence/proot/bridge-validation.json`), additional invalid types (`temp/docs/evidence/proot/bridge-final.json`) |
| Recovery outside guest | A native terminal launches while the configured guest is absent. The recorded independent test establishes launch, not a second identity capture; identities are separately shown above. Dead or malformed saved guest-session environments are ignored. | Absent-guest result (`temp/docs/evidence/proot/native-independent.json`), stale environment (`temp/docs/evidence/proot/stale-environment.txt`) |
| Editor | GNOME Text Editor opens a guest document, accepts X11 input, and saves the changed contents. It substitutes for the liveCD's amd64-only elementary PPA/plugin. | App result (`temp/docs/evidence/proot/application-validation.log`), physical screen (`temp/docs/evidence/proot/editor.png`) |
| Nautilus | Local folder browsing, rename/copy/trash of disposable guest files, and the dedicated Ghostty context action work. The first app test accidentally matched an editor title containing the folder name; the later class-based check and fresh-guest file-action test establish Nautilus itself. | Fresh app results (`temp/docs/evidence/proot/apps-clean-accepted.log`), context menu (`temp/docs/evidence/proot/nautilus-context.png`) |
| Firefox | Firefox ESR renders a local HTML page and the HTTPS example.com page; Debian uBlock Origin 1.67.0 is active. PRoot-Distro supplies `MOZ_FAKE_NO_SANDBOX=1` and `MOZ_SHM_NO_SEALS=1`; this is a reduced browser sandbox. An early remote-page attempt timed out; the fresh-guest retry rendered the page. General website/media compatibility is untested. | HTTPS screen (`temp/docs/evidence/proot/clean-apps/firefox-network.png`), extension state (`temp/docs/evidence/proot/firefox-clean-extension.json`), app environment (`temp/docs/evidence/proot/application-validation.log`) |
| Writer | Writer converts a text fixture into an ODT and opens it in its GTK window. Full GUI editing, printing, macros, and format fidelity were not tested. | Fresh app result (`temp/docs/evidence/proot/apps-clean-accepted.log`), fresh Writer screen (`temp/docs/evidence/proot/clean-apps/writer-accepted.png`) |
| Audio | A 440 Hz fixture reaches the native OpenSL ES sink; capturing its monitor returns nonzero samples. Guest direct Unix Pulse connections failed with a protocol error. The implementation instead uses loopback TCP with a private random cookie; an incorrect cookie is rejected. An acoustic recording/listening test was not made. | Samples (`temp/docs/evidence/proot/application-validation.log`), Unix/TCP probe (`temp/docs/evidence/proot/pulse-tcp-probe.txt`), authentication (`temp/docs/evidence/proot/audio-authentication.txt`) |
| Media | mpv's configured X11 software output renders a 320×240, 15 fps H.264/AAC fixture with Pulse audio. Default GPU output rejected software rendering and could exit successfully while showing no video, so exit code alone was insufficient. Explicit software OpenGL rendered but had startup/desynchronization lag. | Video screen (`temp/docs/evidence/proot/video.png`), media log (`temp/docs/evidence/proot/media-validation.txt`), OpenGL probe (`temp/docs/evidence/proot/mpv-opengl-probe.txt`) |
| Thumbnails/indexing | Direct ffmpegthumbnailer produced a 128×96 PNG. Automatic Nautilus thumbnails are generally unsupported here: fresh PNG, JPEG, and AVIF tests produced no valid previews. Direct converter success does not establish file-manager integration. LocalSearch's extractor repeatedly failed because the kernel lacks its Landlock facility; profile-owned per-user D-Bus activation overrides disable it. Nautilus content indexing is consequently unavailable. | Video thumbnail (`temp/docs/evidence/proot/media-thumbnail.txt`), general preview test (`temp/docs/evidence/proot/thumbnails-round2.json`), generic icons (`temp/docs/evidence/proot/thumbnails-round2.png`) |
| CPU monitoring | Native `/proc/stat` is denied; guest samples are static. htop renders but shows process CPU as N/A and misleading zero global CPU bars. The added `livecd-top` uses changing PID ticks divided by monotonic elapsed time, reporting about 99% for a one-core busy fixture and readable RSS. It includes readable Termux processes, not only guest applications. | Counters (`temp/docs/evidence/proot/proc-validation.txt`), htop (`temp/docs/evidence/proot/htop.png`), monitor (`temp/docs/evidence/proot/monitor-validation.json`) |
| Process control | SIGTERM terminates the disposable workload. SIGSTOP yielded a stopped wait event but the process kept running and gaining CPU ticks; suspend/resume is not supported by this tested PRoot combination. The core check reports this limit rather than claiming a pass. | Signal probe (`temp/docs/evidence/proot/signal-probe.txt`), core result (`temp/docs/evidence/proot/core-clean-final.json`) |
| Mission Center | Stock Flatpak installed GNOME 50 runtimes but failed twice installing Mission Center with `statx didn't return all required fields: No data available`. Round 2 repeated bubblewrap with valid filesystem-bind layouts; those failed while ordinary `/bin/true` worked. The earlier bare invocation was not a valid compatibility test. No GUI, Magpie, measurement, or process-tree acceptance is claimed. The reviewed fork/shim remains untested; this stock-route failure does not disprove it. Flatpak is excluded from core setup. | Install (`temp/docs/evidence/proot/mission-center-stock-flatpak.log`), retry (`temp/docs/evidence/proot/mission-center-stock-retry.log`), toolkit/deployments (`temp/docs/evidence/proot/mission-center-toolkit.txt`), valid-layout probe (`temp/docs/evidence/proot/bubblewrap-valid-layouts-round2.txt`) |

### Rendering and the supplied GPU resource

The default desktop and native Ghostty use llvmpipe. Guest glxinfo reports
OpenGL 4.5; native glxinfo/Ghostty report OpenGL 4.6. These are software
renderers regardless of the reported API version.

The supplied [hardware guide](https://github.com/LinuxDroidMaster/Termux-Desktops/blob/main/Documentation/HardwareAcceleration.md)
was useful as a candidate route, not proof of flawless performance. Mesa's
[Turnip documentation](https://docs.mesa3d.org/drivers/freedreno.html) identifies
Adreno 6xx support. The phone actually exposes `/dev/kgsl-3d0`; PRoot does not
grant access that the Android app UID lacks.

A pinned [Mesa for Android Container build](https://github.com/lfdevs/mesa-for-android-container/releases/tag/mesa-27.0.0-devel-20261025)
was tested from an isolated `/opt/livecd` directory. Its Debian Trixie arm64
archive SHA-256 is
`b711d1d9ab5537ee9085da8896dfe2115e791b33aa317fe37538f276c967d687`.
It leaves Debian's system libraries intact. The optional installer relocates
the archive's absolute Vulkan ICD library path and supplies a per-app wrapper.

- Freedreno/KGSL reports **FD640, accelerated yes, OpenGL 4.3**.
- Turnip/Zink reports **Adreno 640, accelerated yes, OpenGL 4.6**; Vulkan
  enumeration reports Turnip Vulkan 1.3.363.
- A short glmark2 `build` scene at 640×480 rendered with all three paths.
  Its repeated two-second samples were 53–78 fps with llvmpipe, 145–155 with
  KGSL, and 173–181 with Zink. These sequential, short, unthermally-controlled
  samples also use different Mesa versions (25.0.7 versus 27-devel). They
  are neither a full benchmark score nor a comparison with native Android.
  They do not establish the absolute best driver, conformance,
  battery life, or near-native performance.
- The initial isolated Zink probe failed because the upstream ICD still
  pointed to `/usr/lib`; the corrected probe passed. A glxinfo exit code of
  zero accompanied the initial failure, so renderer text was checked too.

Evidence: first probe and its error (`temp/docs/evidence/proot/gpu-renderers.txt`),
corrected GL/Vulkan (`temp/docs/evidence/proot/gpu-renderers-corrected.txt`),
scene samples (`temp/docs/evidence/proot/gpu-window-test.txt`),
installed-wrapper probes (`temp/docs/evidence/proot/gpu-installed-clean.txt`), and
actual Zink scene (`temp/docs/evidence/proot/gpu-zink-clean.png`) with its
12-second run log (`temp/docs/evidence/proot/gpu-scene-clean.txt`). See the profile README
for the optional `LIVECD_GPU=yes` setup and `livecd-gpu` commands. Whole-session
GNOME GPU rendering, native Ghostty GPU rendering, accelerated Firefox, and
hardware video decoding remain untested.

## Startup, recovery, and failures

Two packaging details in the source assessment required explicit installer
work: `gnome-menus` plus `XDG_MENU_PREFIX=gnome-` supply ArcMenu's applications
menu, and Debian ArcMenu 65's missing stylesheet is filled from the existing
liveCD v65 copy. A package-provided stylesheet is preserved. ArcMenu logs a menu-icon fallback on this guest; its available default icon and application menu render. Missing hardware, calendar/online-account, IBus, and screencast services also produce expected warnings; an active extension state is not an error-free session log.

The host controller owns its guest, Pulse process, terminal windows, and any
X server it starts. An already-running X server is reused and survives
logout. It waits for the display, audio, Shell, and extensions before exposing
the terminal bridge. The original smoke-test X server and demo clients were
stopped during development; the controller then started a new X server.

Ten fresh start/exit cycles passed, alternating five managed stops with five
GNOME SessionManager logouts. A deliberate Shell SIGKILL then caused owner
cleanup; a new start recovered, and the test stopped that session. The
cycle log (`temp/docs/evidence/proot/lifecycle-clean.jsonl`) records distinct owners
and Shell PIDs. The post-test process inventory (`temp/docs/evidence/proot/processes-after-clean-lifecycle.txt`)
contains only the pre-existing Termux shell/sshd and the inventory's own SSH
processes, with no desktop, Pulse, or test helper left alive.

Normal logout through GNOME SessionManager completed. Managed stop/start,
recovery mode, return to normal mode, user-preference persistence through
setup/restarts, and a brief Android Home/return transition were exercised.
Recovery saves and restores the user's previous extension-disable setting.
GNOME locking and idle blanking are disabled because no GDM unlock route
exists. The three essential keys now have dconf locks; validation checks their
values and confirms that user overrides cannot make them writable. The tested ScreenSaver D-Bus calls returned missing-service errors;
this report does not reinterpret them as a successful lock/unlock test.

Two Shell SIGSEGVs occurred during experiments that reran setup while the
desktop was active. The underlying crash was **not root-caused or fixed**.
The correlation led to a supported stopped-session update path: setup and
session now share an exclusive lock, and live setup is rejected before
package/profile changes. The host also watches Shell's actual PID and birth
time, because after a crash this kernel/GLib combination can leave the session
manager alive with `waitid(P_PIDFD)` errors. A dead Shell now tears down its
session instead of leaving a healthy-looking bridge.

Twelve actual mpv X11 render/open/close cycles completed. Another twelve
initially labelled GPU trials exited without initializing video and are
explicitly corrected in their raw log. They are not twelve additional
successful video tests. Ordinary short workloads and restarts passed after
the update guard; this is not a long-term stability guarantee.

Evidence: Shell exit (`temp/docs/evidence/proot/shell-exit-investigation.txt`),
owner detects exit (`temp/docs/evidence/proot/recovery-transition-log.txt`),
live setup rejected (`temp/docs/evidence/proot/setup-running-rejected.txt`),
logout (`temp/docs/evidence/proot/gnome-logout.txt`),
recovery (`temp/docs/evidence/proot/recovery-state.txt`),
normal/persistence (`temp/docs/evidence/proot/recovery-normal-and-lock.txt`),
Android return (`temp/docs/evidence/proot/android-resume.txt`),
video-cycle correction (`temp/docs/evidence/proot/window-stress.log`).

## Setup and remaining acceptance boundary

`LIVECD_DISTRO=livecd-clean LIVECD_GPU=yes bash tools/rig.sh setup` created a
new guest from `debian:trixie`, using the rig's cached OCI layer but downloading
the 545 MB of core Debian packages and all three pinned asset archives. It
completed without manual package additions. The stopped rerun applied the
ArcMenu CSS correction and completed again. Core, appearance, and application
checks passed in this guest. The clean manifest (`temp/docs/evidence/proot/guest-packages-clean.tsv`)
contains no Flatpak, gcc, or libc6-dev dependency from earlier experiments.
This is an empty-guest test on the established rig, not a reset/virgin-phone test.
See first setup (`temp/docs/evidence/proot/setup-clean.log`),
rerun (`temp/docs/evidence/proot/setup-clean-rerun.log`),
apps (`temp/docs/evidence/proot/apps-clean-accepted.log`), and
appearance (`temp/docs/evidence/proot/appearance-clean.json`).

In the expanded GUI test, Debian's old xdotool opened GNOME's Run dialog for
F2 on this XKB map; native Termux xdotool opened Nautilus's rename dialog.
The difference was observed, without tracing its internal cause. The helper now sends that mapped keycode through XTest. It also
waits for Nautilus's view after a copy. The failed attempts are retained in
`apps-clean.log`, `apps-clean-retry.log`, and `apps-clean-final.log`; the accepted
run is `apps-clean-accepted.log`. Writer publishes its title before painting:
the initial `clean-apps/writer.png` still shows Firefox, and is **not Writer
visual evidence**. `writer-accepted.png` was captured after waiting for its
actual frame. The test helper now waits longer too.


Themes are pinned and checksum-verified; actual phone downloads were checked,
not only preseeded archives. APT and the `debian:trixie` image tag follow current
repositories. Package manifests are recorded. This is a repeatable installer,
not a bit-for-bit reproducible build or a distro image.

GSConnect and guest EQ are deferred optional features in this profile. (Later,
native Termux gained separate opt-in prototypes of
[GSConnect](gsconnect/README.md) and [playback EQ](audio/README.md).)
Remote desktop, AppImages, boot/install features, and privileged device management are outside
the implementation. No parity is claimed for GNOME Settings hardware pages,
network mounts, printing, portals, keyrings, accessibility, shared Android
storage, clipboard integration, multilingual IME/physical keyboards, every
extension interaction, Android reboot/long suspension, heat/battery life, or
Android 12+ process restrictions. Android owns device networking, power, and
physical locking.

A fresh-guest Shell remained alive for 36 minutes during these checks (PID/elapsed evidence (`temp/docs/evidence/proot/stability-clean.txt`)); this was light/intermittent use, not the proposed sustained workload benchmark.

The proposed acceptance matrix in the historical assessment is broader than
these results. An extension's active state is not a functional test of every
menu, tray, tiling, or file-management operation. Full mission-center and
hardware views are not silently replaced by a claim of complete desktop parity.

The final installed default remains `debian`, with the optional GPU wrapper;
`livecd-clean` is retained, stopped, for inspection. Final core validation also
passed in `debian` (result (`temp/docs/evidence/proot/core-default-final.json`)). Ten
installed program/configuration hashes match the handed-over source
(hash map (`temp/docs/evidence/proot/installed-source-hashes.json`)). The final process
inventory and outstanding experimental phone changes are listed in the handoff.

### Native Ghostty window-close limit

A final menu click opened Ghostty and its actual shell produced the expected
guest identity (screen (`temp/docs/evidence/proot/menu-ghostty-final.png`),
identity (`temp/docs/evidence/proot/menu-identity-final.txt`)). An initial
`xdotool windowclose` destroyed its X window rather than asking the application
to close; this command is not a normal logout test
([xdotool implementation](https://github.com/jordansissel/xdotool/blob/master/xdo.c)).
Managed stop cleaned that managed instance. The subsequent native
`xdotool windowquit` issued a normal close request and showed Ghostty's
confirmation dialog. Confirming it removed the window, **but the native
client and guest shell remained alive**. That is an unresolved lifecycle
limit on this build/kernel, not a completed acceptance case. No internal
cause has been established. Typing `exit` is a separate working path: a round 2 native test verified the expected shell identity and observed every tracked Ghostty/bus/shell process exit in both modes (results (`temp/docs/evidence/proot/terminal-exit-round2.jsonl`)). GNOME Terminal remains the default for using ordinary window-close buttons.

The second instance was standalone (opened while the desktop was starting)
and was explicitly terminated after the test, with process-name/group checks:
close inventory (`temp/docs/evidence/proot/terminal-normal-close.txt`),
cleanup (`temp/docs/evidence/proot/standalone-terminal-cleanup.txt`). The final
process inventory (`temp/docs/evidence/proot/final-phone-processes.txt`) contains no
Ghostty or test shell. Other session/launcher tests above do not erase this
per-window limitation.

## Round 2 verification follow-up

The independent verifier reproduced the installer, default empty-guest build,
core/application/lifecycle tests, audio authentication, recovery, and GPU probes
(round 1 findings). The following changes respond to
V1–V8; they do not retrospectively change the round 1 test results.

- **V1:** automatic previews fail generally, including PNG/JPEG/AVIF. The
  new probe (`test-thumbnails.py`, since removed) samples new URIs at 0, 12 and 30 seconds.
  There are no valid thumbnails; AVIF has a failure marker, while PNG/JPEG have
  no cache entries. The initial probe misread the uint64 limit with a uint32
  accessor; the accepted JSON correctly records 50, without changing that setting.
- **V2/V3:** the close-button leak remains an accepted limitation. Ordinary shell
  `exit` worked for single-shell windows in both modes: tracked clients, buses,
  and shells disappeared in the recorded tests. The failure is specific to the
  close-button path, not every way of finishing a Ghostty session.
- **V4:** setup now consumes the liveCD's font package list with recommendations,
  instead of a narrower hardcoded subset. The package/charset probe (`temp/docs/evidence/proot/fonts-round2.json`)
  finds 3 fonts for U+20000, 1 for U+2A700, and 0 for U+30000. Package parity is
  restored; universal character coverage is not claimed. Native Ghostty's host
  font fallback is a separate, unvalidated rare-character case.
- **V5:** startup now sets Shell's public `OverviewActive` property to false after
  extension readiness. ArcMenu's update notifier defaults off; the initial Dash
  to Panel marker follows its installed metadata. These are new-profile defaults;
  ordinary overview use and existing user preferences remain available. GNOME can still show its informational “Screen Lock disabled” notice because GDM is absent; this is visible in the first-login screenshot.
- **V6:** routine screenshots now use unique temporary PC paths. Two captures
  preserved the cited image's SHA-256 (check (`temp/docs/evidence/proot/screenshot-preservation-round2.json`)).
- **V7:** the old bare bwrap invocation omitted filesystem binds and is not
  diagnostic. The new evidence (`temp/docs/evidence/proot/bubblewrap-valid-layouts-round2.txt`)
  includes direct true (exit 0), a root-bind layout (exit 1), and a Flatpak-like
  `/usr`/proc/dev layout (exit 1). No workaround fork or sandbox bypass was added.
- **V8:** at the initial round 2 probe, TCP inode 1161906 belonged to Termux:X11 PID 32085, listening
  on all IPv4 interfaces at port 7892 (owner match (`temp/docs/evidence/proot/x11-listener-owner-round2.json`),
  listener listing (`temp/docs/evidence/proot/network-listeners-round2.txt`)). The
  [matching upstream source](https://github.com/termux/termux-x11/blob/6dfb8b4a4cc887bc329284d31eb049d596bd1208/lorie/src/main/cpp/lorie/cmdentrypoint.cpp)
  identifies its connection/wakeup listener, which binds `INADDR_ANY` and
  triggers a frontend broadcast. This is separate from Pulse authentication.
  No LAN-peer behavior/security assessment or listener restriction is claimed.

The final fresh-home test in `livecd-clean` passed after preserving its earlier
homes as backups: startup state (`temp/docs/evidence/proot/first-login-refined-round2.json`),
desktop (`temp/docs/evidence/proot/first-login-refined-round2.png`), and
core check (`temp/docs/evidence/proot/core-clean-refined-round2.json`). Application
checks with the expanded fonts also passed (log (`temp/docs/evidence/proot/apps-clean-round2.log`),
Writer frame (`temp/docs/evidence/proot/clean-apps-round2/writer.png`)).
`test-startup.py` records overview state immediately and after 15 seconds.
The image shows GNOME's informational lock-disabled notice, not an ArcMenu
promotion or persistent Activities overview.

On the final default guest, ordinary `start` also preserved a deliberately
opened overview instead of applying the one-time startup action again
(check (`temp/docs/evidence/proot/start-idempotent-overview-round2.json`)). Safe mode
and the return to normal passed after the readiness change; the final core
check is core-final-round2.json (`temp/docs/evidence/proot/core-final-round2.json`).
The final installed/staged source comparison covers 15 inputs
(hash map (`temp/docs/evidence/proot/installed-source-hashes-round2.json`)).
