# PanVK desktop integration on x1s

`livecd start --renderer zink` selects the packaged PanVK kbase ICD on a Mali
phone with accessible `/dev/mali0`. Qualcomm retains the Turnip path. The saved
renderer controls plain `livecd start`; `livecd select` validates the running
desktop before saving that choice. Explicit software and `--safe` recovery
remain available.

## Inputs and behavior

- `mesa-vulkan-icd-panvk-kbase` 26.3.1: the pinned Zenith release Bionic ICD,
  SHA-256 `62c2b3f98ca987d5ab50b6f01e2d2c1c5b3ee995fe93666aa5da9415f65c3348`.
  This is the release driver already validated in private GNOME sessions.
- Mesa 26.2.6-101: Zink queries actual SYNC_FD import/export features before
  advertising native-fence FDs. The driver exposes the extension names but
  does not support that handle type, so the synchronous fallback is required.
- `livecd-desktop` 0.2.0-16: device-based ICD selection, compatible X11 library
  lookup, and PanVK/Mali process evidence in native validation.
- PanVK presentation uses MIT-SHM, including legacy drawing when the controller
  starts Termux:X11. The driver and Mesa remain packaged under `$PREFIX`.
  No `~/gpu-x1s` path enters the installed renderer configuration.

Ghostty 1.4 requires OpenGL 4.3 in its
[renderer source](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/renderer/OpenGL.zig#L34).
This driver exposes core GL 4.2, so the launcher uses llvmpipe for Ghostty while
the compositor and compatible applications retain PanVK. Both `livecd terminal`
and the Terminal overlay's menu/command wrapper use the same capability probe.
Future PanVK drivers reporting sufficient core GL retain GPU rendering. Failed
or unreadable probes select the working software terminal path. No GL version
override is used to claim missing functionality.

The experimental point-size driver is not selected. It passes the offscreen
graphics workload but fails GTK swapchain creation; its two-patch series needs
bisection before desktop use. Its X11 names/symbols resolve successfully, which
does not override that presentation failure.

The installer makes the PanVK package available on Mali without overwriting
a saved renderer preference. A missing/broken ICD fails explicit Zink startup
with a diagnostic rather than counting a software fallback as acceleration.

## Validation

On the SM-G981B / Mali-G77, the new controller selected the installed packaged
ICD in a private GNOME 48.8 session. Nautilus, Settings and the GTK4 GLES GLArea
rendered. Twenty odd-size resize/fullscreen cycles produced 40 captures with
maximum channel error zero across every quadrant interior pixel and distributed
samples. A deliberately stale color phase was rejected. Shell and GTK mapped
the packaged PanVK ICD, held Mali descriptors, and mapped private extraction of
the same Mesa 26.2.6-101 build subsequently installed. No ANGLE mapping was
accepted. Before/after shared-state snapshots matched; the managed desktop
was stopped at both checkpoints. Shell logged no semaphore-creation errors.

Evidence: local `temp/gpu-x1s/integration/desktop-integrated-shm-20/` and
`01-private-desktop.txt`. The test is preserved as
`tests/native/panvk-desktop.py --integrated --controller-dir /private/controller`;
`tests/native/check-panvk-desktop.py` checks the retrieved results.

Six host graphics tests cover Mali/Turnip selection, library boundaries,
missing-driver failure, software recovery and matching process evidence.
Four terminal-environment tests cover low/high GL versions, probe failures,
and the unchanged Turnip/software paths. The existing native device terminal
test is retained separately.
The existing 13 media-routing, 12 packaging and five desktop-status tests pass.
Package CI: [43176795416](https://github.com/cnshing/debian-livecd-termux/actions/runs/43176795416).
Mesa CI: [43147207382](https://github.com/cnshing/debian-livecd-termux/actions/runs/43147207382).
Controller update CI:
[43179865272](https://github.com/cnshing/debian-livecd-termux/actions/runs/43179865272).
All three runs passed. The controller update uses the same pinned Termux builder
for the architecture-independent Python controller, preserving declared runtime
dependencies without recompiling unchanged GNOME libraries.

### Managed session acceptance, 2026-11-12

The phone now has `livecd-desktop` 0.2.0-16 and Mesa 26.2.6-101 installed through
APT, retaining the unchanged release PanVK driver. Only the controller and Mesa
were upgraded. The local APT index preserves the other 94 package stanzas and
now advertises the tested controller, Mesa and PanVK packages. Its metadata,
previous controller and previous renderer preference are backed up under the
local integration evidence directory on the phone.

| Check | Result |
| --- | --- |
| Native Zink desktop validation | 30/30 PASS |
| Compositor identity | Packaged PanVK library and two Mali handles |
| Nautilus | PanVK/Mali evidence and correct inspected capture |
| Ghostty | Intended llvmpipe fallback; native UID/home and typed command PASS |
| Direct Vulkan mpv rendering | PanVK/Mali evidence, inspected video, PulseAudio PASS; software decoding explicit |
| Vulkan cube + GLX gears | 60.49 seconds concurrently; same Shell PID, visible animation, both PanVK/Mali |
| Terminal literal paths, shell exit, WM close | Both cases PASS; native UID and literal Unicode/quoted path preserved |
| `livecd start --safe` | 27/27 PASS, software renderer, no compositor GPU library/device |
| Plain `livecd start` after recovery | 30/30 PASS, PanVK/Zink restored from saved preference |
| Repeated plain start | Same owner/session retained |

`livecd select` saved `native_renderer=zink` after native validation. The final
managed session is running normally on PanVK; `livecd start` needs no extra
renderer flag. The native terminal lifecycle test initially typed before the
second window's input initialization, dropping the leading `python`. Waiting
for focus and allowing startup to settle fixed this test race; the complete
rerun passed both exit and WM-close cases. This was separate from the earlier
Ghostty GL-context failure, which the capability fallback resolves.

Additional evidence is local under `temp/gpu-x1s/integration/`: logs 04–19,
`managed-gpu-artifacts/`, and `recovery/result.json`. The GPU application test
records Ghostty explicitly as software, rather than treating it as GPU evidence.
The 60-second animation run does not substitute for the pending long soak.

## Limits

The 30-minute soak remains pending by user request. Android app AHB import,
unsupported indirect-copy/allocator paths, browser qualification and hardware
video are separate from desktop presentation. No new Firefox workload or ANGLE
desktop path is introduced. Other Mali devices need their own acceptance;
the Turnip selector is covered by host checks, with physical Adreno regression
testing still separate.
