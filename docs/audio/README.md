# Native Termux EasyEffects and AutoEq prototype

This is an **opt-in Android/Bionic port**, independent of the Debian/PRoot
desktop and of the proposed native GNOME migration. It builds local Termux
packages named `easyeffects`, `lsp-plugins-lv2`, and `livecd-audio`.
EasyEffects is not in the phone's configured official main/X11 package indexes;
`pkg install easyeffects` alone will not obtain this port. No repository was
published or added to the phone.

The playback path is:

```text
native applications → private pipewire-pulse → EasyEffects/LSP parametric EQ
                    → PipeWire Pulse tunnel → existing Termux PulseAudio → Android
```

Android and Termux PulseAudio retain responsibility for speakers, Bluetooth,
USB, and output changes. The tunnel does not select a hardware device. A
PulseAudio-compatible frontend alone does not send PipeWire output to a second
PulseAudio server: the explicit [Pulse tunnel module](https://docs.pipewire.org/page_module_pulse_tunnel.html)
provides that connection.

## Build and install

GitHub Actions cross-compiles the three packages from their recipes,
[`easyeffects`](../../packages/easyeffects/build.sh), [`lsp-plugins-lv2`](../../packages/lsp-plugins-lv2/build.sh)
and [`livecd-audio`](../../packages/livecd-audio/build.sh), which check both source archive hashes and apply
the included patches. To install them from the local apt repository, run this in native Termux:

```sh
python src/apply-overlays.py "Audio Effects"
```

That overlay also hides the stock EasyEffects launcher, which would bypass the bridge's private bus.
Run the conversion tests with `python tests/audio/test-autoeq.py`. CI runs them too. The sorting test,
[`test-sort.cpp`](../../tests/audio/test-sort.cpp), needs Bionic, so compile it on the phone against
LSP's patched `stdlib.cpp`.

Packages built by the earlier on-device script are kept locally in the Git-ignored
[`repo/incoming/`](../../repo/incoming).

The port pins GTK-based EasyEffects **7.2.5**, matching this repository's preset
format. Current upstream EasyEffects 8 uses Qt/KDE and would require a separate
port; this does not claim to package the current release. RNNoise and offline
Yelp help are disabled. LSP is built as LV2 effects without its standalone plugin
UIs; EasyEffects supplies its own effect controls. Effects needing other plugin
collections are outside this prototype's acceptance.

## Run

The [native desktop](../native/README.md#session-integrations) starts this existing
graph automatically when installed and stops its owned graph on desktop shutdown.
Applications still use `livecd-audio exec` or the audio environment to select it.
The commands below also work independently of that startup hook.

Start the existing Termux desktop, or start Termux PulseAudio normally. With
Termux:X11 running on `:0`:

```sh
# The current desktop's native Unix PulseAudio socket is recognized automatically.
livecd-audio start
livecd-audio ui

# Launch native audio clients through the private graph.
livecd-audio exec firefox
# Or apply only the audio endpoint variables to a native desktop launcher:
eval "$(livecd-audio env)"

livecd-audio status
livecd-audio stop
```

An independent Termux session can use `pulseaudio --start --exit-idle-time=-1`
first. To specify an existing logical server explicitly:

```sh
livecd-audio start --pulse-server unix:/path/to/pulse.sock
# A cookie-authenticated TCP server also accepts --pulse-cookie /path/to/cookie.
```

The controller owns its PipeWire, WirePlumber, pipewire-pulse, EasyEffects, and
private D-Bus session. It does not kill or replace existing desktop/audio
processes. Its Pulse frontend uses a private Unix socket, with no TCP listener.
Its settings backend is isolated from the guest desktop's DConf service. Normal
applications keep their existing desktop bus and settings backend when launched
with `exec` or the audio environment exports.

Only clients sent to this graph are processed. This does not capture audio from
unrelated Android apps or retroactively redirect the running PRoot desktop.
There is no microphone processing path in this implementation. Logs are in
`~/.local/state/livecd-audio/session.log`.

## AutoEq presets

At [autoeq.app](https://autoeq.app/), select your headphones and export
**EqualizerAPO ParametricEq**. Import and select that file explicitly:

```sh
livecd-autoeq "$HOME/storage/downloads/My headphones ParametricEQ.txt" --name 'My headphones'
livecd-audio preset 'My headphones'
```

The importer creates a local EasyEffects output preset, preserving the preamp
and both channels' peak/low-shelf/high-shelf filters in `APO (DR)` mode. It rejects
unsupported syntax, out-of-range parameters, and more than 32 bands. It refuses
to overwrite existing presets unless `--replace` is supplied. It does not install
AutoEq's scientific Python optimizer; it consumes the presets AutoEq generates.
No headphone model is selected automatically or enabled by the installer.

The live CD's existing OPRA converter also generates the same EasyEffects 7
community-preset format. To install that catalogue optionally, from the repo:

```sh
curl -fL https://opra.roonlabs.net/database_v1.jsonl -o "$TMPDIR/opra.jsonl"
python 'overlays/Audio Effects/lb/hooks/normal/scripts/opra2ee.py' \
    "$TMPDIR/opra.jsonl" "$PREFIX/share/easyeffects/output/OPRA"
rm "$TMPDIR/opra.jsonl"
```

This optional data download uses [OPRA's consumer mirror](https://github.com/opra-project/OPRA/blob/main/docs/CONSUMING.md).
It is not part of the pinned package build or a claim that the entire catalogue
was tested. In EasyEffects, import a chosen community preset locally to save or
associate it. Preset names retain the EQ author's credit, as in the live CD.

## Status and scope

See [verification](VERIFICATION.md) for actual device results and limitations.
This prototype does not establish reliability across Android versions and phones.

The checked official package indexes did not offer EasyEffects, JamesDSP,
PulseEffects, Carla, Qtractor or Qmmp under those names. Audacious is packaged,
but its presence is not evidence of an equivalent desktop-wide parametric EQ
workflow. No trivial packaged GUI replacement was established.

To remove the prototype after stopping it:

```sh
livecd-audio stop
apt remove livecd-audio easyeffects lsp-plugins-lv2
```

User presets, settings, logs, downloaded sources and the build cache are retained.
