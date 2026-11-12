# Ghostty / PanVK G77 handoff

Updated 2026-11-12. User requested a handoff at this point; further investigation
and driver promotion are not part of this handoff.

## Current outcome

The Mali-G76 large-workgroup compiler pass **can be adapted to our Mali-G77**.
The experimental Android driver built in CI and correctly executed the tested
512-, 960- and 1024-invocation workgroups on x1s. This is a working subset,
not full Vulkan or OpenGL conformance.

With the experimental opt-in, Zink reports OpenGL **4.6** and GLES **3.2**,
without a GL/GLSL version override. Ghostty 1.4.0 creates its OpenGL context,
so the former 4.3 context/version gate is overcome. **GPU Ghostty is still not
usable:** the Cairo GTK path did not produce an accepted terminal frame/input
result, and the GTK GL path failed with `EGL_BAD_ACCESS`.

Keep the installed Ghostty software fallback. The experimental ICD was staged
privately and was not installed or selected for the managed desktop.

## Workspace and source provenance

- Main checkout: `/home/cs/debian-livecd-termux`. It has unrelated changes from
  another thread; preserve them.
- Experiment worktree: `/home/cs/debian-livecd-termux-panvk-workgroups`.
- Pushed branch: `research/panvk-g77-workgroups` in
  <https://github.com/cnshing/debian-livecd-termux>.
- Driver commits: `fb61bff` (initial prototype), `fb7ce70` (consistent subgroup
  limits). `2850516` adds the initial private Ghostty probe. The final handoff
  commit also preserves subsequent Python harness/runner refinements.
- Working desktop integration is separately on `feat/panvk-desktop`, in
  `/home/cs/debian-livecd-termux-panvk-desktop`; do not confuse it with this
  experimental driver branch.

Baseline source reconstruction is unchanged from the prior accepted research:
Zenith `cf70e02b918e1864cbcd746a7fefa57b96c673ce`, Mesa base
`5a07217f034b3e50d8c7c7794f97a2df1742613b`, p0175 reconstructed tree
`4a8e9a8cbb34b9fb91a9ad2040319aceb075b973`.

