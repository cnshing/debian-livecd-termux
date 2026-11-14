# Handoff: Vulkan 1.4 and OpenGL 4.3 on the packaged PanVK driver

State on 2026-11-13, Galaxy S20 (`x1s`, Mali-G77 MC11, architecture 9, kbase job manager).
For whoever raises the versions the Mali stack reports. Paths under `temp/` are local files
that Git ignores.

## Where the versions stand

Measured on the phone with the packaged driver (`mesa-vulkan-icd-panvk-kbase` 26.3.1) and
Mesa 26.2.6-103:

| | Reported now | Wanted | What decides it |
| --- | --- | --- | --- |
| Vulkan | 1.3.363 | 1.4 | one function in the driver; the features are already there |
| OpenGL through Zink | 4.2 core, GLSL 4.20 | 4.3 | compute shaders: 1024 invocations per workgroup, the GPU gives 512 |
| OpenGL ES through Zink | 3.1 | 3.2 comes with it | same |

The two are separate pieces of work. **Only OpenGL 4.3 changes what a user sees**: Ghostty
needs it and runs on llvmpipe without it. Nothing in the stack asks for Vulkan 1.4 today:
Zink, ANGLE's Vulkan back end and mpv's libplacebo are all satisfied by 1.3.

## OpenGL 4.3

### The one gate

Mesa turns on `ARB_compute_shader`, and with it OpenGL 4.3, only when the driver allows 1024
invocations in a compute workgroup (`src/mesa/state_tracker/st_extensions.c`):

```c
extensions->ARB_compute_shader =
   screen->compute_caps.max_threads_per_block >= 1024 && ...
```

Zink takes that number from Vulkan's `maxComputeWorkGroupInvocations`, which is 512 on this
GPU: the hardware's own limit. Every other extension 4.3 needs is already reported; in the
surfaceless `eglinfo` dump `GL_ARB_compute_shader` is the one that is missing. JimVulkan's
driver reports the same 512 and the same 4.2, so changing drivers does not help.

### What already exists

A compiler pass that runs a large logical workgroup as several copies inside a smaller
hardware workgroup, taken from the Mali-G76 work in
[soulexit/panvk-kirin990](https://github.com/soulexit/panvk-kirin990) and adapted to the G77:

| Piece | Where |
| --- | --- |
| The three imported patches and our G77 adaptation | `tools/panvk-probes/workgroup-patches/0001` to `0004` |
| CI build of a baseline and a patched driver, with probes | `.github/workflows/panvk-workgroups.yml` |
| Compute probes checked against a CPU oracle | `tools/panvk-probes/workgroups/` (`run.py`, `check.c`, `check.comp`) |
| Opt-in Ghostty launcher for the staged driver | `tools/panvk-probes/workgroups/ghostty-gpu.py` |
| Results | [GHOSTTY-PANVK-HANDOFF.md](GHOSTTY-PANVK-HANDOFF.md) |

With `PANVK_G77_LWG=1` the patched driver reports 1024, Zink reports **OpenGL 4.6 and
OpenGL ES 3.2** with no version override, and Ghostty renders on the GPU: twelve terminal
captures and twelve GTK captures passed, with the stale-frame control rejected. The tested
compute shapes (512, 960 and 1024 invocations, in one, two and three dimensions) match the
oracle in all 448,512 output words.

### What is missing before it can be the default

The pass is a working subset behind an environment variable. To ship it:

1. **Cover what it refuses.** A shader with a barrier inside a loop, or a workgroup size
   that does not divide into 16-lane subgroups (769 was the test), fails pipeline creation
   with `VK_ERROR_FEATURE_NOT_PRESENT`. That is honest, but a driver that advertises 1024
   must run them. Either implement them (nested barriers need the region split to follow
   control flow) or measure how often real GL programs hit them and decide with the user.
2. **Variable workgroup sizes** (`ARB_compute_variable_group_size`) are not handled.
3. **Run a conformance subset**, not only our probes: `dEQP-VK.compute.*` and
   `dEQP-GLES31.functional.compute.*` are the relevant groups. None has been run.
4. **Make it part of the shader cache key.** The experiment disables the shader cache
   because the opt-in is not in the cache identity. As a default it must be, or the variable
   must go away.
5. **Register pressure.** The adaptation halves the hardware thread limit (256 per hardware
   workgroup) to leave room. Nobody has measured what that costs, or whether a shader can
   still exceed it.
6. **Then drop the opt-in** for architecture 9, and soak the desktop. The experiment's
   GNOME and GTK check with the patched driver was two cycles; a default needs the 20-cycle
   run and the 30-minute soak.

When the installed driver reports 4.3, nothing else needs changing for Ghostty:
`src/native/terminal.py` asks `glxinfo` for the core version and keeps the GPU when it is at
least 4.3. Its test is `tests/native/test-terminal-environment.py`.

Ghostty will then present through its CPU readback, because the driver has no SYNC_FD
semaphores. That is the subject of [PANVK-SYNC-FD-HANDOFF.md](PANVK-SYNC-FD-HANDOFF.md).

## Vulkan 1.4

### What the phone shows

The packaged driver already lists every extension Vulkan 1.4 folded into the core, with its
feature turned on, and the limits 1.4 raised are met:

- **Extensions present:** `dynamic_rendering_local_read`, `global_priority`,
  `index_type_uint8`, `line_rasterization`, `load_store_op_none`, `maintenance5`,
  `maintenance6`, `map_memory2`, `push_descriptor`, `shader_expect_assume`,
  `shader_float_controls2`, `shader_subgroup_rotate`, `vertex_attribute_divisor`,
  `host_image_copy`, `pipeline_robustness`.
- **Absent:** `VK_EXT_pipeline_protected_access`, which only matters with protected memory.
  JimVulkan's driver lacks it too and reports 1.4.
- **Limits:** 8 colour attachments, 7 bound descriptor sets, 32 push descriptors, 512
  compute invocations, `largePoints`, `timestampComputeAndGraphics`.

The version is held at 1.3 by the driver's own choice. Its patch
`jm-v9/003-report-vulkan-1.3-on-v9` says it "returns the upstream 1.3 for v9". JimVulkan's
`get_api_version()` (`src/panfrost/vulkan/panvk_vX_physical_device.c`) returns 1.4 for
architecture 9 and later, with the comment that architecture 9 has every feature 1.4
requires. On this phone it reports `1.4.363`.

Diffing the two drivers' `vulkaninfo` here: 558 properties in common, 34 differ, and none
of the differing features is one that 1.4 promoted. The packaged driver reports more than
JimVulkan's in several places (`drawIndirectCount`, `depthBounds`, transform feedback
streams) and less in a few (`alphaToOne`, `shaderDeviceClock`, dual-source attachments).

