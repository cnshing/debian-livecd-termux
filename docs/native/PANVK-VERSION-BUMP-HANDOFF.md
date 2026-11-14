# Handoff: Vulkan 1.4 and OpenGL 4.3 on the packaged PanVK driver

State on 2026-11-14, Galaxy S20 (`x1s`, Mali-G77 MC11, architecture 9, kbase job manager).
For whoever raises the versions the Mali stack reports. Paths under `temp/` are local files
that Git ignores.

## Progress on the source-package prerequisite

A side-by-side `mesa-vulkan-icd-panvk-kbase-source` recipe now packages the
unmodified reconstructed driver for both ABIs, with SHA-256 pins to durable
prerelease assets and installed source provenance. Its glibc binary has the CI
RUNPATH removed. [PANVK-SOURCE-PACKAGE.md](PANVK-SOURCE-PACKAGE.md) records the
build, asset identities, isolated patch variants and promotion procedure.
The normal package and launcher selection still use the upstream release.
Installed desktop validation (30/30) remains the gate for repinning that package.

## Workgroup follow-up

The opt-in series now includes partial-subgroup masking (`0005`) and cache-mode
identity (`0006`). The expanded phone probes pass 257-, 511-, 513-, 769-, 1023-
and 969-invocation shapes, as well as the previous aligned cases. Across runs
with caching disabled, enabled, and a repeated shared cache, all **2,509,632
output words** match the CPU oracle. Opt-in and opt-out pipeline cache UUIDs
are distinct. Nested barriers still return `VK_ERROR_FEATURE_NOT_PRESENT` and
were never dispatched. This closes two gaps in the experimental subset; the
advertised default versions remain unchanged.

