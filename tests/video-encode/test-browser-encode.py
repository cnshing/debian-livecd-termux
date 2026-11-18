#!/data/data/com.termux/files/usr/bin/python
"""Check a browser's video encoder the way the installed launcher starts it.

The browser runs on a private Termux:X11 display with its own D-Bus session, profile and
termux-va daemon. Nothing touches the live desktop, its browser profiles or the shared daemon.

  webrtc         a canvas goes through an RTCPeerConnection loopback; the received picture must
                 have the sent size (a 640x360 call that arrives as 640x368 fails) and the sent
                 colours down to its last rows.
  mediarecorder  the canvas is recorded for three seconds; the file must decode in software to
                 pictures of the sent size and colours.
  webcodecs      60 canvas pictures are encoded, software decoded and checked against their
                 original colours, including the metadata supplied by the encoder.
  colour         known colour bars in full/limited range BT.601/BT.709 (I420 VideoFrames with
                 that colour space) go through MediaRecorder (MediaStreamTrackGenerator) and
                 WebCodecs; FFmpeg decodes each stream as its own signalling says and must get
                 the bars' RGB back. Control: the same streams with the signalling removed
                 must decode wrong for the full range sources.

  step           a WebRTC call whose sender is capped at 200 kb/s (RTCRtpSender maxBitrate)
                 for 15 s, then uncapped: the sent rate must stay within 25% of the cap from
                 3 s after the change, with no stall, and return to 90% of its earlier rate.
                 In both modes the call must first send at least 1.5 times the constraint.
  adapt          the same call with its media through a shaping UDP relay limited to 250 kb/s
                 for 20 s (packets over 150 ms of queue are dropped), then unlimited: congestion
                 control must bring the sent rate under 125% of the limit within 8 s, keep the
                 pictures moving (no second without a picture, at least 10 a second once
                 adapted), keep at least 320x180 with correct colours, keep loss under 5% once
                 adapted, and return to at least 90% of its earlier rate afterwards.
                 The canvas carries two bands of low-contrast noise in these modes, so the
                 encoder cannot meet a lower target by its content alone.

With --expect hardware (the default) the private daemon must also have run an encoder session
on a hardware component with pictures in and out. With --expect software it must have run none.
The received picture is saved as PNG: open it, a metric alone is not a pass.

Usage: test-browser-encode.py chromium|chrome|firefox --out NEW_DIRECTORY [--mode webrtc]
       [--codec h264] [--expect hardware|software]
"""
import argparse
import base64
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

PREFIX = Path('/data/data/com.termux/files/usr')
HERE = Path(__file__).resolve().parent
BROWSERS = HERE.parent / 'browsers'