### The work

1. **Change `get_api_version()`** in the packaged driver's source to return 1.4 for
   architecture 9 on kbase, as a patch in `tools/panvk-probes/driver-patches/`.
2. **Check it against the specification, not against another driver.** The list above is
   what `vulkaninfo` prints; 1.4 also has required behaviours that a property dump cannot
   show. Go through the specification's "Vulkan 1.4" required features and limits, and run
   `dEQP-VK.api.info.*` and `dEQP-VK.info.*`. One known weak spot: the release driver draws
   an 11-pixel point as 5 by 5 ([PANVK-X1S-RESEARCH.md](PANVK-X1S-RESEARCH.md)), and
   `largePoints` is reported as supported. The fix exists as
   `driver-patches/0002-v9-per-vertex-point-size.patch`.
3. **Run what depends on the version string**: Chromium and Chrome start ANGLE on this
   driver and print it in their GL renderer (`Vulkan 1.3.363` today); Firefox's probe patch
   (`packages/android-firefox-video/stage.py`) matches `Mali` and `PANVK` in Zink's
   renderer string, not the version, so it is unaffected. Rerun
   `tests/packaging/test-firefox-video.py` and the browser playback tests anyway.

Do not raise the number without step 2. A wrong 1.3 costs nothing here; a wrong 1.4 makes
applications use paths that were never exercised.

## Shared prerequisite: a package that can carry a patch

Both changes are patches to the driver, and the package installs upstream's release
binaries. `.github/workflows/panvk-driver.yml` reconstructs the release's source (tree
`4a8e9a8c…`) and builds Bionic and glibc drivers in CI; `panvk-workgroups.yml` does the same
with the workgroup series. What is missing:

- **A recipe that installs a built driver**: either `mesa-vulkan-icd-panvk-kbase` builds the
  reconstructed tree, or it pins a CI artifact by hash. Both ABIs, because Chrome uses the
  glibc one. The rebuilt, unmodified driver gave the same probe pictures as the release, but
  byte equality with the release cannot be shown, so the first source-built package needs
  the desktop validation again (30 of 30) before anything is added to it.
- **Separate variants.** The `driver-patches/` pair (X11 sonames, point size) fails GTK
  swapchain creation and was never bisected. Keep each new patch in its own variant on the
  unmodified baseline until that is understood, as the workgroup series does.
- A source-built driver can link Termux's X11 library names directly, which would retire
  the package's `bionic/x11` link directory.

The SYNC_FD port needs the same step. Do it once, first.

## Suggested order

1. Source-built package, unmodified, validated against the release.
2. OpenGL 4.3: close the workgroup pass's gaps, drop the opt-in.
3. SYNC_FD ([PANVK-SYNC-FD-HANDOFF.md](PANVK-SYNC-FD-HANDOFF.md)), for Ghostty's
   presentation.
4. Vulkan 1.4, when something wants it.

## How to check, on the phone

```sh
# Versions and the gate, without a display.
VK_DRIVER_FILES=<icd.json> LD_LIBRARY_PATH=$PREFIX/lib/panvk-kbase/bionic/x11 vulkaninfo \
  | grep -E 'apiVersion|maxComputeWorkGroupInvocations'
VK_DRIVER_FILES=<icd.json> LD_LIBRARY_PATH=$PREFIX/lib/panvk-kbase/bionic/x11 \
  GALLIUM_DRIVER=zink MESA_LOADER_DRIVER_OVERRIDE=zink EGL_PLATFORM=surfaceless eglinfo \
  | grep -E 'profile version|GL_ARB_compute_shader'

# Compute correctness for the workgroup pass.
python workgroups/run.py --baseline <base.so> --patched <patched.so> --out <new dir>

# Desktop and Ghostty on a private display; check the retrieved results on the host.
python panvk-desktop.py --mode shm --cycles 20 --driver <patched.so> --ghostty-probe --out <new dir>
python3 tests/native/check-panvk-desktop.py <dir> && python3 tests/native/check-ghostty-panvk.py <dir>
```

The dumps behind this page are in `temp/gpu-x1s/jim-eval/out2/` (packaged driver:
`zenith-vulkaninfo.txt`, `zenith-eglinfo.txt`) and `temp/gpu-x1s/jim-eval/out/`
(JimVulkan's). Builds go through GitHub CI. Phone rules are in
[VIDEO-ENCODING-HANDOFF.md](VIDEO-ENCODING-HANDOFF.md).
