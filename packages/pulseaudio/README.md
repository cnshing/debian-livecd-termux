# Android PulseAudio presentation latency

This recipe carries Termux's PulseAudio 17.0-5 Android modules and build patches
from the builder revision recorded in `upstream.json`. Revision 101 repairs
the AAudio sink's playback latency reporting and callback shutdown; the desktop still selects its
existing sink until the runtime change is separately qualified.

The AAudio sink advertises `PA_SINK_LATENCY` and reports queued frames relative
to `AAudioStream_getTimestamp(CLOCK_MONOTONIC)`, extrapolated to the query time.
The callback currently being rendered is included before Android publishes it
in `getFramesWritten()`. Before hardware timestamps become available it uses
Android's consumed-frame counter as an explicitly logged startup estimate.
Configured buffer latency remains separate from measured playback latency.

`tests/audio/test-aaudio-latency.c` exercises presentation extrapolation, pending
callback data, future timestamps, exhausted queues and 44.1 kHz arithmetic.
Runtime qualification must additionally check timing, stream state transitions,
route changes, real playback and desktop integration. See
[the handoff](../../docs/native/handoff/mpv-audio-timing.md).

The client library ABI is unchanged. The recipe is a separate behavior-only CI
job so other desktop packages continue building against Termux's client headers
and libraries rather than requiring a rebuild of every PulseAudio consumer.

For private runtime qualification after extracting the CI package (not installing
it), run inside `livecd-native exec`:

```sh
python tests/audio/test-aaudio-device.py \
  --candidate-prefix /path/to/extracted/data/data/com.termux/files/usr \
  --out "$HOME/aaudio-qualification-new"
```

The output directory must be new. The test starts and cleans up its own Xvfb
display and PulseAudio server. It uses only a generated video/tone and records
the private sink monitor. It does not replace the desktop's server or record a
microphone. The default run includes two minutes of playback and requires at
least 90 seconds when customized. Passing this test does not qualify physical
lip sync, Bluetooth routing, calls or GNOME's UI.

AAudio callbacks synchronously request rendering from the sink IO thread. Closing
the stream on that same IO thread can deadlock while Android joins a callback
waiting for rendering. The main thread now detaches the handle through an IO
message before closing it, allowing IO to drain pending callbacks with STOP.
The device qualification includes suspend/resume and repeated module reloads.