PAGE = '''<!doctype html><title>encode probe</title><body><script>
const W = %(width)d, H = %(height)d, sleep = ms => new Promise(r => setTimeout(r, ms));
const c = document.createElement('canvas'); c.width = W; c.height = H;
const g = c.getContext('2d'); let n = 0;
// A hue field with a moving white bar: every row carries the same colour, so a band of
// padding at the bottom of a received picture shows as a different colour there.
// With texture=1, two bands of fresh low-contrast blocks away from the sampled rows cost
// bits at any target, so an encoder cannot meet a lower target by its content alone.
const texture = new URLSearchParams(location.search).get('texture') === '1';
const noise = new ImageData(W >> 2, 16), tile = new OffscreenCanvas(W >> 2, 16);
setInterval(() => { g.fillStyle = `hsl(${(n * 7) %% 360} 70%% 45%%)`; g.fillRect(0, 0, W, H);
  if (texture) {
    crypto.getRandomValues(noise.data);
    for (let i = 0; i < noise.data.length; i += 4) { const v = 108 + (noise.data[i] & 31);
      noise.data[i] = noise.data[i + 1] = noise.data[i + 2] = v; noise.data[i + 3] = 255; }
    tile.getContext('2d').putImageData(noise, 0, 0); g.imageSmoothingEnabled = false;
    for (const y of [H >> 3, (H * 5) >> 3]) g.drawImage(tile, 0, y, W, H >> 3);
  }
  g.fillStyle = 'white'; g.fillRect((n * 8) %% W, 0, 48, H); n++; }, 33);
const stream = c.captureStream(30);
function sample(source, width, height) {
  const k = document.createElement('canvas'); k.width = width; k.height = height;
  const kg = k.getContext('2d'); kg.drawImage(source, 0, 0, width, height);
  const row = kg.getImageData(0, height >> 1, width, 1).data; let best = 0, bar = 0;
  for (let x = 0; x < width; x++) { const s = row[x * 4] + row[x * 4 + 1] + row[x * 4 + 2]; if (s > best) { best = s; bar = x; } }
  const x = (bar + (width >> 1)) %% width, out = [];
  for (const y of [2, height >> 1, height - 2]) {
    const p = kg.getImageData(x, y, 1, 1).data, r = p[0] / 255, gg = p[1] / 255, b = p[2] / 255;
    const mx = Math.max(r, gg, b), mn = Math.min(r, gg, b), l = (mx + mn) / 2;
    out.push({y, rgb: [p[0], p[1], p[2]], s: +(mx === mn ? 0 : (mx - mn) / (1 - Math.abs(2 * l - 1))).toFixed(2), l: +l.toFixed(2)});
  }
  return {samples: out, png: k.toDataURL('image/png')};
}
const good = q => Math.abs(q.s - 0.7) < 0.12 && Math.abs(q.l - 0.45) < 0.08;
async function webrtc(codec) {
  const pc1 = new RTCPeerConnection(), pc2 = new RTCPeerConnection(); let c1 = 0, c2 = 0;
  pc1.onicecandidate = e => { if (e.candidate) { c1++; pc2.addIceCandidate(e.candidate); } };
  pc2.onicecandidate = e => { if (e.candidate) { c2++; pc1.addIceCandidate(e.candidate); } };
  const tr = pc1.addTransceiver(stream.getVideoTracks()[0], {direction: 'sendonly'});
  const caps = RTCRtpSender.getCapabilities('video').codecs.filter(x => x.mimeType.toLowerCase() === 'video/' + codec);
  if (!caps.length) return {codec, error: 'codec not offered'};
  tr.setCodecPreferences(caps);
  const o = await pc1.createOffer(); await pc1.setLocalDescription(o); await pc2.setRemoteDescription(o);
  const a = await pc2.createAnswer(); await pc2.setLocalDescription(a); await pc1.setRemoteDescription(a);
  const v = document.createElement('video'); v.muted = true; v.autoplay = true; document.body.append(v);
  pc2.getReceivers().forEach(r => { v.srcObject = new MediaStream([r.track]); });
  await sleep(8000);
  const shots = []; let png = null;
  for (let t = 0; t < 5; t++) { const s = sample(v, v.videoWidth || W, v.videoHeight || H); shots.push(s.samples); png = s.png; await sleep(300); }
  const out = {codec, candidates: [c1, c2], ice: pc1.iceConnectionState, received: [v.videoWidth, v.videoHeight], samples: shots, png};
  out.picture_ok = v.videoWidth === W && v.videoHeight === H && shots.every(s => s.every(good));
  (await pc1.getStats()).forEach(s => { if (s.type === 'outbound-rtp' && s.kind === 'video')
    Object.assign(out, {encoder: s.encoderImplementation, powerEfficientEncoder: s.powerEfficientEncoder,
      framesEncoded: s.framesEncoded, frameWidth: s.frameWidth, frameHeight: s.frameHeight}); });
  (await pc2.getStats()).forEach(s => { if (s.type === 'inbound-rtp' && s.kind === 'video')
    Object.assign(out, {decoder: s.decoderImplementation, framesDecoded: s.framesDecoded}); });
  pc1.close(); pc2.close(); v.remove();
  return out;
}
// The call runs a plan of phases [{seconds, limit (b/s on the relay, 0 for none), maxBitrate}].
// With relay=1 the media direction goes through the harness's shaping UDP relay: the sender
// gets only the relay's address as its remote candidate and the receiver learns the relay
// as a peer-reflexive one, so every RTP packet passes the shaper.
async function adapt(codec) {
  const q = new URLSearchParams(location.search), plan = JSON.parse(q.get('plan')), relay = q.get('relay') === '1';
  const pc1 = new RTCPeerConnection(), pc2 = new RTCPeerConnection(); let relayed = false;
  pc1.onicecandidate = e => { if (e.candidate && e.candidate.candidate && !relay) pc2.addIceCandidate(e.candidate); };
  pc2.onicecandidate = async e => {
    if (!e.candidate || !e.candidate.candidate) return;
    if (!relay) return pc1.addIceCandidate(e.candidate);
    const f = e.candidate.candidate.split(' ');
    if (relayed || f[2].toLowerCase() !== 'udp' || f[7] !== 'host' || !/^[0-9.]+$/.test(f[4])) return;
    relayed = true;
    const r = await (await fetch(`/relay?ip=${f[4]}&port=${f[5]}`)).json(); f[5] = String(r.port);
    pc1.addIceCandidate({candidate: f.join(' '), sdpMid: e.candidate.sdpMid, sdpMLineIndex: e.candidate.sdpMLineIndex});
  };
  const tr = pc1.addTransceiver(stream.getVideoTracks()[0], {direction: 'sendonly'});
  const caps = RTCRtpSender.getCapabilities('video').codecs.filter(x => x.mimeType.toLowerCase() === 'video/' + codec);
  if (!caps.length) return {codec, error: 'codec not offered'};
  tr.setCodecPreferences(caps);
  const o = await pc1.createOffer(); await pc1.setLocalDescription(o); await pc2.setRemoteDescription(o);
  const a = await pc2.createAnswer(); await pc2.setLocalDescription(a); await pc1.setRemoteDescription(a);
  const v = document.createElement('video'); v.muted = true; v.autoplay = true; document.body.append(v);
  pc2.getReceivers().forEach(r => { v.srcObject = new MediaStream([r.track]); });
  let presented = 0;
  const count = () => { presented++; v.requestVideoFrameCallback(count); };
  if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(count);
  const seconds = [], phases = []; let t = 0;
  for (const phase of plan) {
    if (relay) await fetch(`/limit?bps=${phase.limit || 0}`);
    if ('maxBitrate' in phase) {
      const p = tr.sender.getParameters(); if (!p.encodings || !p.encodings.length) p.encodings = [{}];
      if (phase.maxBitrate) p.encodings[0].maxBitrate = phase.maxBitrate; else delete p.encodings[0].maxBitrate;
      await tr.sender.setParameters(p);
    }
    for (let i = 0; i < phase.seconds; i++, t++) {
      await sleep(1000);
      const row = {t, limit: phase.limit || 0, maxBitrate: phase.maxBitrate || 0, presented,
                   width: v.videoWidth, height: v.videoHeight};
      (await pc1.getStats()).forEach(s => { if (s.type === 'outbound-rtp' && s.kind === 'video')
        Object.assign(row, {bytesSent: s.bytesSent, framesEncoded: s.framesEncoded, sentWidth: s.frameWidth,
          sentHeight: s.frameHeight, encoder: s.encoderImplementation, qpSum: s.qpSum, nack: s.nackCount, pli: s.pliCount}); });
      (await pc2.getStats()).forEach(s => { if (s.type === 'inbound-rtp' && s.kind === 'video')
        Object.assign(row, {bytesReceived: s.bytesReceived, framesDecoded: s.framesDecoded, packetsLost: s.packetsLost,
          framesDropped: s.framesDropped, decoder: s.decoderImplementation}); });
      if (relay) Object.assign(row, await (await fetch('/relaystats')).json());
      seconds.push(row);
    }
    const shot = sample(v, v.videoWidth || W, v.videoHeight || H);
    phases.push({limit: phase.limit || 0, maxBitrate: phase.maxBitrate || 0, received: [v.videoWidth, v.videoHeight],
                 samples: shot.samples, picture_ok: shot.samples.every(good), png: shot.png});
  }
  const out = {codec, relay, ice: pc1.iceConnectionState, seconds, phases};
  pc1.close(); pc2.close(); v.remove();
  return out;
}
async function mediarecorder(codec) {
  const types = {h264: ['video/mp4;codecs=avc1.42E01E', 'video/x-matroska;codecs=avc1', 'video/webm;codecs=h264'],
    vp8: ['video/webm;codecs=vp8'], vp9: ['video/webm;codecs=vp9'], hevc: ['video/mp4;codecs=hvc1.1.6.L93.B0']}[codec] || [];
  const type = types.find(t => MediaRecorder.isTypeSupported(t));
  if (!type) return {codec, error: 'no recordable type'};
  const recorder = new MediaRecorder(stream, {mimeType: type, videoBitsPerSecond: 2000000}), parts = [];
  recorder.ondataavailable = e => parts.push(e.data);
  const stopped = new Promise(r => recorder.onstop = r);
  recorder.start(); await sleep(3000); recorder.stop(); await stopped;
  const bytes = new Uint8Array(await new Blob(parts).arrayBuffer()); let text = '';
  for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
  return {codec, type, size: bytes.length, recording: btoa(text)};
}
async function webcodecs(codec) {
  const codecs = {h264: 'avc1.42001f', hevc: 'hvc1.1.6.L93.B0', vp8: 'vp8', vp9: 'vp09.00.10.08'};
  const config = {codec: codecs[codec], width: W, height: H, bitrate: 2000000,
    framerate: 30, hardwareAcceleration: 'prefer-hardware', bitrateMode: 'constant'};
  if (codec === 'h264') config.avc = {format: 'annexb'};
  if (codec === 'hevc') config.hevc = {format: 'annexb'};
  if (!(await VideoEncoder.isConfigSupported(config)).supported) return {codec, error: 'codec not offered'};
  const color = i => [(i * 37) %% 256, (i * 91 + 40) %% 256, (i * 53 + 90) %% 256];
  const canvas = new OffscreenCanvas(W, H), ctx = canvas.getContext('2d', {willReadFrequently: true});
  const chunks = [], errors = []; let metadata, failure = null, decoded = 0, png;
  const encoder = new VideoEncoder({output: (chunk, meta) => {
    chunks.push(chunk); if (meta.decoderConfig) metadata = meta.decoderConfig;
  }, error: e => { failure = String(e); }});
  encoder.configure(config);
  for (let i = 0; i < 60; i++) {
    ctx.fillStyle = `rgb(${color(i).join(',')})`; ctx.fillRect(0, 0, W, H);
    const f = new VideoFrame(canvas, {timestamp: i * 33333, duration: 33333});
    encoder.encode(f, {keyFrame: i %% 30 === 0}); f.close();
  }
  await encoder.flush(); encoder.close();
  const decoder = new VideoDecoder({output: f => {
    ctx.drawImage(f, 0, 0); const p = ctx.getImageData(W >> 1, H >> 1, 1, 1).data;
    const want = color(Math.round(f.timestamp / 33333));
    errors.push(Math.max(...want.map((v, k) => Math.abs(v - p[k])))); decoded++;
    const save = document.createElement('canvas'); save.width = W; save.height = H;
    save.getContext('2d').drawImage(f, 0, 0); png = save.toDataURL('image/png'); f.close();
  }, error: e => { failure = String(e); }});
  decoder.configure({...metadata, hardwareAcceleration: 'prefer-software'});
  for (const chunk of chunks) decoder.decode(chunk);
  await decoder.flush(); decoder.close();
  return {codec, chunks: chunks.length, decoded, max_color_error: Math.max(...errors),
    frames_over_16: errors.filter(e => e > 16).length, decoderConfig: metadata, error: failure, png,
    picture_ok: chunks.length === 60 && decoded === 60 && errors.every(e => e <= 16) && !failure};
}
const CONTROLS = %(controls)s;
function barFrame(control, timestamp) {
  const y = new Uint8Array(W * H), u = new Uint8Array(W * H / 4), v = new Uint8Array(W * H / 4);
  const bar = Math.floor(W / control.yuv.length), pick = x => control.yuv[Math.min(Math.floor(x / bar), control.yuv.length - 1)];
  for (let x = 0; x < W; x++) { const c = pick(x); for (let r = 0; r < H; r++) y[r * W + x] = c[0]; }
  for (let x = 0; x < W / 2; x++) { const c = pick(2 * x); for (let r = 0; r < H / 2; r++) { u[r * W / 2 + x] = c[1]; v[r * W / 2 + x] = c[2]; } }
  const data = new Uint8Array(W * H * 3 / 2); data.set(y); data.set(u, W * H); data.set(v, W * H * 5 / 4);
  return new VideoFrame(data, {format: 'I420', codedWidth: W, codedHeight: H, timestamp, colorSpace: control.space});
}
const b64 = bytes => { let s = ''; for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768)); return btoa(s); };
async function colour(codec) {
  const out = [];
  for (const control of CONTROLS) {
    // MediaRecorder from a generated track.
    const gen = new MediaStreamTrackGenerator({kind: 'video'}), writer = gen.writable.getWriter();
    const recorder = new MediaRecorder(new MediaStream([gen]), {mimeType: 'video/mp4;codecs=avc1.42E01E', videoBitsPerSecond: 4000000});
    const parts = []; recorder.ondataavailable = e => parts.push(e.data);
    const stopped = new Promise(r => recorder.onstop = r); recorder.start();
    for (let i = 0; i < 60; i++) { await writer.write(barFrame(control, i * 33333)); await sleep(33); }
    recorder.stop(); await stopped; writer.close();
    const rec = new Uint8Array(await new Blob(parts).arrayBuffer());
    // WebCodecs, Annex B chunks.
    const chunks = []; let meta = null, failure = null;
    const enc = new VideoEncoder({output: (c, m) => { const b = new Uint8Array(c.byteLength); c.copyTo(b); chunks.push(b);
      if (m && m.decoderConfig) meta = m.decoderConfig; }, error: e => { failure = String(e); }});
    enc.configure({codec: 'avc1.42001f', width: W, height: H, bitrate: 4000000, framerate: 30,
      hardwareAcceleration: 'prefer-hardware', bitrateMode: 'constant', avc: {format: 'annexb'}});
    for (let i = 0; i < 30; i++) { const f = barFrame(control, i * 33333); enc.encode(f, {keyFrame: i === 0}); f.close(); }
    await enc.flush(); enc.close();
    const all = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0)); let o = 0; for (const c of chunks) { all.set(c, o); o += c.length; }
    out.push({codec, control: control.name, recording: b64(rec), annexb: b64(all), decoderConfig: meta, error: failure});
  }
  return out;
}
(async () => { const q = new URLSearchParams(location.search), r = [];
  for (const k of q.get('codecs').split(',')) {
    try { const x = await ({mediarecorder, webcodecs, webrtc, colour, adapt}[q.get('mode')](k)); Array.isArray(x) ? r.push(...x) : r.push(x); }
    catch (e) { r.push({codec: k, error: String(e)}); } }
  window.RESULT = r; })();
</script>'''

