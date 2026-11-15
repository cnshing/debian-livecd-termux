# `/dev/dma_heap` on top of `/dev/ion`

Progress on the handoff `docs/native/handoff/dmabuf-s20.md` (on `feat/s20-video-parity`,
PR #12). State on 2026-11-15.

## What exists

- `packages/android-vaapi/dma-heap.c` builds `libandroid-dma-heap.so` (android-vaapi 27.0.0~devel20261029-6),
  shipped beside `libandroid-vaapi-render-node.so` in the private directory. It is **not loaded
  by the launcher yet**.
- It presents `/dev/dma_heap/system` and `/dev/dma_heap/system-uncached`, which are character
  devices to `stat`/`access`. `DMA_HEAP_IOCTL_ALLOC` turns into ION's 4.12+ `ION_IOC_ALLOC`.
- Heap choice follows Android's
  [libdmabufheap](https://android.googlesource.com/platform/system/memory/libdmabufheap/)
  (`BufferAllocator::QueryIonHeaps`):
  - `system` uses `ion_system_heap` with `ION_FLAG_CACHED`;
  - `system-uncached` uses the same heap with no flags;
  - when no heap has that name, the first heap of type `ION_HEAP_TYPE_SYSTEM` is used.
- It does nothing when a real `/dev/dma_heap` exists, when `/dev/ion` is missing, or when
  `LIVECD_DMA_HEAP_ION=0` is set. With no ION system heap, `open` fails with `ENOENT`.
- Host test: `tests/dma-heap/test-dma-heap.sh`, 9 cases against a fake ION device
  (`fake-ion.c`).

## S20 results (x1s, Linux 4.19.87, no root), 2026-11-15

ION heaps from `tests/dma-heap/ion-probe.c`:

| id | type | name |
| --- | --- | --- |
| 0 | 0 system | ion_system_heap |
| 1 | 2 carveout | camera_heap |
| 2 | 2 carveout | npu_fw |
| 3 | 4 dma | vstream_heap |
| 4 | 4 dma | crypto_heap |
| 5 | 2 carveout | secure_camera_heap |
| 6–10 | 5 custom | vfw_heap, vnfw_heap, vframe_heap, vscaler_heap, gpu_buffer |

- Raw ION, without the preload: cached and uncached allocations of 4 KiB, 1 MiB and 64 MiB all
  pass, each with `mmap` and a `DMA_BUF_IOCTL_SYNC` start/end round trip.
- Through the preload, `tests/dma-heap/heap-client.c` uses only the heap API:
  - `system` and `system-uncached` at all three sizes: ok;
  - each run covers open, alloc, the `O_CLOEXEC` flag on the fd, rejection of bad flags,
    `ENOTTY` for other ioctls, `mmap`, the pattern read back in a second process over
    `SCM_RIGHTS`, and alloc on a `dup` of the heap fd.
- Control: without the preload, and with `LIVECD_DMA_HEAP_ION=0`, the client fails at `stat`
  with `ENOENT`, so the test does exercise the preload.
- Bionic calls libc wrappers before library constructors run, so every forwarded call resolves
  its next definition on first use. The first build resolved them in the constructor and
  segfaulted on start-up, even with emulation disabled.

## PanVK's own ION fallback

Zenith's `patches/jm-v7/005-kbase-ion-fallback-for-placed-map-dma-buf.patch` already does
heap-then-ION in `kbase_kmod.c`:

- it uses the first system-type ION heap, with `ION_FLAG_CACHED`;
- its log line is `kbase: using ION system heap, mask 0x%x`;
- the built driver, both the Bionic and the glibc copy, contains these strings.

So PanVK does not need the preload for shareable BOs. With the preload loaded, PanVK opens
`/dev/dma_heap/system` and ends up with the same ION allocation, so the two do not conflict.

**One behaviour change to test before the launcher loads the preload:** the GPU is not
IO-coherent, so PanVK asks for `/dev/dma_heap/system-uncached` for HOST_COHERENT memory.

- Today that open fails, and PanVK cleans imports before each submit.
- With the preload, PanVK would get uncached ION memory instead.
- Test CPU-write/GPU-read and the reverse, and rerun the desktop and Ghostty checks, before
  enabling it.

## Left

- Handoff step 3, GPU half: import a heap buffer into PanVK with
  `VK_EXT_external_memory_dma_buf`, have the GPU write it, and check the result on the CPU.
- Steps 4–5: PanVK and the bridge through the preload, removing the bridge's own ION path, and
  launcher wiring in `acceleration.py`/`graphics.py`.
- A glibc build through Bionilux. The host test already builds and passes it on glibc.
- `opendir("/dev/dma_heap")` listing is not emulated yet.
