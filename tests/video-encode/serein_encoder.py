"""Serein's Linux camera encoder, element for element.

From crates/discord-voice/src/camera/encode_linux.rs at
v1.0.0-nightly.20261028.68: appsrc with packed RGB, videoconvert, vah264enc
set only through properties it declares, h264parse with config-interval=-1
and an appsink that demands Constrained Baseline. encode() pushes one picture
and returns at most one access unit, waiting as Serein does.
"""
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import GObject, Gst, GstApp  # noqa: E402

import encode_oracle as oracle  # noqa: E402

Gst.init(None)


def make(name):
    element = Gst.ElementFactory.make(name)
    if not element:
        raise RuntimeError('missing element ' + name)
    return element


def set_number(element, name, value):
    # Serein sets a property only when the element declares it as an integer.
    spec = element.find_property(name)
    if spec and spec.value_type in (GObject.TYPE_INT, GObject.TYPE_UINT, GObject.TYPE_INT64, GObject.TYPE_UINT64):
        element.set_property(name, value)


def set_flag(element, name, value):
    spec = element.find_property(name)
    if spec and spec.value_type == GObject.TYPE_BOOLEAN:
        element.set_property(name, value)


class SereinCameraEncoder:
    """encode_linux.rs: Config {640x480, 15 fps, 600 kb/s, max 128 KiB, Baseline}."""
    MAX_IN_FLIGHT = 6

    def __init__(self, width, height, fps, bit_rate, key_interval=1):
        self.width, self.height, self.fps = width, height, fps
        encoder = make('vah264enc')
        set_number(encoder, 'bitrate', bit_rate // 1000)
        set_number(encoder, 'key-int-max', key_interval)
        set_number(encoder, 'gop-size', key_interval)
        set_number(encoder, 'b-frames', 0)
        set_number(encoder, 'bframes', 0)
        set_number(encoder, 'rc-lookahead', 0)
        set_flag(encoder, 'zerolatency', True)
        self.source = GstApp.AppSrc(caps=Gst.Caps.from_string(
            f'video/x-raw,format=RGB,width={width},height={height},framerate={fps}/1'))
        self.source.set_stream_type(GstApp.AppStreamType.STREAM)
        self.source.set_property('format', Gst.Format.TIME)
        self.source.set_property('is-live', True)
        self.source.set_property('do-timestamp', True)
        self.source.set_property('block', False)
        self.source.set_property('max-bytes', width * height * 3 * self.MAX_IN_FLIGHT)
        self.frames = GstApp.AppSink(caps=Gst.Caps.from_string(
            'video/x-h264,stream-format=byte-stream,alignment=au,profile=constrained-baseline'))
        self.frames.set_property('sync', False)
        self.frames.set_property('max-buffers', self.MAX_IN_FLIGHT)
        self.frames.set_property('drop', False)
        convert, parse = make('videoconvert'), make('h264parse')
        set_number(parse, 'config-interval', -1)
        self.pipeline = Gst.Pipeline()
        chain = [self.source, convert, encoder, parse, self.frames]
        for element in chain:
            self.pipeline.add(element)
        for a, b in zip(chain, chain[1:]):
            if not a.link(b):
                raise RuntimeError(f'cannot link {a.get_name()} to {b.get_name()}')
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('pipeline refused to play')
        self.in_flight = 0
        self.pictures = 0

    def encode(self, rgb):
        """Serein's encode(): one picture in, at most one access unit out."""
        if self.pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR):
            raise RuntimeError('encoder reported an error')
        self.pictures += 1
        buffer = Gst.Buffer.new_wrapped(rgb)
        buffer.offset = self.pictures
        if self.source.push_buffer(buffer) != Gst.FlowReturn.OK:
            raise RuntimeError('push failed')
        self.in_flight += 1
        frame_ms = 1000 // max(self.fps, 1)
        wait = 0 if self.in_flight <= 1 else frame_ms if self.in_flight < self.MAX_IN_FLIGHT else frame_ms * 4
        sample = self.frames.try_pull_sample(wait * Gst.MSECOND)
        if not sample:
            if self.in_flight >= self.MAX_IN_FLIGHT:
                raise RuntimeError('encoder stopped returning pictures')
            return None
        self.in_flight -= 1
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        data = bytes(info.data)
        buffer.unmap(info)
        return data, bool(buffer.get_flags() & Gst.BufferFlags.DELTA_UNIT)

    def close(self):
        self.pipeline.set_state(Gst.State.NULL)


def rejected(unit, delta):
    """Serein drops to software for good on any of these."""
    report = oracle.idr_report(unit, 'h264')
    return delta or not report['idr'] or report['idr_without_parameter_sets'] or len(unit) > 128 * 1024


def drain(encoder):
    """Access units the encoder still holds at the end of the stream."""
    encoder.source.end_of_stream()
    units = []
    while (sample := encoder.frames.try_pull_sample(2 * Gst.SECOND)):
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        units.append(bytes(info.data))
        buffer.unmap(info)
    return units
