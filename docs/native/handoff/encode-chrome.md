# Handoff: Google Chrome hardware encoding

State on 2026-11-14. Chrome is Google's prebuilt glibc binary under Bionilux; it cannot be
patched. Shared rules and pass criteria: [README.md](README.md).

## Status

**Off by default, and mostly blocked.**

| Use | Adreno | Mali (S20) |
| --- | --- | --- |
| WebRTC | not run | **cannot connect**: zero ICE candidates, zero frames |
| WebCodecs `VideoEncoder` | not run | **crashes the GPU process** with `AcceleratedVideoEncoder`, as Chromium does |

## Blocker 1: no network for WebRTC

- Chrome logs `Could not bind NETLINK socket: Permission denied` and finds no network
  interfaces. This is not a video problem: it probably breaks every Chrome WebRTC call, hardware
  or not.
- Chromium's `AddressTrackerLinux` enumerates interfaces over netlink directly, which bypasses
  Bionilux's existing `getifaddrs` fallback. Termux's own Chromium carries
  `1013-chromium-net-address-tracker.patch`, which handles a denied multicast subscription and
  link enumeration, and it does gather candidates on the same phone. Chrome has no such patch.
- **Possible fix:** make Bionilux answer the netlink route dump Chrome sends (or fail it in a
  way that makes Chrome fall back), in `packages/bionilux` and
  `overlays/Browser+Chromium/browsers/bionilux-0.5.0-browser.patch`. Why the bind is denied has
  not been established; compare what the two Chromiums do with `strace` first.

## Blocker 2: the WebCodecs crash cannot be fixed here

Same cause as Chromium ([encode-chromium.md](encode-chromium.md)): Chromium's Linux WebCodecs
adapter asks for GPU-memory input frames, and a `CHECK` aborts when they are plain shared
memory. The fix is a source patch, and Chrome is a closed binary. Only Google can change it.

So turning on `AcceleratedVideoEncoder` for Chrome would always bring the crash with it, even
after blocker 1 is fixed. **Whether WebRTC hardware encoding is worth that is the user's
decision**, and nobody has made it.

## Next steps

1. Fix blocker 1, then rerun Chrome's WebRTC loopback in software, and then with the flag.
2. Ask the user whether to enable the flag for Chrome despite blocker 2. Until then, leave it
   off.

## Where things are

| What | Where |
| --- | --- |
| Bionilux | `packages/bionilux`, `overlays/Browser+Chromium/browsers/` |
| Chrome flags | `command_line()` in `src/native/acceleration.py` |
| History | [VIDEO-ENCODING-HANDOFF.md](../VIDEO-ENCODING-HANDOFF.md) |
