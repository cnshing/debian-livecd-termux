# Handoff: intermittent WebGPU "Failed to allocate memory for buffer mapping" (Adreno, Chromium and Chrome)

## Symptom (Note10+, 2026-11-19)
`tests/browsers/test-web-graphics.py BROWSER` (WebGL 1, WebGL 2, then WebGPU in one page), installed launchers,
mesa 26.2.6-107 / android-vaapi-glibc 13:

| Run | Chrome | Chromium |
|---|---|---|
| full page, 20 repeats | 16/20 | 18/20 |
| `--cases webgpu` only | 5/5 | 20/20 |

Every failure is the same renderer-side message, after `webgpu step: map render` (or `compute read`):

    GPUDevice: "Failed to allocate memory for buffer mapping
        at APICreateErrorBuffer (third_party/dawn/src/dawn/native/Device.cpp)"

followed by `mapAsync ... Invalid Buffer`. The adapter is Turnip (qualcomm/adreno-6xx, not a fallback) in every run.

## What it is not
- Not GPU-side `vkMapMemory` or a KGSL allocation: the error buffer is made while the buffer is *created*, from
  Dawn's wire client, before the GPU process maps anything. No Vulkan or KGSL error appears in the logs.
- Not the glibc Turnip: the Bionic Turnip (Chromium) shows it too, with the same driver change (mesa 0027).
- Not WebGPU alone: it needs the WebGL cases first in the same renderer.

## Most likely cause
Dawn's wire client asks the embedder's memory transfer service for a shared-memory handle for each mappable
buffer (Chromium: `gpu/command_buffer/client/dawn_client_memory_transfer_service.cc`, allocating from the
renderer's `MappedMemoryManager` / transfer buffers). When that fails, Dawn returns an error buffer with this
message. The WebGL contexts run earlier in the same renderer hold transfer-buffer/shared memory, so the
allocation fails sometimes. Candidates to check, in order:
1. Shared memory creation in the renderer: these builds run with `--disable-dev-shm-usage` (and Chrome with
   `--no-sandbox`); check whether `base::UnsafeSharedMemoryRegion::Create` fails (memfd vs file in
   `$PREFIX/tmp`, fd limits) by adding `--enable-logging=stderr --vmodule=*shared_memory*=2,*dawn_client*=2,*mapped_memory*=2`.
2. The mapped-memory limit of the WebGPU interface's `MappedMemoryManager` once WebGL contexts are alive
   (try destroying the WebGL contexts first, `loseContext()`, in a page variant; if that fixes it, it is the budget).
3. Timing: the test page maps right after rendering; retry with a short delay to rule out a race with the
   WebGL contexts' teardown.

## Reproduce
On the phone (no live display is touched): repeat
`python tests/browsers/test-web-graphics.py chromium --out NEW_DIR` 20 times and grep the run's `*.log` for
the message; Chrome: same with `chrome`. A fix must make 20/20 full runs pass in both browsers.
