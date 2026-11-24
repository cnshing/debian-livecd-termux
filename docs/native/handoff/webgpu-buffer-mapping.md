# WebGPU buffer mapping on the Note10+

## Investigation, 2026-11-22

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

## Packaged workaround

`android-webgpu` provides `lib/android-webgpu/libwebgpu-map.so`. It uses the
common AArch64 C ABI, with no dependency on either libc recorded, so the same
library can be loaded by Bionic Chromium and glibc Chrome. `livecd-desktop` depends
on the package and injects it only into GPU-enabled Chromium-family launchers
when `/dev/kgsl-3d0` exists and `/dev/mali0` does not.

The library records the end of a successful large anonymous no-access reservation.
For a shared `shared-memory-region` memfd with an advisory hint beyond 39 bits, it
folds the hint into the accessible tail after that reservation. If the tail is
fragmented and the kernel still returns an address below the reservation, the
helper reads its own `/proc/self/maps` without allocating memory and retries in
a free gap, using another advisory mapping. Finding that gap is necessary for
Chromium's more fragmented address space; folding alone remained intermittent. It never uses a
fixed mapping, overwrites existing memory or skips V8's range checks. Other fds,
private mappings, fixed mappings, Firefox, software rendering and Mali are unchanged.
The library also checks the device gate itself and probes whether the process can
map above the 39-bit boundary, leaving newer kernels with wider address spaces alone. `LIVECD_WEBGPU_MAP=0` disables it
for a negative control. No Chrome binary is modified; no Chromium rebuild is needed.

Host checks: `python3 tests/browsers/test-webgpu-mapping.py` exercises real memfd
mappings, a tail with only one free 16 MiB hole, untouched unrelated/private/fixed
mappings, late environment availability, the opt-out, the absence of libc
dependencies, launcher ABI routing and the Mali/device gates.

## Installed qualification, 2026-11-23

CI-built `android-webgpu 0.1.0-1` (run 45108106965) and
`livecd-desktop 0.2.0-48` (run 45107508926) were installed through the phone's
local APT repository, without downgrades. The full installed-launcher-module
harness passed **50/50 Chromium 156 and 50/50 Chrome 157** sequential fresh-profile
runs. Each run checks WebGL1/2, WebGPU render/compute and compositor pixels, plus
32 simultaneous 1 MiB read buffers, 32 patterned upload/copy/readback cycles and
a 64 MiB buffer. Every word is checked. Both use hardware Turnip; no diagnostic
preload or special WebGPU flag is injected by the test.

The installed helper SHA256 is
`2c3c85b00f90a19f530563d122e5537e14f99b9e3a3917fe62f1ee4db849d43c`;
installed acceleration.py is
`ad01eca167599e898b810348fe9c97f727d9d4ae06013ec50bbb035ac2a0e5da`.
The first and last screenshots from both browsers were opened: all three
expected gradients are present. Firefox also passes WebGL1/2 and WebGPU with
mapping stress, without loading the helper.

Desktop restart exposed a pre-existing packaging omission: desktop.py imports
audio.py, but the package lacked its source link. The exact committed module was
restored to recover the desktop (validate 30/30). Revision 49 adds the missing
link; its CI artifact (45176219600) contains audio.py and the identical tested
acceleration.py. A host packaging test now checks every packaged Python module's
local imports.

Revision 49 was then installed via local APT with no other package changes.
Desktop stop/start and validation pass **30/30**, including AAudio. The installed
helper/launcher hashes remain identical; a further **3/3 stress runs per browser**
pass after that upgrade.

With `LIVECD_WEBGPU_MAP=0`, Chromium fails 7/20 full runs and Chrome fails 1/6
(stopped after the first failure). Every failing control records the original
“Failed to allocate memory for buffer mapping” in Dawn's uncaptured errors; the
mapAsync rejection itself says the buffer is invalid. Both opt-out screenshots
were opened: WebGL remains visible and the WebGPU canvas is blank. The runner's
first control loop checked only the rejection text, so it unnecessarily continued
to 20 Chromium runs; the captured errors establish all seven original failures.

