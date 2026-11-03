# Native Termux desktop verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> Recorded before the repository restructure. Paths were updated, but build steps and
> install locations describe the earlier on-device flow.

**Later GPU follow-up:** native Turnip + Zink is implemented and
selected on the tested phone. [GPU verification](GPU-VERIFICATION.md) records
the EGL/GLES compositor fix, actual GPU application checks and current renderer
selection. The software-rendering results below preserve the initial port snapshot.

Implemented and tested on the established
Samsung Note10+ SM-N975U1, Android 11, arm64, Adreno 640 rig. This is a functional
native GNOME port with the limits below; it is not a complete source rebuild of
the compositor stack or a validation of every Android integration feature.

## What runs natively

GNOME Shell 48.0, Mutter 48.1, GJS 1.85.1 / mozjs-128, gnome-session 48.0,
Nautilus 49.3, GNOME Terminal, Ghostty, GNOME Text Editor, Firefox, LibreOffice,
mpv-x and xfce4-taskmanager use Android/Bionic executables. The native owner
contains no PRoot invocation. Its private runtime's recursive ELF audit resolves
**169 ELF files with no missing dependencies**, including the source-built
components. Native executable interpreters are `/system/bin/linker64`.

The stored Debian guest is optional fallback/data storage. It is not a native
application dependency. Setup works from native Termux package/source inputs and
does not enter or require a Debian guest. Any Debian start recorded below is an
explicit, separate rollback test.

## Final phone state

The native backend is installed, selected as the `livecd` default, and left
running in normal mode. `select-native.json` records selection after validation.
`selected-fallback-cycle.json` then records native stop → explicit Debian start
and validation (`PASS_CORE_WITH_LIMITS`) → Debian stop → default native start
and validation. The Debian worker and its terminal helper explicitly pin their
backend, so retaining a native default cannot redirect the fallback's worker.

`core-final.json` passes all **23 checks**, including eight enabled extensions
and no running PRoot processes. Optional GSConnect and audio controllers are
stopped. `final-inventory.json` records the selected backend, native process
executables, exact source hashes and matching installed controller hashes.
Relative to the pre-install inventory, **169 native packages were added and
no existing APT package versions changed** at that snapshot. Debian remains stored
on disk and is unnecessary for native startup, terminals or applications.

Commands used Wi-Fi ADB with an ADB-forwarded native SSH connection. These
results do not establish USB-specific behavior. `desktop-final.png` captures
the native X11 display directly.

## Inputs and integration fixes