LAUNCHER = '''#!{python}
import json, os, sys
sys.path.insert(0, {modules!r})
import acceleration
argv, env = acceleration.prepare({profile!r}, [{binary!r}, *sys.argv[1:]], {abi!r}, 'auto')
open({record!r}, 'w').write(json.dumps({{'argv': argv, 'env': {{k: v for k, v in env.items()
    if k.startswith(('VK_', 'TERMUX_VA', 'LIBVA', 'LD_', 'BIONILUX', 'GALLIUM', 'MOZ_'))}}}}, indent=1))
os.execve(argv[0], argv, env)
'''


def wait(check, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError('Timed out waiting for ' + what)


def decoded_recording(path, width, height):
    """Software-decode a recording: frame count, size, and the hue field's colour in the middle
    and the last rows of a late frame."""
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries',
                            'stream=codec_name,width,height,nb_read_frames', '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=120)
    stream = (json.loads(probe.stdout or '{}').get('streams') or [{}])[0]
    info = {'codec': stream.get('codec_name'), 'size': [stream.get('width'), stream.get('height')],
            'frames': int(stream.get('nb_read_frames') or 0)}
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-vf', 'select=eq(n\\,20)',
                          '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                         capture_output=True, timeout=120).stdout
    samples = []
    if len(raw) == width * height * 3:
        middle = raw[(height // 2) * width * 3:(height // 2 + 1) * width * 3]
        bar = max(range(width), key=lambda x: sum(middle[x * 3:x * 3 + 3]))
        x = (bar + width // 2) % width
        for y in (2, height // 2, height - 2):
            r, g, b = (value / 255 for value in raw[(y * width + x) * 3:(y * width + x) * 3 + 3])
            high, low = max(r, g, b), min(r, g, b)
            light = (high + low) / 2
            samples.append({'y': y, 's': round(0 if high == low else (high - low) / (1 - abs(2 * light - 1)), 2),
                            'l': round(light, 2)})
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path), '-vf', 'select=eq(n\\,20)',
                        '-frames:v', '1', str(path.with_suffix('.png'))], timeout=120, check=False)
    info['samples'] = samples
    info['picture_ok'] = (info['size'] == [width, height] and info['frames'] >= 30 and len(samples) == 3 and
                          all(abs(q['s'] - 0.7) < 0.12 and abs(q['l'] - 0.45) < 0.08 for q in samples))
    return info


COLOR_SPACE_JS = {'bt601': {'primaries': 'smpte170m', 'transfer': 'smpte170m', 'matrix': 'smpte170m'},
                  'bt709': {'primaries': 'bt709', 'transfer': 'bt709', 'matrix': 'bt709'}}


def colour_controls():
    import encode_oracle as oracle
    return [{'name': f'{"full" if full else "limited"}-{matrix}', 'matrix': matrix, 'full': full,
             'space': {**COLOR_SPACE_JS[matrix], 'fullRange': full},
             'yuv': [oracle.rgb_to_yuv(rgb, matrix, full) for rgb in oracle.COLOR_BARS]}
            for matrix in ('bt601', 'bt709') for full in (False, True)]


def check_colour_case(case, out, width, height):
    """Decode a colour case's recording and WebCodecs stream with FFmpeg as signalled."""
    import encode_oracle as oracle
    name = case['control']
    case['full'] = name.startswith('full-')
    case['streams'] = {}
    ok = not case.get('error')
    for kind, suffix in (('recording', '.mp4'), ('annexb', '.h264')):
        path = out / f'colour-{name}-{kind}{suffix}'
        path.write_bytes(base64.b64decode(case.pop(kind)))
        found, worst = oracle.bar_errors(path, width, height)
        info = {'signalled': oracle.stream_color(path), 'bars': found, 'error': worst}
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path), '-vf', 'select=eq(n\\,5)',
                        '-frames:v', '1', str(path.with_suffix('.png'))], timeout=120, check=False)
        if case['full'] and kind == 'annexb':
            # Control: strip the signalling; a full range source must then decode wrong.
            bare = out / f'colour-{name}-unsignalled.h264'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path), '-c', 'copy', '-bsf:v',
                            'h264_metadata=video_full_range_flag=0:colour_primaries=2:'
                            'transfer_characteristics=2:matrix_coefficients=2', str(bare)], timeout=120, check=False)
            unused, bare_worst = oracle.bar_errors(bare, width, height)
            info['control_unsignalled_error'] = bare_worst
            info['control_fails'] = bare_worst is not None and bare_worst > oracle.COLOR_TOLERANCE
            ok = ok and info['control_fails']
        info['ok'] = worst is not None and worst <= oracle.COLOR_TOLERANCE
        ok = ok and info['ok']
        case['streams'][kind] = info
    case['picture_ok'] = ok