Imported MIT patches are byte-identical to
[soulexit/panvk-kirin990](https://github.com/soulexit/panvk-kirin990) commit
`c024c056ac2426acead6a8741ccc38081964fddb`, from `patches/mesa-26.3/`:

| Upstream patch | Purpose |
|---|---|
| 0012 | Run logical workgroups as multiple copies per hardware invocation; preserve top-level workgroup barriers between cloned regions. |
| 0044 | Permit subgroup operations and rewrite logical subgroup ID/count. |
| 0061 | Lower module-private variables to locals so each logical invocation keeps its own values across barriers. |

All three applied to our reconstructed source without importing unrelated G76
patches. They live in `tools/panvk-probes/workgroup-patches/`, with the upstream
license. Patch 0004 is our adaptation:

- Enables the pass only for `PAN_ARCH == 9` with `PANVK_G77_LWG=1`.
- Uses half the hardware thread limit: G77 logical workgroups become hardware
  groups of at most 256 invocations, allowing for register pressure.
- Requires each cloned region's hardware group to align to the 16-lane subgroup.
- Exposes experimental 1024-invocation limits and a consistent subgroup count
  only under the opt-in.
- Rejects static compute shaders still exceeding the lowered limit at pipeline
  compilation, instead of sending unsupported oversized workgroups to the GPU.

This independent series excludes the earlier point-size/X11-soname series,
which regressed GTK swapchain creation. Do not combine those experiments.

## CI and artifact identity

[PanVK G77 workgroup experiment run 43192201109](https://github.com/cnshing/debian-livecd-termux/actions/runs/43192201109)
completed successfully at driver source commit `fb7ce70`. Both the baseline and
patched Android ICDs were built; the CPU-checked probes compiled with warnings
as errors, and SPIR-V validation passed. No builds ran on the host or phone.

Artifact: `panvk-workgroups-android-aarch64`.
Patched Mesa content tree: `9f36ff1bbb409bbaa385f98ec757815b31348659`.

| Binary | SHA-256 |
|---|---|
| Baseline Android ICD | `c6eb73b6617a7d94aa780aa9af44c03799882f8de50d109cf94cff791e25b6c3` |
| Patched Android ICD | `98658abb95344b8729645cc5b494b4cd59f0c1cad86226c6a0990aaee569c709` |

The original CI artifact is preserved locally. The staged copy uses the latest
Python runner, which limits original-driver controls to 128/256 invocations;
larger cases run only with the pass enabled. This runner-only refinement does
not change the CI-built binaries or shaders.

## Device results

Device: x1s, Mali-G77 MC11, native Termux UID 10287, stock kernel. The SSH helper
selects the x1s ADB device and forwards port 8023:
`/home/cs/debian-livecd-termux/temp/gpu-x1s/ssh`.

### Compute: pass

`run-01` contains 14 successful test decisions:

- Baseline and patched opt-out: 128/256-invocation execution matches the oracle;
  1024 is skipped before pipeline creation because advertised limits remain 512.
- Patched opt-in: 128, 256, 512, 1024x1x1, 32x30x1 (960) and 8x8x16 (1024)
  execute correctly.
- A 1024-invocation shader with a uniform loop barrier, and a prime-sized
  769-invocation shader, return `VK_ERROR_FEATURE_NOT_PRESENT` (-8) at pipeline
  creation; neither is dispatched.

All **448,512 output words** from executed cases match the CPU oracle. Each
case covers six dispatch groups and checks local/global IDs, logical workgroup
size, shared-memory atomics/barriers, subgroup IDs/count/reduction/ballot,
module-private values and SSA values live across barriers.

An extra diagnostic run prints the lowered NIR for the 1024 case:
`workgroup_size: 256, 1, 1`, retaining the logical 1024-element shared array.
Its additional 98,304 output words also match. This confirms actual lowering,
rather than only changing the reported limit.

### GNOME/GTK: pass in a short private run

`desktop-software-control` runs the experimental GPU driver for GNOME Shell and
GTK4, with software rendering only for the Ghostty control. The pixel checker
passes all four resize/fullscreen captures with maximum error 0 and rejects the
stale-frame negative control. Shell and GTK map the experimental PanVK library
and hold Mali device descriptors. Ghostty software rendering displays text,
accepts a typed command, records the native UID/home and exits normally.

This is a short correctness check. The previously deferred 30-minute soak is
still pending, as requested by the user.

### Ghostty GPU: not accepted

| Run directory | Observation |
|---|---|
| `desktop-01` | Zink reports GL 4.6; Ghostty logs `loaded OpenGL 4.6`. The typed identity command never completes; the test times out. |
| `desktop-02` | Same GL/context success and input timeout. Before/after screenshots show the private GNOME background with no visible terminal content. |
| `desktop-software-control` | Ghostty software rendering/input/exit succeeds, while the surrounding desktop uses the experimental GPU driver. |
| `desktop-dmabuf-disabled` | Shell readiness marker appears; the probe aborts while inspecting `/proc/30324/fd` with `PermissionError`. It does not establish a successful or failed DMA-BUF workaround. |
| `desktop-gsk-gl` | With `GSK_RENDERER=gl`, Ghostty logs `failed to make EGL context current err=error.BadAccess`, then surface initialization fails. Shell readiness times out. |

Do not classify any GPU Ghostty run as a pass. In particular, GL context creation
and a reported GL version are insufficient evidence of usable rendering.

The software-control screenshot's initial diagnostic string says `GPU INPUT
PASS` because that first harness used the same text in both modes. Its JSON
explicitly identifies `software_control: true` and verifies no PanVK/Mali use in
Ghostty. The saved source now uses the neutral text `GHOSTTY INPUT PASS`.

The `/proc/.../fd` denial could be a process-lifecycle race, a process permission
condition, or something else. A crash has **not** been established: the harness
did not preserve Ghostty's exit status before cleanup. Do not infer a kernel,
SELinux, DMA-BUF or driver root cause from that exception alone.

## Presentation investigation and useful sources

Ghostty 1.4's OpenGL renderer creates a surfaceless EGL context and exports
rendered textures as DMA-BUFs, with a CPU readback presentation fallback:

- [OpenGL backend](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/renderer/OpenGL.zig)
- [EGL device](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/renderer/opengl/Device.zig)
- [Render target export/readback](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/renderer/opengl/Target.zig)
- [GTK render surface](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/apprt/gtk/class/render_surface.zig)

A related upstream [blank-window discussion](https://github.com/ghostty-org/ghostty/discussions/14395)
describes failed DMA-BUF import and presentation fallback. It is a lead, not a
diagnosis for this phone; our logs do not show that same import failure.

GTK documents `GDK_DISABLE=dmabuf`, but Ghostty 1.4's
[`setGtkEnv()`](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/apprt/gtk/class/application.zig)
overwrites `GDK_DISABLE` with `vulkan`. Our attempted environment workaround
indeed logs only `setting GDK_DISABLE=vulkan`. Therefore this test did **not**
actually disable Ghostty's DMA-BUF path.

A later search also found an existing experimental
[Ghostty GLES 3.1 / Vulkan port discussion](https://github.com/ghostty-org/ghostty/discussions/13907).
Neither backend was downloaded, built or validated here. It is an alternative
research route if fixing the current Ghostty presentation path is unattractive.

## Evidence locations

Host base:
`/home/cs/debian-livecd-termux/temp/gpu-x1s/workgroups/`

- `ci-build.log`, `ci-artifact/out/`: original CI logs/binaries/probes/provenance.
- `stage/`: exact staged drivers and the refined runner.
- `upstream-provenance.json`: imported patch identity and checksums.
- `compute-run-01.txt`, `lowered-nir-1024.txt`: execution and compiler evidence.
- `evidence/run-01/`: individual case logs and results JSON.
- `evidence/desktop-*/`: results, isolation snapshots, environment, logs and captures.
- `desktop-*.txt`: outer test logs, including the failed runs.
- `managed-before.txt`, `managed-after.txt`, `managed-handoff.txt`: managed state.

Phone base: `~/gpu-x1s/panvk/workgroups/`. It contains the baseline ICD,
`patched/libvulkan_panfrost.so`, `workgroups/` probes, `panvk-desktop.py`, and
all named result directories. The most recent source of the runner and private
harness is the experiment worktree; copy it again before resuming.

## Reproduction

Use fresh output directories. Commands below run on x1s through the SSH helper;
keep builds in GitHub CI. Do not enable the opt-in in the managed desktop.

```
cd ~/gpu-x1s/panvk/workgroups
python workgroups/run.py --baseline libvulkan_panfrost.so \
  --patched patched/libvulkan_panfrost.so --out run-next

PANVK_G77_LWG=1 MESA_SHADER_CACHE_DISABLE=true python panvk-desktop.py \
  --mode shm --cycles 2 --driver "$PWD/patched/libvulkan_panfrost.so" \
  --ghostty-probe --ghostty-software --allow-other-displays \
  --out "$PWD/desktop-control-next"
```

For the unaccepted GPU Ghostty case, omit `--ghostty-software`. The default
Ghostty GTK renderer is Cairo; `--ghostty-gsk gl` selects the failed GL control.
The harness creates a private display/session and cleans up only its own tagged
processes. Never target the managed `:0` session with its input automation.

Check retrieved presentation captures on the host:

```
python3 tests/native/check-panvk-desktop.py /path/to/desktop-control-next
```

## Resume priorities and boundaries

1. Preserve Ghostty's actual exit status and inspect process liveness during
   readiness/input waits. Keep optional diagnostic `/proc` failures distinct
   from rendering/input acceptance. Do not relax GPU evidence checks.
2. Determine whether the Cairo GPU case exits/crashes, stalls in GL work, or
   fails to present. Instrument first-frame progress before attributing it to
   DMA-BUF or synchronization.
3. If testing CPU **presentation** with GPU rendering, use a real Ghostty code
   path/configuration change; the overwritten `GDK_DISABLE` environment variable
   does not implement that test. Build any changes in CI.
4. Keep the workgroup implementation experimental until valid nested barriers,
   unaligned/prime shapes and other required shader patterns are implemented,
   and relevant CTS/capability checks pass. The opt-in reports capabilities that
   its deliberately restricted implementation does not generally satisfy.
5. Revisit an app-specific solution or the existing GLES port if preferable to
   general OpenGL 4.3 qualification. A successful Ghostty app test alone would
   still not qualify full GL 4.3/4.6 support.

No root, kernel, permission or SELinux changes. No new Firefox workloads; no
ANGLE desktop path. Do not stop other sessions' processes. No long soak is
required for this handoff.

## State left behind

All five private display runs cleaned up; every recorded isolation comparison
passed. Final X socket listing contains only `X0`. Managed status matches the
before snapshot: owner 7760, Shell 8163, session tag
`4cb70234ceda4c88a750822fc22f7be4`, renderer `zink`, integrations ready (the
pre-existing Bluetooth headset condition is unrelated). The installed renderer
configuration and Ghostty software fallback were not changed.