[PanVK workgroup build 43543966212](https://github.com/cnshing/debian-livecd-termux/actions/runs/43543966212)
built the tested driver. The new evidence is in the original checkout's
`temp/panvk-version-bump/evidence/compute-{uncached,cache-cold,cache-warm}/`.
There are 19 test decisions per run, including the refusal and limit controls.

The same new driver passed a private four-cycle desktop/Ghostty run with caching
enabled: eight terminal captures and eight GTK captures, both independent
checkers passing (GTK maximum channel error 0), stale-frame rejection and
Ghostty exit 0. Zink reports GL 4.6 and GLES 3.2 with no version override.
Presentation still uses the existing CPU-readback fallback. The phone was left
with only `X0`, owner 23548 / Shell 23741 and the original managed session tag.
Evidence: `temp/panvk-version-bump/evidence/desktop-workgroups-4/`.

| Experimental artifact | Identity |
| --- | --- |
| Patched Mesa content tree | `54c56ccdd9ea9ca1039c4a85ad1ec22607dc59dd` |
| Baseline Android SHA-256 | `db0bf89a47a9fd18b28c343493ad10812fdafc8381fdd16fb8d05da915b56ab3` |
| Patched Android SHA-256 | `1aae164b6acab253f00dd2f0c79a0d83be9724cc98cb8e3f9c7554ad81c8c69b` |
| Opt-out pipeline cache UUID | `ce9c200ba86279ab111001549054b446` |
| Opt-in pipeline cache UUID | `ee59d8d25c43904ff9122282699695c6` |

Reproduce compute checks with `workgroups/run.py`, first without `--shader-cache`,
then twice with it using fresh sibling output directories. That flag selects a
private cache shared by sibling runs; 35 files were observed in the test cache.
The default runner still disables the cache. For the presentation check, use
the new driver with `PANVK_G77_LWG=1 MESA_SHADER_CACHE_DISABLE=false`, the existing
staged `mesa-102/lib`, `--ghostty-probe` and `--cycles 4`.

## Qualification follow-up: variable sizes, nested barriers and CTS

The actual Zink variable-size path now has a passing device probe:
`tools/panvk-probes/workgroups/variable-size.py`. One OpenGL program uses
`ARB_compute_variable_group_size`, shared memory and a barrier, then dispatches
512, 769, 1024, 17x19x3 and 8x8x16 local shapes across six workgroups each.
All **206,304 output words** match the CPU oracle using the `0001`–`0006`
driver above. The probe checks the mapped ICD and Mali/Zink renderer without a
version override. Host log: `temp/panvk-qualification/variable-gl-02.log`;
phone report: `~/gpu-x1s/qualification/variable-gl-02/results.json`.
Zink specializes the local dimensions before PanVK's lowering pass; this closes
the previously untested GL variable-size path for these cases, rather than
establishing full conformance. The shader must use `gl_LocalGroupSizeARB`:
the extension prohibits `gl_WorkGroupSize` in a variable-size shader.

The tested nested-barrier lowering is now on main in
`workgroup-patches/0007-experimental-nested-barrier-continuations.patch`. It uses NIR shader
continuations to spill values across barriers and reconstruct loops/branches,
with a per-logical-invocation program counter and separate scratch slices.
It additionally requires `PANVK_G77_NESTED=1`. New probes cover dynamic loops,
uniform branches, break/continue, private values live across barriers and a
769-invocation shape. The first pipeline-creation-only control crashed in the
compiler **before dispatch**. A region/global-variable ownership fix and symbols
are in revision `71e7a6f`, successfully built in
[run 43560105312](https://github.com/cnshing/debian-livecd-termux/actions/runs/43560105312).
The Android binary SHA-256 is
`9a0d3fb9e89a4f4dbee17242a8f133f6156ddd0d05927e6340e8916c1e22805b`.
That older binary is retained only as diagnostic history; use the fixed build
below for positive tests.

After wireless access returned, `71e7a6f` passed compile-only creation and
statistics capture. Its first nested dispatch completed but failed the CPU
oracle: **24,633 of 98,304 words were wrong**. Testing stopped there. The NIR
dump exposed overlapping scratch slices: `nir_lower_shader_calls` retains
per-call stack sizes larger than the final shader's `scratch_size`. Research
revision `70baee8` takes the maximum over every continuation marker before
assigning per-copy slices. It built successfully in
[run 43563350446](https://github.com/cnshing/debian-livecd-termux/actions/runs/43563350446).
All four nested compile controls and CPU-checked dispatches now pass. Across
uncached, cold-cache and warm-cache runs, **66 test decisions** passed and all
**3,615,840 output words** matched. This includes the original straight-line
cases, dynamic loops, uniform branches, break/continue and partial-subgroup
769-invocation execution. The Android SHA-256 is
`2b57c92c4b0f882580a8f35d879f982e4548706ebca0c1519221f915c1b2f47f`.
Evidence: `temp/panvk-qualification/evidence/nested-slices/`, with
`uncached-01/`, `cache-cold-01/`, `cache-warm-01/` and `compile-controls/`.
The nested scheduler remains opt-in while broader CTS and desktop qualification
are outstanding.

CTS executables are built in `.github/workflows/panvk-cts.yml`, pinned to
VK-GL-CTS `vulkan-cts-1.4.7.1` (`0d18b347943e5e843529a05c95220e27fe30c538`).
The Android API 33 standalone build matches this phone. GLES opens Termux's
absolute, versioned EGL/GLES libraries; overriding `libEGL.so` globally breaks
Android's `libgui` dependency before CTS starts. `PLATFORM.patch` records the
platform-only changes, and `BUILD.txt` records the source/build identity.
[Run 43559427755](https://github.com/cnshing/debian-livecd-termux/actions/runs/43559427755)
successfully produced both corrected executables. Their SHA-256 identities are:

| Executable | SHA-256 |
| --- | --- |
| `deqp-vk` | `bbfcfef3c5daac858efc9f310f833df96051ea84fb5be1de8f76addacca36d2b` |
| `deqp-gles31` | `019cb7fc277ac29f159309fa20f1dfa4f3c10b46985ad2052911123dafee7b89` |

Both executables now run on the phone. These targeted command-line runs are
qualification evidence, not a formal Khronos conformance submission.

| Device subset | Packaged release | Accepted `0001`–`0006`, opt-in |
| --- | --- | --- |
| GLES `info.*` | 6/6 pass | not repeated |
| GLES `functional.compute.basic.*` | 41/41 pass | 41/41 pass |
| GLES `functional.compute.shared_var.*` and `indirect_dispatch.*` | 154/154 pass | 154/154 pass |

All **195 GLES compute cases** in those groups passed on each driver, with no
skips or warnings. The host checked every QPA case/status and each process-map
sample contains the requested driver. The packaged release SHA-256 is
`62c2b3f98ca987d5ab50b6f01e2d2c1c5b3ee995fe93666aa5da9415f65c3348`;
the opt-in driver is the previously accepted `1aae164b…` binary, not the nested
prototype. Retrieved evidence is in the original checkout's
`temp/panvk-qualification/evidence/gles-{basic,shared-indirect}-{release,lwg}-01/`
and `gles-info-fixed-01/`.

The packaged release's Vulkan `api.info.*` run stopped after two passes and one
failure: `dEQP-VK.api.info.android.no_unknown_extensions` reports
`Unknown extension: VK_ANDROID_native_buffer`. The Android-specific test expects
private loader extensions to be hidden; this standalone build uses Termux's
Khronos loader. Preserve this failure as a platform/loader qualification issue;
do not edit the CTS test or count the remaining 10,487 cases as passed. Evidence:
`temp/panvk-qualification/evidence/vk-info-fixed-01/`.

Vulkan compute also found failures in the controls, independent of the nested
prototype. The release's `compute.pipeline.basic.*` run stopped with 13 passes,
one unsupported case and one failure: `empty_workgroup_y` returned 0 rather than
1 after an empty dispatch followed by a 1x1x1 dispatch. A separate maximum-local-
size run failed on X, first at invocation 32 of 512. The source-built baseline
`db0bf89a…` also failed that test; the accepted workgroup driver failed at
invocation 64 of 1024. Each run stopped at that first failure; Y/Z maximum sizes
were not exercised. QPA evidence is in `vk-basic-release-01/` and
`vk-max-local-{release,source,lwg}-01/` under the same evidence directory.

Research `0008` adds `PANVK_G77_NO_MERGE=1`, a diagnostic that disables workgroup
merging consistently in compilation and dispatch and gives it a separate cache
identity. Build [43593759926](https://github.com/cnshing/debian-livecd-termux/actions/runs/43593759926)
produced Android SHA-256
`e0839fc06d2ea096cc29a9749ee2f8d50b5a873dd8354902ffa4608079de653d`.
It still fails maximum-local-size X at invocation 288 of 512. Disabling optional
write-back host memory with `PANVK_DEBUG=no_wb_mmap` also fails on the unmodified
source baseline. Neither diagnostic is a fix; `0008` stays off main. Evidence:
`vk-max-local-unmerged-01/` and `vk-max-local-source-uncached-01/`.
The runner records these modes explicitly with `--unmerged-compute` and
`--uncached-host-memory`.

Smaller controls narrow the failure without resolving it. A barrier-free
six-workgroup oracle passes 49,152 words at local X=512, with buffer robustness
both enabled and disabled. A reduced CTS fixture using specialization constants,
one workgroup, scalar stores, explicit buffer barriers, flush and invalidate
passes 512 words for Vulkan 1.1 and 1.3 SPIR-V. Raw ICD, Termux loader, preloaded
Android platform dependency and supported Vulkan 1.1–1.3 core-feature controls
also pass. Thus the failure is not explained by the absence of barriers,
specialization, core buffer robustness, loader use or those core feature bits
alone. Retain the failing CTS result; these reduced passes cannot replace it.
The `bare-*` and `cts-max-*` probes and their controls are documented in
`tools/panvk-probes/workgroups/README.md`.

A separate release `dEQP-VK.info.*` run stopped after nine passes, one unsupported
case and `device_memory_budget_multi_instance` failing. Its QPA reports that
heap 0 usage did not increase when allocation and budget query used different
Vulkan instances. The single-instance budget case passed. Evidence:
`temp/panvk-qualification/evidence/vk-general-info-release-01/`. This is another
baseline blocker, separate from workgroup lowering.

`tools/panvk-probes/cts/run.py` lists the requested cases and executes one at a
time, recording QPA results, exit status, mapped libraries and binary hashes.
It stops at the first failure/crash/timeout, enforces a 3 GB available-memory
floor and a run time limit, and never counts an empty or all-skipped run as a
pass. Bounded successful chunks can resume only with matching binary identities
and selection. Resumed results retain their original QPA/log directory. Nine
host tests cover parsing, resume, failure stopping, process exit failures,
all-skipped runs, explicit merge/host-memory modes and trace isolation. Use only the X11 dependency directory in
`LD_LIBRARY_PATH`; the Vulkan suite loads Termux's Vulkan **loader**, not the raw
ICD as a loader. For example, with a freshly extracted CTS artifact on the phone:

```sh
LD_LIBRARY_PATH=$PREFIX/lib/panvk-kbase/bionic/x11 python cts/run.py \
  --suite gles31 --cts <artifact/out> --driver <baseline.so> \
  --pattern 'dEQP-GLES31.info.*' --out <new-info-control>
LD_LIBRARY_PATH=$PREFIX/lib/panvk-kbase/bionic/x11 python cts/run.py \
  --suite gles31 --cts <artifact/out> --driver <accepted-workgroups.so> \
  --large-workgroups --pattern 'dEQP-GLES31.functional.compute.*' \
  --max-seconds 600 --max-cases 100 --out <new-compute-chunk>
```

Run the release/source-baseline controls first, then matched opt-in subsets.
For Vulkan, select `dEQP-VK.api.info.*`, `dEQP-VK.info.*`, then
`dEQP-VK.compute.*`. Preserve failures for diagnosis before another run; a partial
chunk is incomplete, even when every executed case passed.

### Compile control and register statistics

[Probe-only build 43561130311](https://github.com/cnshing/debian-livecd-termux/actions/runs/43561130311)
passes the Android C build with warnings treated as errors and validates every
SPIR-V probe. Future probe changes can use the workflow's `probes_only=true`
input to avoid rebuilding the driver. Set `PANVK_PROBE_STATS=1` to enable
`VK_KHR_pipeline_executable_properties` and capture all compiler statistics.
`compile` is an explicit success-without-dispatch mode, distinct from `reject`,
which requires `VK_ERROR_FEATURE_NOT_PRESENT`:

```sh
PANVK_G77_LWG=1 PANVK_G77_NESTED=1 PANVK_PROBE_STATS=1 \
  MESA_SHADER_CACHE_DISABLE=true timeout -k 5 30 \
  <new-probes/check> <nested-driver.so> <nested.spv> 1024 1 1 compile
```

Run this once before any nested dispatch; preserve its log and diagnose any
compiler error first. Once compilation succeeds, use the research branch's
matching `run.py --nested` and nested SPIR-V probes for CPU-checked dispatches.
Capture statistics for identical 128/256/512-invocation shaders with the release,
patched opt-out and patched opt-in modes, then compare the 769/1024 and nested
cases. Record registers, spills/fills, scratch and instruction counts exposed
by the driver. Measured compiler statistics for the straight-line oracle are:

| Shape | Mode | Registers | Instructions | Spills/fills |
| --- | --- | --- | --- | --- |
| 128/256/512 | release or patched opt-out | 25 | 424 | 0/0 |
| 128/256 | patched opt-in | 25 | 424 | 0/0 |
| 512 | patched opt-in | 26 | 808 | 0/0 |
| 769 | patched opt-in | 35 | 1,681 | 0/0 |
| 1024 | patched opt-in | 32 | 1,600 | 0/0 |
| 1024 nested loop, fixed scratch slices | nested opt-in | 64 | 6,039 | 539/1,090 |

The straight-line comparison uses the accepted `0001`–`0006` driver. The fixed
nested scheduler reserves 768 bytes of NIR scratch and still spills heavily.
Evidence: `temp/panvk-qualification/evidence/compiler-stats-01/` and
`temp/panvk-qualification/nested-slices-compile.log`. These are static compiler
counts, not GPU throughput measurements; register-pressure performance remains
an open gate.

`--trace-loader <trace-loader.so>` is a Vulkan-only diagnostic. The probes-only
Actions artifact includes this forwarding loader. It forwards Vulkan inputs to
Termux's loader, logs device extensions/feature structure types, allocations,
specialization and post-invalidate mapped words, and saves shader modules under
`<output>/spirv/`. The report records its binary hash; normal runs clear inherited
trace settings. For example, repeat only the first failing case with this flag,
then run the exact saved SPIR-V through `check ... run-cts-max`. Additional CPU
logging/reads can affect timing, so a traced pass alone cannot clear the original
failure. Keep untraced controls and both logs.

## Desktop qualification still required

The fixed `0007` binary passed **20 private GNOME/Ghostty cycles** with caching
enabled and both opt-ins set. Both host checkers pass: 40 GTK captures with
maximum channel error 0, 40 GPU Ghostty captures, rejected stale-frame controls,
normal Ghostty exit and preserved session isolation. Presentation uses CPU
readback. Evidence:
`temp/panvk-qualification/evidence/nested-slices/desktop-20-01/`.

The first 30-minute attempt stopped after six samples through 151.5 seconds
because another owner's private X93 display appeared. None of the monitored
workloads exited, but isolation failed; this is not a completed soak. Evidence:
`temp/panvk-qualification/evidence/nested-slices/soak-30min-01/`. Retry 02 was
stopped deliberately to yield the shared lock to a previously queued short
package test. Neither partial interval counts toward the required continuous
1,800 seconds.

After a soak, run `tests/native/check-panvk-soak.py <evidence-directory>` as
well as both pixel checkers. It requires at least 1,800 continuous seconds,
samples with no gap over 90 seconds, stable Shell/cube/gears PIDs, the same
mapped PanVK path and Mali FDs in every sample and final audit, changing capture
files, GL frame progress covering the interval and preserved session isolation.
It reports RSS and FD counts without treating warm-up growth as a leak verdict.
Eight host tests reject interrupted, short, gapped, restarted, driver-switched,
isolation-failed, stalled and missing-capture evidence. This is stability
evidence; it does not establish pixel correctness for every soak frame or GPU
throughput.

The private harness can run the 20 capture cycles and 30-minute soak together:

```sh
python panvk-desktop.py --mode shm --cycles 20 --soak-seconds 1800 \
  --driver <qualified.so> --ghostty-probe --out <new-directory>
```

Retrieve the whole directory and run both host checkers. Check `PHONE-STATUS`,
memory and the shared private-display lock first; do not overlap the soak with
another GPU qualification. Preserve the managed session and stop only owned
test processes. This harness starts a private compositor, not the complete
installed controller, so its captures cannot count as the installed 30/30 gate.

For that final gate, the current controller's `graphics.PANVK` selects only
`$PREFIX/lib/panvk-kbase`; simply installing the source package does not switch
it. Prepare a controller copy with **only** `PANVK` set to the candidate's
installed root, check both ABI ICD library paths and provenance, and run the
private harness with `--integrated --controller-dir <staged-controller>` first.
Once those checks pass and an interruption is agreed, save the installed
controller file/hash and session renderer, stop the managed desktop through
its controller, atomically install that same tested graphics module, and start
the normal Zink session. Run `desktop.py validate` in that session, preserving
the output and compositor maps proving the candidate actually loaded. Restore
the saved graphics module and restart the previous renderer on failure; do not
repin the normal package unless all 30 checks pass. The live session has not
been interrupted for this step.

## Where the versions stand

Measured on the phone with the packaged driver (`mesa-vulkan-icd-panvk-kbase` 26.3.1) and
Mesa 26.2.6-103:

| | Reported now | Wanted | What decides it |
| --- | --- | --- | --- |
| Vulkan | 1.3.363 | 1.4 | declarations pass the audit; CTS behavior has blockers |
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
| The imported patches, G77 adaptation and follow-up fixes | `tools/panvk-probes/workgroup-patches/0001` to `0006` |
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

1. **Qualify nested barriers beyond the probes.** `0007` now passes the nested
   CPU oracles and repeated caches behind `PANVK_G77_NESTED=1`. Extend CTS
   coverage and close the baseline compute failures before making it automatic.
   `0005` already covers partial subgroups, keeping hardware barriers unconditional.
2. **Variable workgroup sizes** (`ARB_compute_variable_group_size`) now pass the
   five-shape GL probe above; extend coverage with the conformance subset.
3. **Extend the conformance subset**: the 195 GLES compute cases above pass on
   both the release and opt-in drivers. Vulkan compute, broader coverage and
   the Android loader information-test failure still need qualification.
4. **Cache identity is now covered.** `0006` hashes the architecture-9 opt-in into the
   physical device cache digest, uses that digest for both the pipeline UUID and the disk
   cache timestamp, and the phone tests confirm distinct UUIDs with correct repeated cached
   output. The older hash-pinned Ghostty experiment launcher still disables caching for its
   older binary. Continue testing cache reuse when changing the lowering pass.
5. **Register pressure.** The compiler statistics above quantify the straight-line
   cases and show heavy spilling in the nested scheduler. Measure GPU throughput
   and broader shader pressure; the 256-thread hardware cap is not a performance proof.
6. **Then drop the opt-ins** for architecture 9 after qualification. The fixed nested
   driver passed the private 20-cycle run. The 30-minute soak and installed 30/30
   validation still remain.

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

The repeatable declaration audit is `tools/panvk-probes/audit-vulkan14.py`:

```sh
python3 tools/panvk-probes/audit-vulkan14.py <single-device-vulkaninfo.txt> --out <audit.json>
```

Against the saved packaged-driver dump it passes **77/77 checks** covering the
additional 1.4 features, limits, subgroup flags and the host-copy streaming path.
Four host tests check hexadecimal limits, arrays, missing conditional features
and conflicting multi-device input. The requirements come from Khronos'
[feature requirements](https://docs.vulkan.org/spec/latest/chapters/features.html#features-requirements)
and [1.4 requirements](https://docs.vulkan.org/features/latest/features/proposals/VK_VERSION_1_4.html).
It checks declarations added by 1.4; it does not requalify inherited Vulkan
requirements or prove their behavior. Its report always records
`conformance_proven: false`. Local report:
`temp/panvk-qualification/vulkan14-audit.json`. In particular, a true
`largePoints` flag cannot establish correct point rendering; use the rendering
control below.

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

### Isolated point-size result, 2026-11-14

The point-size-only variant in Actions
[43595656433](https://github.com/cnshing/debian-livecd-termux/actions/runs/43595656433)
passes the 11-pixel point control in both ABIs: 121 yellow pixels, plus 185 green
wide-line pixels and 1,154 triangle pixels. The Android 64×64 image is byte equal
to the saved lavapipe reference. Patched ICD SHA-256 values:

- Android: `d8cc7af890341631df873a552ad4fe89c469751d68d3e801cf2a614277fcf361`
- glibc: `f76b5c7181b32470608f9cb09dade82b6c154f82a3e3aa5578d19c53af6d3f5c`

The Android binary also passes two private GNOME/GTK cycles: four captures,
maximum channel error 0, stale-frame control rejected and session isolation
preserved. The earlier combined X11/point-size failure is not reproduced in
this bounded point-size-only test. Evidence:
`temp/panvk-qualification/evidence/point-only/{graphics-01,desktop-gtk-02-01}/`.
This build has no large-workgroup series and exposes GL 4.2. Its separate Ghostty
attempt exits before shell readiness, so it does not qualify Ghostty or the
combined point-size/workgroup driver. No installed driver was changed.

## Shared prerequisite: a package that can carry a patch

Both changes are patches to the driver, and the package installs upstream's release
binaries. `.github/workflows/panvk-driver.yml` reconstructs the release's source (tree
`4a8e9a8c…`) and builds Bionic and glibc drivers in CI; `panvk-workgroups.yml` does the same
with the workgroup series. What is missing:

- **Qualify and promote the source-built candidate**: the new
  `mesa-vulkan-icd-panvk-kbase-source` recipe pins both ABIs by hash and installs them beside
  the release stack. The rebuilt, unmodified driver gave the same probe pictures as the
  release, but byte equality with the release cannot be shown. Installed desktop validation
  (30 of 30) is still required before changing the normal package's binary pins.
- **Separate variants now exist in CI.** The `driver-patches/` pair (X11 sonames, point
  size) failed GTK swapchain creation together. The isolated `point-size` variant
  now passes the rendering control and short GTK run above; `x11` still needs its
  independent test. Keep new patches isolated as well.
- A source-built driver can link Termux's X11 library names directly, which would retire
  the package's `bionic/x11` link directory.

The SYNC_FD port needs the same step. Do it once, first.

## Suggested order

1. Qualify the unmodified source-built candidate against the release, then repin the normal package.
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
