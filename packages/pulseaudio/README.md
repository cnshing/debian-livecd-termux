# Android PulseAudio presentation latency

This recipe carries Termux's PulseAudio 17.0-5 Android modules and build patches
from the builder revision recorded in `upstream.json`. Revision 100 changes only
the AAudio sink's playback latency reporting; the desktop still selects its
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