def encoder_sessions(log):
    """Hardware encoder sessions in a termux-va log: (component, pictures in, packets out)."""
    names, sessions = {}, []
    for line in log.splitlines():
        match = re.search(r'\[(\d+)\] selected encoder: (\S+)', line)
        if match:
            names[match[1]] = match[2]
        match = re.search(r'\[(\d+)\] encoder session end: (\d+) units in, (\d+) packets out', line)
        if match:
            sessions.append((names.get(match[1], '?'), int(match[2]), int(match[3])))
    return sessions


class Relay:
    """A UDP relay between a WebRTC sender and receiver that shapes the sender's direction.

    Socket "near" faces the sender, which has it as its only remote candidate; socket "far"
    faces the receiver. Sender-to-receiver packets leave through a queue drained at the current
    limit; one that would wait more than MAX_QUEUE seconds is dropped, as at a congested link.
    Receiver-to-sender packets (RTCP feedback, STUN answers) pass at once."""
    MAX_QUEUE = 0.15

    def __init__(self, ip, port):
        import socket
        self.target, self.sender = (ip, port), None
        self.near = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.far = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for sock in (self.near, self.far):
            sock.bind((ip, 0))
        self.port = self.near.getsockname()[1]
        self.limit, self.departure, self.lock = 0, 0.0, threading.Lock()
        self.queue, self.ready = [], threading.Condition(self.lock)
        self.stats = {'relayed_bytes': 0, 'relayed_packets': 0, 'dropped_packets': 0, 'feedback_packets': 0}
        self.running = True
        for target in (self.forward, self.back, self.drain):
            threading.Thread(target=target, daemon=True).start()

    def set_limit(self, bps):
        with self.lock:
            self.limit = bps

    def forward(self):
        while self.running:
            data, self.sender = self.near.recvfrom(65536)
            now = time.monotonic()
            with self.lock:
                if not self.limit:
                    self.queue.append((now, data))
                else:
                    start = max(now, self.departure)
                    if start - now > self.MAX_QUEUE:
                        self.stats['dropped_packets'] += 1
                        continue
                    # IP and UDP headers count against the link too.
                    self.departure = start + (len(data) + 28) * 8 / self.limit
                    self.queue.append((self.departure, data))
                self.ready.notify()

    def drain(self):
        while self.running:
            with self.lock:
                while not self.queue:
                    self.ready.wait()
                when, data = self.queue[0]
                delay = when - time.monotonic()
                if delay > 0:
                    self.ready.wait(delay)
                    continue
                self.queue.pop(0)
                self.stats['relayed_bytes'] += len(data)
                self.stats['relayed_packets'] += 1
            self.far.sendto(data, self.target)

    def back(self):
        while self.running:
            data, _ = self.far.recvfrom(65536)
            if self.sender:
                self.stats['feedback_packets'] += 1
                self.near.sendto(data, self.sender)