- The bootstrap distribution is the tracked `dist/` tree of
  [GNOME-Termux, 42a890c7603609d1c6a7e6edf9cd05c084923d8f](https://github.com/Gass-OS/GNOME-Termux/tree/42a890c7603609d1c6a7e6edf9cd05c084923d8f).
  The full archive hash is `db08ba6d6ab0c95f09ccf90a5d45ba9d73b8b6d5d9071a5dedb4cba71cb5b62a`.
  Unlike its published release, this tree includes matching Mutter and
  mozjs-128 libraries. No upstream installer was executed.
- The private executable originally loaded GIRepository 1.0 alongside GJS's
  GIRepository 2.0, causing a duplicate-GType failure. `gi-paths.c` supplies only
  its three legacy path/option-group imports; the executable's dependency is
  rewritten locally. The developer introspection-dump option is not provided.
- The bundle omitted `mutter-x11-frames`, and its missing-child path crashed.
  The helper is built from the hash-verified Mutter 48.1 source. The private
  Mutter library's fixed-length helper path is relocated to the owned native
  launcher. Nothing is copied over the shared Termux Mutter/GJS libraries.
- The published Shell GIR referenced `GioUnix.DesktopAppInfo` without including
  GioUnix, and the bundled typelib was stale. Adding the dependency and compiling
  the typelib fixed ArcMenu's app-information errors. ArcMenu also uses the
  existing Termux account compatibility module instead of missing AccountsService.
- gnome-session uses the patches from the closed
  [Termux PR #24585, 77ae9db](https://github.com/termux/termux-packages/tree/77ae9db667103a2ea7575c8f23a497754796951a/x11-packages/gnome-session),
  with the Meson configuration-key quoting corrected.
- Nautilus uses the five Android/build patches from
  [PR #32883, b3c8d590](https://github.com/JesusChapman/termux-packages/tree/b3c8d5907eb221aaa8306449e4209cf4bbeee3b8/x11-packages/nautilus).
  gnome-autoar 0.4.5 and Nautilus 49.3 are built into the private prefix.
  LocalSearch's file-miner schema is installed with empty indexed-directory
  defaults; the indexing daemon is not started.
- DING's old global `/proc` cleanup was removed: Android denied its scan, and
  the desktop owner already cleans up tagged children. D-Bus helper launchers,
  schemas, menus, font paths, cursors, theme paths and XSettings use native paths.
- The official native package set lacks an available PNG/JPEG thumbnailer on
  this rig. The profile's FFmpeg image helper supplies PNG, JPEG and AVIF previews.
- PulseAudio uses the host environment for Android's OpenSL ES initialization;
  private GNOME library-path overrides caused initialization to fail. Native
  clients use the owned Unix socket. No desktop Pulse TCP listener is started.
- Optional GSConnect and audio launchers restore their existing native component
  profiles and shared Termux library paths, avoiding CJS/GJS ABI mixing. Audio
  clients launched with `livecd-audio exec` retain desktop settings and bus
  ownership while selecting the effects socket.

`sources.lock.json`, `build-components.py`, the included patches and
`prepare.py` pin the non-APT inputs. Official Termux packages remain rolling.

## Accepted checks

Evidence is in `evidence/` (`temp/docs/evidence/native`), with failed intermediate probes retained
where they explain a fix. A passing extension state alone is not used as proof
of every extension interaction.

| Check | Result / evidence |
| --- | --- |
| Recursive private ELF closure | 169 files; no missing dependencies. `elf-audit-final.json` |
| Complete installer and stopped rerun | `setup-first.log`, `setup-rerun.log`; rerun symlink handling was corrected before the accepted rerun |
| Native WM, session bus, eight extensions, private settings, lock-key enforcement, native packages, font coverage and signals | `core-final.json` |
| Native SIGSTOP/SIGCONT | A busy native Python process enters `T` and resumes; core JSON |
| Broad CJK coverage | Fonts cover U+20000 and U+2A700; core JSON. This is not universal Unicode/shaping acceptance |
| Theme switching and CSS ownership | `appearance.json`: light/red and dark/yellow transitions; existing regular CSS and unrelated broken links preserved |
| Editor edit/save | `apps-writer-edit.json`, `apps-writer-edit.log`; saved bytes verified after real X11 typing |
| Nautilus browse/rename/copy/trash | Same app test; disposable fixture files checked after real UI operations |
| Firefox local and HTTPS pages | Same app test; titles and screenshots. Bootstrap XPI is pinned at 1.67.0; Firefox's normal extension update produced active, signed 1.75.0 by the final check (`firefox-extension.json`) |
| Writer edit/save | Fresh isolated profile; first-run welcome dismissed, text typed through X11, saved text verified inside the ODT ZIP. Final document 10,268 bytes; `apps-writer-edit.json`, `writer.png`. Formatting/printing are not established |
| Audio output data | OpenSL ES sink monitor recorded peak signed-16 sample magnitude 2,001; no acoustic listening test |
| Automatic previews | `thumbnails-fixed.json`: fresh PNG, JPEG and AVIF URIs acquired thumbnail paths and cache files after opening Nautilus |
| Native terminal paths and identity | `terminal-final.json`: Exact Unicode/quote/shell-syntax directory preserved; no shell expansion |
| Native terminal close | Shell `exit` and WM close each removed the window, launcher and real Bash process; terminal JSON |
| Recovery terminal without GNOME | `standalone.json`: a separate private-bus GNOME Terminal used the real native home, then its owner exited with the shell |
| Repeated lifecycle | `lifecycle.jsonl`: ten complete start/stop cycles, **8.420–10.414 s**, median **8.991 s**. These are cycle times, not startup-only measurements |
| Crash, recovery and isolation | Forced Shell death cleaned the session; safe/normal transitions passed; an unrelated `sleep` survived every cycle; lifecycle JSON |
| Native video | `media-final.json`, `video.png`: generated MPEG-4/AAC fixture played in a native mpv window with X11 video and PulseAudio output; software rendering |
| Task manager GUI | `components.json`, `xfce4-taskmanager.png`: actual native Task Manager window |
| Optional component integration | `components.json`, component screenshots: existing GSConnect preferences and EasyEffects windows opened; an effects client preserved desktop settings and bus while using the effects socket. Both optional daemons stopped after validation |
| Debian document copy | `data-migration.json`: 13 regular files copied with matching hashes, one identical file, no conflicts or skipped entries. Copied contents on this rig were prior validation fixtures |
| Explicit Debian fallback | `debian-fallback.json`: separately invoked guest passed `PASS_CORE_WITH_LIMITS`, stopped before returning to native |

The earlier Writer repeat attempts exposed validation-profile recovery and
overwrite dialogs. Tests now use unique filenames and isolated profiles, dismiss
the first-run welcome and close Writer through the window manager. The earlier
test profile is preserved under `~/.local/state/livecd-native/libreoffice-validation-profile`.
No user documents were removed to fix the test.

The complete installer and its first accepted rerun preceded the final controller
fixes. A third full rerun was cancelled while waiting for a separate Chromium
download's APT lock (`setup-final.log`); that download was left intact. With the
desktop stopped and the installed dependencies unchanged, the final controller
and profile were installed and audited separately (`finalize-profile.sh`,
`final-profile-install.log`). This is not recorded as a third complete installer
pass. The pre-install prefix archive is 1,422,837,760 bytes; restoration is untested.

Reproduction commands are in [README.md](README.md). Run lifecycle tests through
plain native Python outside the desktop environment, since stopping a session
also stops test processes launched through that session.

## Remaining boundary

- The Shell/Mutter/GJS bootstrap is a repaired third-party binary set. A full
  reproducible source build, security maintenance and a newer GNOME 48 patch
  level remain work. Shell is **48.0**, not the guest's 48.7. Official Termux no
  longer maintains this X11 Mutter stack.
- This uses software rendering and the Termux:X11 display route. GPU acceleration,
  hardware video decoding, Wayland/Anland and newer Android process policies
  are not validated by these results.
- Android owns device locking, power, network policy and hardware permissions.
  The compatibility system bus has no privileged services. Full GNOME Settings,
  GDM, system power management, portals, mounts and content indexing are not
  supplied. Some corresponding GNOME warnings are expected.
- xfce4-taskmanager's totals cover the processes Termux can see. They are not
  whole-device Android CPU statistics.
- Ghostty retains the earlier normal-window-close limitation; GNOME Terminal
  is the default accepted close workflow. Multi-window/tab/split edge cases
  are not implied by the two single-window terminal checks.
- EasyEffects/AutoEq and GSConnect retain their separate opt-in controllers and
  prior acceptance limits. Shared GNOME GSConnect panel integration, restoring
  its disabled CJS features, and processing every desktop audio client are not
  established here.
- General website/media behavior, office formatting/printing, accessibility,
  physical keyboards/IME, Android clipboard/shared storage, rotation, reboot,
  battery/thermal endurance and multi-hour sessions need separate acceptance.
  Native Firefox success is not proof of a conventional Linux browser sandbox.
- The test phone already had a populated Termux environment and build tools.
  A new-phone installation and restoration of the archived host prefix have not
  been performed. Debian documents are copied only by the explicit data copier;
  compiled environments and browser profiles are not imported automatically.
