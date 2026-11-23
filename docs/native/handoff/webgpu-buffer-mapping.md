# WebGPU buffer mapping on the Note10+

## Investigation, 2026-11-22 (installed qualification pending)

The original error reproduces in Chrome 157.0.8103.78 with the installed launcher
configuration, android-vaapi-glibc 14 and Mesa 26.2.6-108. A syscall trace identifies
an address-placement failure in V8's partially reserved sandbox, rather than a
failed memfd allocation or exhausted WebGL transfer-buffer budget.

The failing renderer creates a `shared-memory-region` memfd, truncates it to
2,097,152 bytes, and adds its seals successfully. It then makes ten shared mmap
requests with hints above `0x8000000000`, the kernel's 39-bit userspace limit.
Every mmap succeeds at `0x599e350000`. V8 unmaps each result because it is outside
the permitted, unreserved portion of its sandbox, then reports allocation failure.
There is **no failing syscall errno** for these ten mappings. The smaller
131,072-byte mapping immediately afterward succeeds at an acceptable address.

The source path is:

- [Dawn client memory transfer service](https://chromium.googlesource.com/chromium/src/+/156.0.8078.79/gpu/command_buffer/client/dawn_client_memory_transfer_service.cc)
  → `MappedMemoryManager::Alloc` → `CommandBufferProxyImpl::CreateTransferBuffer`.
- [ArrayBufferSharedMemoryMapper](https://chromium.googlesource.com/chromium/src/+/156.0.8078.79/gin/array_buffer.cc)
  maps WebGPU transfer buffers through the V8 sandbox address space.
- [EmulatedVirtualAddressSubspace::AllocateSharedPages](https://chromium.googlesource.com/v8/v8/+/c9b3cfcab30ace06c21f9b48a0f0a34805e81e9d/src/base/emulated-virtual-address-subspace.cc)
  only accepts mappings in the unreserved region and gives up after ten attempts.
  Its logical sandbox can extend beyond the Android kernel's accessible addresses.

A fresh unmodified Chrome baseline passed 18/20 full WebGL1 + WebGL2 + WebGPU
runs. Both failures rejected mapAsync with “A valid external Instance reference
no longer exists”; a subsequent traced run reproduced the original “Failed to
allocate memory for buffer mapping” message. The probe now preserves adapter
information, uncaptured errors and device-loss details when a mapping rejects.

The private compatibility prototype passed 20/20 Chrome and 20/20 Chromium runs
including mapping stress. These are debugging results, **not installed acceptance**.
A subsequent unmodified Chromium stress control also failed, and its syscall
trace reproduces the same V8 partial-sandbox mapping failure. Prototype logging
was initially absent in Bionic because its preload constructors cannot see the
environment yet; the packaged helper therefore reads its opt-out at call time.

## Proposed packaged workaround

`android-webgpu` provides `lib/android-webgpu/libwebgpu-map.so`. It uses the
common AArch64 C ABI, with no dependency on either libc recorded, so the same
library can be loaded by Bionic Chromium and glibc Chrome. `livecd-desktop` depends
on the package and injects it only into GPU-enabled Chromium-family launchers
when `/dev/kgsl-3d0` exists and `/dev/mali0` does not.

The library records the end of a successful large anonymous no-access reservation.
For a shared `shared-memory-region` memfd with an advisory hint beyond 39 bits, it
folds the hint into the accessible tail after that reservation. It never uses a
fixed mapping, overwrites existing memory or skips V8's range checks. Other fds,
private mappings, fixed mappings, Firefox, software rendering and Mali are unchanged.
The library also checks the device gate itself. `LIVECD_WEBGPU_MAP=0` disables it
for a negative control. No Chrome binary is modified; no Chromium rebuild is needed.

Host checks: `python3 tests/browsers/test-webgpu-mapping.py` exercises real memfd
mappings, untouched unrelated/private/fixed mappings, the opt-out, the absence of
libc dependencies, launcher ABI routing and the Mali/device gates.

## Device acceptance still required

- Install CI-built android-webgpu and livecd-desktop via the phone's local apt repo,
  under `~/.parity-install.lock`, with no downgrades.
- Both browsers: at least 50/50 full runs through installed launcher modules.
- `test-web-graphics.py BROWSER --map-stress --out NEW_DIRECTORY`: 32 simultaneous
  1 MiB buffers, 32 patterned upload/copy/readback map/unmap cycles, and a 64 MiB
  buffer. All words are checked. The visible WebGL/WebGPU canvases still undergo
  reference comparisons and screenshot checks.
- Reproduce a failure with `LIVECD_WEBGPU_MAP=0`; open screenshots.
- WebGL1/2 in all three browsers, Firefox WebGPU, Chromium/Chrome hardware video,
  and `livecd validate` must pass.

Evidence: `temp/parity-note10-20261116/webgpu-map/` on the host and
`~/pl-webgpu-map/` on the Note10+. Private displays only. The shared temporary SSH
key is needed by the zerocopy lane too; the last lane removes it.

## Original report, 2026-11-19

Installed launchers, mesa 26.2.6-107 / android-vaapi-glibc 13:

| Run | Chrome | Chromium |
|---|---|---|
| WebGL1 + WebGL2 + WebGPU, 20 repeats | 16/20 | 18/20 |
| WebGPU alone | 5/5 | 20/20 |

The adapter was Turnip, not a software fallback. The original hypothesis was
renderer transfer-buffer exhaustion after WebGL. The current trace supersedes
that hypothesis for Chrome's reproduced allocation error. Vulkan mapping and
KGSL allocation limits do not account for the observed successful syscalls.
