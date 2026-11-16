# PanVK desktop integration on x1s

Current integration: `install.sh` selects PanVK/Zink by default for a fresh
qualified x1s installation, preserving any saved renderer preference. The
normal `mesa-vulkan-icd-panvk-kbase` 26.3.1-1 package carries the fourteen-patch
source-built desktop/AHB candidate for both Bionic and glibc. Controller
`livecd-desktop` 0.2.0-21 verifies the device profile and source manifest before
defaulting to `PANVK_G77_LWG=1` and `PANVK_G77_NESTED=1`. Explicit mode settings
are preserved. Software and `--safe` recovery remain available.

- Bionic SHA-256: `134b668a988626a64f01ce8f1c93307a439cf208e47d775a17a42b60358c5758`.
- glibc SHA-256: `64f5516f608fa31db503e8c45f5442790d0afe1cf28ba2aa6a334030dd608b04`.
- Source tree: `b28956ffc095bda26bf8241badba014be178536b`.
- Assets and provenance: [panvk-desktop-26.3.1-1](https://github.com/cnshing/debian-livecd-termux/releases/tag/panvk-desktop-26.3.1-1).

The installer and browser installation path ensure the pinned driver/controller
versions, using the local APT repository when available or verified immutable
release assets online. Downloaded packages remain in a local APT repository
at the project priority, so later upgrades retain them until a newer version
is available. An older offline tarball fails clearly instead of
silently selecting an older stack. Both ABIs use the existing installed paths
under `$PREFIX/lib/panvk-kbase`, so desktop and browser selectors agree. No
qualification-directory path is used by the installed configuration.

The automatic profile is limited to x1s/aarch64/Linux 4.19.87/kbase JM 11.35.
Other Mali devices retain manual renderer selection; Qualcomm retains Turnip.
Presentation stays on the accepted MIT-SHM transport. The dedicated qualified
Ghostty GTK GL DMA-BUF launcher remains the default where its guard passes.
Full CTS coverage and further timed soaks are not daily-desktop requirements.
See [the version handoff](PANVK-VERSION-BUMP-HANDOFF.md) for current results and
[the acceptance handoff](PANVK-CTS-AND-DAILY-DESKTOP-HANDOFF.md) for scope.

## Historical release validation

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
The 60-second animation run does not establish a long soak; no further soak is requested.

## Limits

No further timed soak is requested. The latest linear RGBA AHB path has
focused CTS and pixel-readback coverage; other formats, browser workloads and
hardware video require their own relevant checks. No new Firefox workload or ANGLE
desktop path is introduced. Other Mali devices need their own acceptance;
the Turnip selector is covered by host checks, with physical Adreno regression
testing still separate.