PLANS = {'step': [{'seconds': 12, 'maxBitrate': 0}, {'seconds': 15, 'maxBitrate': 200000},
                  {'seconds': 12, 'maxBitrate': 0}],
         'adapt': [{'seconds': 12, 'limit': 0}, {'seconds': 20, 'limit': 250000}, {'seconds': 20, 'limit': 0}]}


def judge_adaptation(case, mode):
    """Per-second rates and the pass criteria described at the top."""
    rows, failures = case.get('seconds') or [], []
    if not rows:
        return {'ok': False, 'failures': ['no statistics']}

    def delta(key, i):
        now, before = rows[i].get(key), rows[i - 1].get(key) if i else 0
        return None if now is None or before is None else now - before
    sent = [round((delta('bytesSent', i) or 0) * 8 / 1000, 1) for i in range(len(rows))]
    received = [round((delta('bytesReceived', i) or 0) * 8 / 1000, 1) for i in range(len(rows))]
    pictures = [delta('presented', i) if rows[i].get('presented') else delta('framesDecoded', i) for i in range(len(rows))]
    plan, start, report = PLANS[mode], 0, {'sent_kbps': sent, 'received_kbps': received, 'pictures_per_second': pictures}
    constrained = next(i for i, phase in enumerate(plan) if phase.get('limit') or phase.get('maxBitrate'))
    for index, phase in enumerate(plan):
        span = range(start, start + phase['seconds'])
        start += phase['seconds']
        target = (phase.get('limit') or phase.get('maxBitrate') or 0) / 1000
        if index == constrained:
            constrained_start = span[0]
            # A sender already under the constraint proves nothing about adapting to it.
            before = sent[span[0] - 5:span[0]]
            if sum(before) / len(before) < 1.5 * target:
                failures.append(f'sent only {sum(before) / len(before):.0f} kb/s before a {target:g} kb/s '
                                'constraint; the test needs at least 1.5 times it')
            allowed = 8 if mode == 'adapt' else 3
            reach = next((i - span[0] for i in span if all(sent[j] <= 1.25 * target for j in range(i, span[-1] + 1))), None)
            report['reach_seconds'] = reach
            if reach is None or reach > allowed:
                failures.append(f'sent rate not under {1.25 * target:g} kb/s within {allowed} s of the change (after {reach})')
            else:
                steady = [sent[j] for j in range(span[0] + reach, span[-1] + 1)]
                if mode == 'step' and min(steady) < 0.75 * target:
                    failures.append(f'sent rate fell to {min(steady)} kb/s under a {target:g} kb/s cap')
                if mode == 'adapt':
                    late = received[span[-1] - 9:span[-1] + 1]
                    if sum(late) / len(late) < 0.5 * target:
                        failures.append(f'received only {sum(late) / len(late):.0f} kb/s through a {target:g} kb/s link')
                    first, last = rows[span[0] + reach - 1], rows[span[-1]]
                    sent_packets = last['relayed_packets'] + last['dropped_packets'] - first['relayed_packets'] - first['dropped_packets']
                    loss = (last['dropped_packets'] - first['dropped_packets']) / max(sent_packets, 1)
                    report['loss_after_reach'] = round(loss, 4)
                    if loss > 0.05:
                        failures.append(f'{loss:.1%} of packets dropped after adapting')
                slow = [pictures[j] for j in range(span[0] + reach, span[-1] + 1)]
                if min(p or 0 for p in slow) < 10:
                    failures.append(f'only {min(p or 0 for p in slow)} pictures in a second once adapted')
        if index == constrained + 1:
            # Back to the rate before the constraint. Not higher: libwebrtc caps a stream by its
            # resolution (500 kb/s at 320x180), and its H.264 quality scaler keeps a busy picture
            # small (QP above 24), so a call may legitimately stay at its starting size.
            late = sent[span[-1] - 4:span[-1] + 1]
            before = sent[constrained_start - 5:constrained_start]
            report['recovered_kbps'] = round(sum(late) / len(late), 1)
            report['before_kbps'] = round(sum(before) / len(before), 1)
            if report['recovered_kbps'] < 0.9 * report['before_kbps']:
                failures.append(f'sent rate did not return to {report["before_kbps"]} kb/s ({report["recovered_kbps"]})')
    stalls = [i for i in range(3, len(rows)) if not pictures[i]]
    if stalls:
        failures.append(f'no picture in seconds {stalls}')
    for phase in case.get('phases', []):
        if not phase.get('picture_ok') or phase['received'][0] < 320 or phase['received'][1] < 180:
            failures.append(f'picture at limit {phase["limit"]} / cap {phase["maxBitrate"]}: {phase["received"]} '
                            f'{"colours wrong" if not phase.get("picture_ok") else "too small"}')
    report['failures'] = failures
    report['ok'] = not failures
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('browser', choices=('chromium', 'chrome', 'firefox'))
    p.add_argument('--out', type=lambda value: Path(value).resolve(), required=True)
    p.add_argument('--mode', choices=('webrtc', 'mediarecorder', 'webcodecs', 'colour', 'step', 'adapt'), default='webrtc')
    p.add_argument('--codec', action='append', help='h264 (default), vp8, vp9 or hevc; repeatable')
    p.add_argument('--expect', choices=('hardware', 'software'), default='hardware')
    # Colour mode needs 640x480 or more: smaller MediaRecorder tracks use Chromium's software encoder.
    p.add_argument('--size', default=None)
    p.add_argument('--firefox-encode', action='store_true',
                   help='experiment with Firefox encoding without changing the installed default')
    p.add_argument('--modules', default=str(Path.home() / '.local/lib/livecd-native'),
                   help='directory of the launcher modules (acceleration.py) to test')
    p.add_argument('--browser-command', type=lambda value: Path(value).resolve(),
                   help='start the browser with this command instead of the launcher')
    args = p.parse_args()
    if os.environ.get('LIVECD_ENCODE_TEST_BUS') != '1':
        # Start from the environment the desktop gives its programs (its preloads present the
        # GPU as /dev/dri/renderD128, which Firefox's encoder opens), on a bus of its own.
        # The tested acceleration module is imported first: desktop.py imports it by name.
        sys.path.insert(0, args.modules)
        import acceleration  # noqa: F401
        from desktop import environment
        os.environ['ANDROID_PROCFS_COMPAT'] = '0'
        env = environment('zink')
        for key in ('LIVECD_NATIVE_SESSION', 'XAUTHORITY', 'PULSE_SERVER'):
            env.pop(key, None)
        env['LIVECD_ENCODE_TEST_BUS'] = '1'
        os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, *sys.argv], env)
    codecs = args.codec or ['h264']
    args.size = args.size or ('1280x720' if args.mode == 'colour' else '640x360')
    width, height = (int(value) for value in args.size.split('x'))
    out = args.out
    out.mkdir(parents=True)
    for name in ('config', 'cache', 'data', 'state', 'runtime'):
        (out / name).mkdir(mode=0o700)
    # The browser's crash dumps and caches stay out of the user's profile.
    os.environ.update(XDG_CONFIG_HOME=str(out / 'config'), XDG_CACHE_HOME=str(out / 'cache'),
                      XDG_DATA_HOME=str(out / 'data'), XDG_STATE_HOME=str(out / 'state'),
                      XDG_RUNTIME_DIR=str(out / 'runtime'))
    spec = importlib.util.spec_from_file_location('probe', BROWSERS / 'test-browsers.py')
    os.environ.setdefault('PREFIX', str(PREFIX))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe.OUT = out
    tag = 'encode-test-' + uuid.uuid4().hex
    # Stop at the first GPU-process crash: a browser left to restart it in a loop has brought
    # Android's low-memory killer down on the whole desktop before.
    launch = probe.launch

    def guarded(command, name):
        process = launch(command, name)

        def monitor():
            while process.poll() is None:
                log = out / (name + '.log')
                text = log.read_text(errors='replace') if log.exists() else ''
                if any(marker in text for marker in ('Check failed:', 'GPU process exited unexpectedly', 'FATAL:')):
                    (out / 'crash-stop.txt').write_text('Stopped at the first GPU crash or fatal log line\n')
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    return
                time.sleep(0.25)
        threading.Thread(target=monitor, daemon=True).start()
        return process
    probe.launch = guarded
    display = next(n for n in range(80, 99) if not (PREFIX / f'tmp/.X11-unix/X{n}').exists()
                   and not (PREFIX / f'tmp/.X{n}-lock').exists())
    os.environ['DISPLAY'] = f':{display}'
    children, socket_dir = [], None
    result = {'browser': args.browser, 'mode': args.mode, 'expect': args.expect, 'display': display}
    try:
        with (out / 'x-server.log').open('w') as log:
            children.append(subprocess.Popen([str(BROWSERS / 'private-lorie/private-lorie'), f':{display}'],
                                             stdout=log, stderr=log, start_new_session=True))
        wait(lambda: subprocess.run(['xdpyinfo'], capture_output=True).returncode == 0, 60, 'the X server')
        # A short path: a Unix socket's path is limited to 107 bytes.
        socket_dir = Path(subprocess.run(['mktemp', '-d', str(PREFIX / 'tmp/enc-XXXXXX')], capture_output=True,
                                         text=True, check=True).stdout.strip())
        os.environ['TERMUX_VA_SOCKET'] = str(socket_dir / 'va.sock')
        daemon_env = {k: v for k, v in os.environ.items() if k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')}
        with (out / 'termux-va.log').open('w') as log:
            children.append(subprocess.Popen([os.environ.get('TERMUX_VA_DAEMON', str(PREFIX / 'bin/termux-va')), '-t'],
                                             env=daemon_env, stdout=log, stderr=log, start_new_session=True))
        wait(lambda: (socket_dir / 'va.sock').is_socket(), 20, 'the termux-va socket')
        command = args.browser_command
        binary = {'chromium': PREFIX / 'lib/chromium/chrome', 'chrome': PREFIX / 'opt/google/chrome/chrome',
                  'firefox': PREFIX / 'bin/firefox'}[args.browser]
        if command is None:
            command = out / 'launcher.py'
            command.write_text(LAUNCHER.format(python=sys.executable, modules=args.modules, profile=args.browser,
                                               binary=str(binary), abi='glibc' if args.browser == 'chrome' else 'bionic',
                                               record=str(out / 'argv.json')))
            command.chmod(0o700)
        page = (PAGE % {'width': width, 'height': height, 'controls': json.dumps(colour_controls())}).encode()
        relays = []

        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import parse_qs, urlsplit
                url = urlsplit(self.path)
                query = {key: values[0] for key, values in parse_qs(url.query).items()}
                body, kind = page, 'text/html'
                if url.path == '/relay':
                    relays.append(Relay(query['ip'], int(query['port'])))
                    body, kind = json.dumps({'port': relays[-1].port}).encode(), 'application/json'
                elif url.path == '/limit':
                    for relay in relays:
                        relay.set_limit(int(query['bps']))
                    body, kind = b'{}', 'application/json'
                elif url.path == '/relaystats':
                    body, kind = json.dumps(relays[-1].stats if relays else {}).encode(), 'application/json'
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *unused):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Page)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        probe.wait_for = lambda check, timeout, what: wait(check, timeout, what)
        profile = out / 'profile'
        if args.browser == 'firefox':
            profile.mkdir()
            os.environ.update(MOZ_LOG='FFmpegVideo:4,PlatformEncoderModule:4', MOZ_LOG_FILE=str(out / 'mozilla.log'))
            # The launcher manages preferences only in its own profile, so apply its decisions
            # to this disposable one the same way.
            sys.path.insert(0, args.modules)
            import acceleration
            encode = args.firefox_encode or acceleration.firefox_encode_ready(os.environ['TERMUX_VA_SOCKET'])
            result['launcher_firefox_encode'] = encode
            result['experimental_firefox_encode'] = args.firefox_encode
            acceleration.firefox_preferences(profile, True, True, encode=encode)
            browser = probe.Firefox(command, profile, tag, prefs=(
                ('extensions.enabledScopes', 1), ('extensions.autoDisableScopes', 15),
                ('media.navigator.permission.disabled', True), ('media.navigator.streams.fake', False),
                # The relay needs the receiver's real address, not an mDNS name.
                ('media.peerconnection.ice.obfuscate_host_addresses', False)),
                preserve_prefs=True)
        else:
            browser = probe.Chromium(command, profile, tag, (
                '--enable-logging=stderr', '--vmodule=*vaapi*=2,*video_encode*=2', '--ozone-platform=x11',
                '--disable-extensions', '--password-store=basic', '--disable-breakpad', '--disable-crash-reporter'))
        result['version'] = browser.version
        query = f'mode={args.mode}&codecs=' + ','.join(codecs)
        if args.mode in PLANS:
            from urllib.parse import quote
            query = (f'mode=adapt&codecs={",".join(codecs)}&texture=1&relay={int(args.mode == "adapt")}'
                     f'&plan={quote(json.dumps(PLANS[args.mode]))}')
        browser.open(f'http://127.0.0.1:{server.server_address[1]}/?' + query)
        cases = wait(lambda: browser.evaluate('window.RESULT'), 240, 'the page')
        browser.quit()
        for case in cases:
            if args.mode == 'colour':
                if 'control' in case:
                    check_colour_case(case, out, width, height)
                continue
            for number, phase in enumerate(case.get('phases', [])):
                (out / f'received-{case["codec"]}-phase{number}.png').write_bytes(
                    base64.b64decode(phase.pop('png').split(',', 1)[1]))
            if args.mode in PLANS and 'seconds' in case:
                case['adaptation'] = judge_adaptation(case, args.mode)
                case['picture_ok'] = case['adaptation']['ok']
            if case.get('png'):
                (out / f'received-{case["codec"]}.png').write_bytes(base64.b64decode(case.pop('png').split(',', 1)[1]))
            if case.get('recording'):
                suffix = '.mp4' if 'mp4' in case['type'] else '.mkv' if 'matroska' in case['type'] else '.webm'
                recording = out / f'recording-{case["codec"]}{suffix}'
                recording.write_bytes(base64.b64decode(case.pop('recording')))
                case.update(decoded_recording(recording, width, height))
        result['cases'] = cases
    except Exception as error:
        result['error'] = str(error)
    finally:
        if hasattr(probe, 'stop'):
            probe.stop(tag)
        for child in reversed(children):
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in children:
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        for path in (PREFIX / f'tmp/.X11-unix/X{display}', PREFIX / f'tmp/.X{display}-lock'):
            path.unlink(missing_ok=True)
        if socket_dir:
            shutil.rmtree(socket_dir, ignore_errors=True)
        log = out / 'termux-va.log'
        sessions = encoder_sessions(log.read_text(errors='replace')) if log.exists() else []
        result['encoder_sessions'] = sessions
        hardware = [s for s in sessions if s[1] >= 30 and s[2] >= 30
                    and not s[0].startswith(('OMX.google.', 'c2.android.'))]
        result['crashed'] = (out / 'crash-stop.txt').exists()
        pictures = bool(result.get('cases')) and all(case.get('picture_ok') for case in result['cases'])
        result['ok'] = (pictures and not result['crashed'] and
                        (len(hardware) >= len(codecs) if args.expect == 'hardware' else not sessions))
        (out / 'result.json').write_text(json.dumps(result, indent=1) + '\n')
        print(json.dumps(result, indent=1))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