Hardware-video regression through installed Chromium/Chrome commands passes
H.264, HEVC and VP9, two fullscreen/windowed cycles per clip, with hardware GPU
and VA-API decode required. Pinned fixture frames pass reference PSNR/SSIM and
color checks at both browser and compositor layers; contact sheets were opened.
An initial invocation incorrectly combined the legacy simple-color-bar checker
with patterned v2 fixtures; the corrected runs use the manifest's frame checks.
Final `livecd validate` is **30/30**. WebGPU stays enabled by default.

Host regression results: mapping/launcher checks 10/10; package integration 16/16
(including missing-local-import coverage); Mali acceleration 24/24; Adreno setup
9/9. CI runs 45108106965 and 45176219600 pass. No release was modified.

Evidence: `temp/parity-note10-20261116/webgpu-map/` on the host and
`~/pl-webgpu-map/` on the Note10+. Private displays only. At the time the shared
temporary SSH key remained for the zerocopy lane; that lane finished last and
removed the key and stopped sshd.

The delivered change is commits 34772e3 through bb41715 on main (the range
`34772e3^..bb41715`). Its pre-rebase branch `fix/webgpu-map` was deleted on
2026-11-24 after every commit was confirmed equivalent on main.

## Review follow-up, 2026-11-24: Mali and maintenance

A host-only review confirmed the claims, CI hashes and opt-out evidence and
found no correctness bug. It found one scope gap: the cause is the 39-bit
kernel address space, not the GPU, but the helper was KGSL-only, while Chromium
and Chrome WebGPU are on by default on the Mali x1s (Galaxy S20). Branch
`fix/review-followups` (android-webgpu 0.1.0-2, livecd-desktop 50) changes:

- The library activates on its 39-bit probe alone: a temporary advisory
  mapping at 2^39 must land below 2^39. Kernels with more address bits keep
  their native mapping behaviour, which a new host test checks with a real
  (not test-forced) build on the 47-bit host; a forced build fails it.
- The launcher preloads it for Chromium, Chrome and ungoogled-chromium with a
  GPU on any vendor. `0`, `false`, `no` and `off` opt out.
- Retries pick a different free-gap slot per attempt, a failed `munmap` of the
  helper's own mapping keeps that mapping instead of mapping a second copy,
  and the `/proc/self/maps` scan stops once it has an answer.

x1s result (2026-11-24): the kernel is 39-bit, so the helper activates. WebGL
1 and 2 pass with it preloaded, but Chromium offers no WebGPU adapter on PanVK
there, so the mapping failure cannot occur yet. Details are in
`docs/native/X1S-BROWSER-VERIFICATION.md`. If a later PanVK or Chromium
version offers an adapter, run the stress and its opt-out control on the x1s.

Maintenance: the helper recognises Chromium's memfd by the exact name
`shared-memory-region` and V8's reservation by its size (at least 12 GiB minus
a page, with size + page − 4 GiB a power of two). A browser update that changes
either makes the helper inert without any message, and the original
intermittent failure returns. Re-run the opt-out control and the installed
stress after each Chromium or Chrome update. ungoogled-chromium receives the
helper but has not been tested.

## Original report, 2026-11-19

Installed launchers, mesa 26.2.6-107 / android-vaapi-glibc 13:

| Run | Chrome | Chromium |
|---|---|---|
| WebGL1 + WebGL2 + WebGPU, 20 repeats | 16/20 | 18/20 |
| WebGPU alone | 5/5 | 20/20 |

The adapter was Turnip, not a software fallback. The original hypothesis was
renderer transfer-buffer exhaustion after WebGL. The current trace supersedes
that hypothesis for both browsers' reproduced allocation errors. Vulkan mapping and
KGSL allocation limits do not account for the observed successful syscalls.
