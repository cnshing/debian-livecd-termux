# Native EasyEffects / AutoEq verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> Recorded before the repository restructure. Paths were updated, but build steps and
> install locations describe the earlier on-device flow.

Verified on the established Galaxy Note10+ ARM64 rig, Android 11,
in native Termux (`com.termux`). The existing Debian/PRoot desktop
continued running. This is a separate implementation exercise from the earlier
[migration assessment](../termux-native-migration.md).

**Result: working experimental native playback EQ.** EasyEffects 7.2.5 and LSP
1.2.35 were compiled against Termux's Bionic libraries on the phone, packaged as
local `.deb` files, installed with APT, and exercised through an explicit
PipeWire-to-Termux-PulseAudio tunnel. No native GNOME installation was needed.

## Accepted checks

| Check | Result / evidence |
| --- | --- |
| Native package installation | `easyeffects` 7.2.5-1, `lsp-plugins-lv2` 1.2.35-1, `livecd-audio` 0.1.0-1; package metadata and hashes (`temp/docs/evidence/audio/packages.json`) |
| EasyEffects executable | `easyeffects --version` reports 7.2.5; native loader and libraries, not Debian binaries |
| Required equalizer plugin | Native `lv2ls` discovers `http://lsp-plug.in/plugins/lv2/para_equalizer_x32_lr` |
| GUI | Native EasyEffects opens on the existing Termux:X11 display; window capture (`temp/docs/evidence/audio/easyeffects.png`). GUI activation returns success after the included GApplication fix |
| AutoEq export | The official [HD 600 sample export](https://github.com/jaakkopasanen/AutoEq/blob/master/results/oratory1990/over-ear/Sennheiser%20HD%20600/Sennheiser%20HD%20600%20ParametricEQ.txt) converts to ten bands with the -6.3 dB preamp, imports locally, and loads through EasyEffects' CLI. The sample was a conversion test, not a choice of headphones for this phone |
| Import validation | Both native and PC conversion checks pass: stereo settings, headroom, shelf types, disabled filters, limits, invalid syntax; existing-file overwrite is refused |
| libc sorting port | Fourteen native comparisons against `std::sort`, including both comparison directions, empty inputs, duplicates and whole records, pass |
| PipeWire-to-PulseAudio transport | Quiet generated tones reach `OpenSL_ES_sink.monitor` on the existing Termux PulseAudio server |
| Gain processing | Requested -12 dB preamp measured **-12.003 dB** at the backend monitor; exploratory capture (`temp/docs/evidence/audio/signal-probe.json`) |
| Parametric filtering | A 1 kHz, Q=1, -12 dB bell measures **-12.002 dB at 1 kHz**, versus **-0.168 dB at 100 Hz**, on the final packaged build; final capture (`temp/docs/evidence/audio/final-filter-response.txt`) |
| Lifecycle | Start, repeated start, GUI activation, stop, restart and stop succeed; lifecycle output (`temp/docs/evidence/audio/lifecycle.txt`). The controller's clients use the private Pulse frontend and its environment export contains only three audio variables |
| Existing desktop | Original owner **2512**, Shell **2771**, and native PulseAudio **2637** remain running after the audio graph stops |

The filter check uses float32 stereo tones with amplitude 0.01 at 48 kHz,
records the backend's existing default sink monitor, and compares filtered RMS
against bypass RMS. It neither changes the backend default sink nor chooses a
Bluetooth/USB device. The loose acceptance bounds are less than 1 dB change at
100 Hz and -12 ±0.5 dB at 1 kHz. It verifies processing and transport rather than
subjective sound quality. The reproducible probe is [verify-signal.py](../../tests/audio/verify-signal.py).

## Porting work required

The original assumption that EasyEffects could simply be installed from the
configured official repositories was incorrect. Most dependencies were already
packaged, but EasyEffects and LSP LV2 needed local builds.

- EasyEffects: use `unsigned long` instead of glibc's `ulong`; enable upstream's
  libc++ workarounds; omit offline help requiring unavailable `itstool`; return
  success after handling GUI activation instead of invoking GLib's unhandled
  parent command-line handler. RNNoise remains disabled for this prototype.
- LSP: provide an allocation-free `qsort_r` fallback; avoid unavailable pthread
  cancellation controls and glibc `dlmopen`; use LSP's existing file-lock fallback
  instead of robust pthread mutexes; back named shared memory with files in
  Termux's private temporary directory; use Android-compatible environment,
  username and mount-option handling; link Termux `libiconv` explicitly.
- Session: wait for WirePlumber's default-node policy before choosing the tunnel;
  use its `policy` profile so it does not try to enumerate Android hardware;
  supervise the native processes without replacing the host audio daemon.
- Packaging: account for Termux's restrictive default umask when creating Debian
  control directories, and use one build job after a parallel linker crash.

The [build script](../../packages/easyeffects/build.sh) pins and checks both upstream source archives. Clean
archive extraction and patch applicability were checked on the PC, and every
modified source file used on the phone was compared with the checked-in patch
result. Final packaging was run incrementally against those compiled sources;
a second fully clean native compile was not repeated.

## Limits and final device state

This is a **local experimental port**, not a new official Termux repository
package or a maintained EasyEffects 8 port. The default desktop installer remains
unchanged. Only the equalizer, basic gain path, preset import/load and short
lifecycle tests are accepted here; this does not certify all EasyEffects/LSP
effects, long playback sessions, microphone processing, every GUI interaction,
or other Android releases.

Physical headphone discovery, Android-wide audio capture, and Bluetooth/USB
selection or switching were deliberately outside scope. Termux PulseAudio and
Android keep those responsibilities. No hardware output was selected by this
implementation.

The exploratory PipeWire tunnel-sink monitor capture returned no samples;
downstream PulseAudio monitor capture worked and was used for the measured
acceptance results. PipeWire also logs the absence of its optional D-Bus support
library, and WirePlumber logs unavailable system-bus services. Those messages
did not prevent the tested playback path.

The three packages and their native dependencies remain installed. The private
audio graph is stopped at handoff; the existing desktop/PulseAudio service
remains running. Temporary correction presets were removed and the output
plugin list was returned to empty. No headphone correction is selected for the
user. Source archives, build results, packages and logs remain in
`~/.cache/livecd-audio-build` on the phone. Copies of the three packages are in
this workspace's ignored `repo/incoming/` directory.
