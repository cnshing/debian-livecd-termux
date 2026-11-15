# Handoff: Vulkan 1.4 and OpenGL 4.3 on the packaged PanVK driver

State on 2026-11-15, Galaxy S20 (`x1s`, Mali-G77 MC11, architecture 9, kbase job manager).
For whoever raises the versions the Mali stack reports. Paths under `temp/` are local files
that Git ignores.

Latest checkpoint: the Bionic `combined-ahb` candidate fixes the measured AHB
image allocation failure. Its exact buffer/image cases pass, the dedicated AHB
group completes **12 Pass / 1 NotSupported**, and an imported-image GPU render
passes Android CPU pixel readback. Installed desktop validation passes **30/30
in default and nested modes**, with the exact driver hash checked in Shell.
The original release controller is restored and validates 30/30. This candidate
has not repeated the earlier broader CTS qualification: the corrected
`combined-platform` pair separately passed **597/597 GLES**, **115 Pass /
9 NotSupported** Vulkan core/info/mapping cases and nested CPU-oracle checks.
The unsafe ION placed-map capability remains withdrawn; its thirteen cases
report NotSupported. Full conformance is not established. Package pins and API
defaults remain unchanged, and no further soak is requested or run.

## Focused iteration policy

Per the user's 2026-11-14 request, do not rerun the broad CTS selections for
every proposed fix. During AHB development, run the exact failing image case
and one relevant buffer control. Once those pass, expand to the affected AHB
group. Run broader compute/desktop regressions once for the stable candidate,
or when a change affects those paths. No soak is requested.

The runner accepts repeated `--case <exact-name>` instead of `--pattern` and
skips CTS case enumeration. It retains driver/CTS hashes, mapped-library
evidence, bounds, stop-on-failure behavior and strict QPA case matching.
Unknown/empty results cannot count as a pass. Fifteen host tests pass.
`panvk-driver.yml` now accepts `abi=android|glibc|both`, defaulting to both;
Android-only AHB diagnostics build only Bionic.

The `combined-ahb-trace` variant adds stage logging to the corrected candidate,
without changing allocation behavior or extensions. Its fourteen-patch tree is
`2c8edc10363dfe002f832b478200ee51962e0065`. It logs AHB description, dma-buf
selection, mapper/layout, image requirements and underlying import results.
Use it for diagnosis only; do not rerun broad qualification on this logging
variant or count its results as the stable candidate's qualification.

## AHB focused investigation, 2026-11-15

The diagnostic build 43690902199 confirms that the first image allocation
fails at gralloc metadata lookup, before Vulkan image initialization. The
buffer control passes. These are exact-case runs, not another broad CTS run.
The phone provides mapper 2.1, while the existing metadata paths try mapper
4/5. Read-only vendor queries, loaded through SPHAL, successfully return the
actual linear format, dma-buf, dimensions, stride, offset, size and layer count
for six controlled RGBA AHardwareBuffers, including non-aligned dimensions.

The experimental `combined-ahb` variant adds a legacy Mali metadata fallback
to the corrected thirteen-patch candidate. Standard mapper paths retain
priority. The fallback accepts only explicitly linear, single-layer
RGBA/RGBX/BGRA with validated allocation bounds; it does not guess pitch or
modify imported pixels. Its fourteen-patch content tree is
`b28956ffc095bda26bf8241badba014be178536b`. The Bionic-only
[CI build 43692804161](https://github.com/cnshing/debian-livecd-termux/actions/runs/43692804161)
succeeded from source `ee95158`. Its driver SHA-256 is
`134b668a988626a64f01ce8f1c93307a439cf208e47d775a17a42b60358c5758`.

The buffer control and previously failing image `bind_export_import_bind`
case both pass, taking 0.894 seconds total. Only then was the dedicated AHB
group expanded: all thirteen cases complete, **12 Pass / 1 NotSupported**,
with 6.252 seconds of case execution. The remaining NotSupported case,
`image.export_import_bind_bind`, is explicitly disallowed for Android AHB by
CTS itself at `vktApiExternalMemoryTests.cpp:4405`; it is not another allocation
failure. Each case maps the exact candidate, without diagnostic filtering.
The existing CI-built `ahb_render` probe also passes import, bind, GPU rendering
and Android CPU readback: interior RGBA `255 0 0 255`, clear `0 0 255 255`.

After these affected-path checks passed, the stable Bionic candidate passed
installed desktop validation **30/30 in both default and nested modes**.
Shell maps the new driver and has the expected `PANVK_G77_LWG`/`PANVK_G77_NESTED`
flags independently checked in each mode. An initial attempt could not acquire
the shared test lock and exited before making changes; the successful run
acquired it after the other test released it. The original controller hash
`46eea9ffcf91ca66fd31801c725ef97b9bcb635349d0efcac9887692dec35666`
is restored, and the release desktop again validates **30/30**. Other owners'
processes are preserved. No repeated 597-case compute selection, private
GTK/Ghostty cycle run or soak was used for this AHB-only change. The glibc
artifact remains the earlier corrected candidate, not a new fourteen-patch
build. Normal package pins and API defaults remain unchanged.

Evidence is retrieved under `temp/panvk-qualification/evidence/ahb-focus/`:
`candidate-two-cases-01/`, `candidate-dedicated-01/`, `candidate-render-01/`,
`installed-check/` and `checkpoint.json`. The preceding diagnostic cases and
six read-only vendor metadata controls are saved there as well. This closes
the measured linear RGBA AHB allocation blocker, not full AHB-format coverage
or complete Vulkan conformance.

## Combined candidate qualification, 2026-11-14

The `combined` driver variant now selects eleven patches: workgroups `0001`–
`0007`, point-size, process-wide budget, ION CPU cache mode and import coherence.
It excludes the X11 soname and diagnostic NO_MERGE patches. Both workgroup modes
remain opt-in. All eleven apply to the pinned baseline in an isolated index;
the resulting content tree is `a4db9b7adcb014dfe30ca0bfcb72e2a77913a7b2`.
The cache patch's include context was adjusted to compose with the budget patch.
The first combined build failed at that include context before producing a
candidate; [corrected build 43666745173](https://github.com/cnshing/debian-livecd-termux/actions/runs/43666745173)
succeeded for both ABIs. Driver and probe compilation remains CI-only.

| Combined artifact | SHA-256 |
| --- | --- |
| Bionic | `1fa20d672c80b87b6160fc9e3c9fcbb3d6aa11febdb312dc8e52993da04855da` |
| glibc | `228f2323f8cd2ee52728eac922b239a658467c1f5ca3eb7d4c4ec1ae3584ec0f` |

The exact combined pair passes seven basic processes and both graphics feature
checks on each ABI. The glibc probe environment includes the staged X11/Wayland
libraries followed by Chrome's normal dependency directory (which supplies
`libdrm.so.2`); the first attempt without that directory failed to load libdrm,
before Vulkan enumeration. Bionic's complete 16,384-byte graphics readback
matches the previously accepted point-size image byte for byte: 121 yellow
point pixels, 185 green line pixels and 1,154 triangle pixels.

Nested compilation succeeds before dispatch. Uncached, cold-cache and warm-cache
runs then pass **66 decisions and 3,615,840 CPU-oracle words**. Both default and
nested modes retain their distinct cache identities. Default-mode Vulkan basic
CTS completes **73 Pass, eight NotSupported**. Nested-mode basic, built-in
variables, indirect dispatch, 64-bit indexing and info queries complete all
**156 cases: 130 Pass, 26 NotSupported**, including both budget tests. Every
case maps the exact combined Bionic driver without diagnostic filtering.

Additional controls use the previously qualified import-coherence binary
`0f793fe3dc3fe8d91447401c5c3ed8b11ca6da7f87ad55511f1f0df373246b7c`:

- Vulkan built-in variables, indirect dispatch and 64-bit indexing: **35 Pass,
  17 NotSupported**, all 52 selected cases complete.
- Vulkan zero-initialized workgroup memory: **617 Pass, 29 NotSupported**, all
  646 cases complete. Run 01 reached its time bound after 621 accepted cases;
  run 02 resumed with the same identity and retained each original log path.
- GLES atomic counters and synchronization: **402/402 Pass**.
- The existing installed Zink desktop passes **30/30** before any switch.

These passing CTS controls use no diagnostic feature filtering, import flags
or trace loader. Every case maps the intended ICD. Local evidence is under
`temp/panvk-qualification/evidence/combined/control-{extended-01,zero-init-01,zero-init-02}/`;
the installed control is `installed-baseline.json`. Combined evidence is in
`oracle-{uncached,cache-cold,cache-warm}/`, `basic/`, `basic-glibc/`,
`vk-default-basic-01/` and `vk-nested-core-01/` beneath the same directory.
The combined nested-mode expansion also completes:

| CTS selection | Pass | NotSupported |
| --- | ---: | ---: |
| GLES compute, atomic counters and synchronization | 597 | 0 |
| Vulkan zero-initialized workgroup memory | 617 | 29 |
| Vulkan compute memory barriers and host/shader concurrency | 1 | 64 |

All 64 compute-barrier cases require a dedicated compute queue, which x1s does
not expose; they do not provide barrier-execution coverage. Every executed
case maps the combined ICD. Reports: `gles-nested-expanded-01/`,
`vk-nested-zero-init-01/` and `vk-nested-memory-01/`.

The integrated private run uses the phone's installed Mesa **26.2.6-103**, the
staged controller and exact combined ICD. Twenty cycles pass **40 GTK captures
with maximum channel error 0** and **40 Ghostty captures**, including stale-frame
rejection, normal exit and preserved live-session isolation. Shell, GTK and
Ghostty all map the combined driver and hold Mali FDs. Presentation remains the
CPU fallback. Evidence: `desktop-integrated-20-01/` and its two pixel reports.

Installed qualification temporarily selects the same staged root through the
actual packaged controller module, then starts normal managed sessions on `:0`:

| Managed session | Checks | GL / GLES | Driver |
| --- | --- | --- | --- |
| Combined, both opts off | 30/30 | 4.2 / 3.1 | exact combined Bionic SHA above |
| Combined, both opts on | 30/30 | 4.6 / 3.2 | exact combined Bionic SHA above |
| Restored release | 30/30 | 4.2 / 3.1 | unchanged release |

`installed-{default,nested}-identity.json` verifies the live compositor's mapped
library, binary hash and both environment flags. No GL version override is used.
The two installed screenshots show Nautilus rendering the small fixture's folder
and text file. The original controller hash is restored to
`46eea9ffcf91ca66fd31801c725ef97b9bcb635349d0efcac9887692dec35666`;
the home compatibility symlink is restored too. No package pin or saved default
renderer was changed.

The entrypoints under `~/.local/lib/livecd-native` are symlinks. Python imports
from **`$PREFIX/libexec/livecd-native`**, so replacing only the home graphics
symlink does not select the candidate. The first attempt was caught by its
wrong-driver assertion, restored automatically and archived in
`installed-wrong-selection-01/`; its 30/30 release result is not a candidate
result. Resolve the actual imported module before any future controlled switch.

The additional memory control stopped after two passes at
`dEQP-VK.memory.map_placed.exact_size.size_65536`, with SIGBUS / BUS_ADRALN.
One focused trace reproduces it on the coherence control. Android's crash log
identifies libc `memset+172` (`stp q0, q0, [x3, #-32]`), faulting at the first
placed page while CTS fills the surrounding file-backed reservation. This
localizes the CPU mapping failure but does not establish its cause. No CTS test
or allowlist has been changed. Evidence: `control-memory-01/`,
`control-placed-trace-01/` and local `combined/placed-logcat.txt`. The rest of that
78-case selection did not execute and cannot be called passing.
The exact combined driver also fails the placed selection, this time at its
first 1 MiB case (`size_1048576`, SIGBUS); the remaining twelve cases never run.
`vk-nested-placed-01/` preserves that untraced result. The independent
`vk-nested-android-extension-01/` selection fails with
`Unknown extension: VK_ANDROID_native_buffer`. These remain failures; none of
the passing subsets or installed checks establishes Vulkan conformance.

`cts/ion-map-boundary.c` is a CPU-only diagnostic built by the probes workflow.
It opens ION and memfd mappings without Vulkan or Mali, compares cached and
uncached allocations at three sizes, and compares libc memset within the ION
mapping against memset across its file-backed guard boundaries. Twelve finite
child controls catch SIGBUS/SIGSEGV and report the fault stage/address through a
pipe; caught faults still make the diagnostic exit nonzero. CPU accesses are
bracketed by `DMA_BUF_IOCTL_SYNC`, and `--cpu N` pins the parent and its children.
The original diagnostic opened ION read/write and failed with EACCES after
reboot, before any allocation. The allocator-compatible read-only correction
is source `17c5864`, [CI 43687514748](https://github.com/cnshing/debian-livecd-termux/actions/runs/43687514748).
The verified binary SHA-256 is
`13a95c22705812ff5a1f569625e6b9d4f8f90e5ae148d36cae068b3a91545e96`.

The corrected CPU-only controls complete all twelve cases on each pinned CPU:

| Control | CPU 0 | CPU 7 |
| --- | --- | --- |
| Uncached ION, libc memset confined to ION | 3 Pass | 3 Pass |
| Uncached ION, libc memset spans memfd/ION boundary | 3 Pass | 3 caught SIGBUS |
| Cached ION, isolated or mixed-boundary fill | 6 Pass | 6 Pass |

Every caught fault occurs at stage 4 (libc memset), signal 7, si_code 1
(BUS_ADRALN), for 4 KiB, 64 KiB and 1 MiB. The preceding volatile byte fill
and DMA_BUF_SYNC_START succeed. This establishes CPU/core and allocator-mode
dependence without loading Vulkan or using Mali. It does not measure actual
kernel PTE attributes. Evidence is `ion-map-boundary-readonly-cpu{0,7}.jsonl`
and corresponding stderr under the local combined evidence directory.

### Platform corrections and qualification

`combined-platform` adds two patches to the eleven-patch combined candidate.
It has a distinct binary identity and must not inherit the old candidate's
passes automatically:

- The hybrid Android/X11 Termux ICD profile omits private
  `VK_ANDROID_native_buffer`; Android-only HAL builds retain it, and public
  `VK_ANDROID_external_memory_android_hardware_buffer` remains tied to gralloc.
  The generic Termux loader does not perform the private-to-public extension
  translation used by the [AOSP loader](https://android.googlesource.com/platform/frameworks/native/+/18fa257ea2/vulkan/libvulkan/driver.cpp).
  Qualify the unmodified no-unknown-extensions case, public AHB paths and X11.
- The kmod backend records unsafe placed mapping for noncoherent ION and
  consistently omits `VK_EXT_map_memory_placed`, `memoryMapPlaced` and
  `memoryUnmapReserve` on that allocator. Other allocators retain their existing
  behavior. This withdraws an optional capability that fails on this platform;
  it does not repair the kernel/libc boundary interaction or turn the archived
  placed-map crash into a pass. Keep uncached HOST_COHERENT allocations and
  the accepted CPU/GPU coherence fixes. Qualify ordinary mapping, import/export,
  compute and desktop behavior on the new binary.

No CTS source, allowlist, diagnostic filtering or advertised API version changes.
The private-extension-only build at source `738c1b0` was superseded by the build
including the placed-map capability correction. The thirteen-patch tree is
`8ab30125381fef7d545427d557b676b3f02c8523`, verified in an isolated index without
editing the Mesa checkout. Both ABI builds succeeded in
[CI 43687729688](https://github.com/cnshing/debian-livecd-termux/actions/runs/43687729688),
source `7974fb9`. New Bionic SHA-256:
`526cd67e94f773c7684e4efd36f63fc41c4011d951bd2bea5f4db4380ec099ce`;
new glibc SHA-256:
`3fd1e8f6d93ee21afad6ea0f1ec8fc2a6d9a4cf50325b97ba3b1e35a49470526`.

Both ABIs pass seven basic probe processes and graphics readback. The
unmodified CTS platform-gate selection completes **one Pass, thirteen
NotSupported**: `no_unknown_extensions` passes and every placed-map case
correctly reports the withdrawn optional feature as unsupported. No trace
loader or test filtering is used. Installed desktop checks against this separate identity pass **30/30 in both
default and nested modes**, with exact candidate SHA and compositor flags
recorded independently. The original controller and normal release desktop
were restored and pass **30/30**. Bionic's full graphics image is byte-equal to
the old combined image; glibc's graphics probe reports the same expected pixel
counts (its launcher did not preserve the optional image-dump variable).
Evidence is retrieved under local `evidence/combined-platform/`.

The first two-cycle private GTK/Ghostty run completes rendering but fails
isolation: another owner starts Shell/daemon processes and X84 between its
before/after snapshots. Their processes and display are preserved; this is not
an accepted isolated desktop pass. A post-run release validation passes 30/30.
No soak is run. The broader run completes:

| Corrected candidate selection | Result |
| --- | --- |
| Vulkan basic compute, info and ordinary 257-byte dedicated mapping | 115 Pass, 9 NotSupported; all 124 complete |
| GLES compute, atomic counters and synchronization | 597/597 Pass |
| Nested CPU oracle | 22 accepted decisions; 1,205,280 words including baseline controls |
| GL variable workgroup size, nested | 206,304 words Pass |
| Dedicated public AHB | 9 Pass, 1 Fail; stops with 3 cases unrun |

The oracle checks 1,168,416 words on the corrected driver (off/on combined),
plus 36,864 words on the earlier combined control. All executed CTS cases map
the exact corrected Bionic binary, without diagnostic filtering or version
overrides. Ordinary mapping includes legacy/map2, remap, flush and invalidate
controls; both process-wide budget queries pass. The release desktop is
restored and passes 30/30 after CTS, with the original controller hash.
The AHB image failure matches the earlier combined control; it is not cleared
or newly introduced by these two patches.
Phone evidence root: `combined-platform-ci43687729688/`.

The long evidence path also exceeds the Unix socket path limit for GVfs.
The desktop harness now creates a short private XDG runtime directory under
`$TMPDIR`, removes it after owned-process cleanup, and records the path and
cleanup in `runtime-directory.json`. The follow-up two-cycle run confirms
that the short runtime directory is removed after owned-process cleanup.
Four GTK captures again have maximum channel error zero, and four Ghostty
captures pass pixel/stale controls and normal exit. Its strict isolation check
again rejects a new X84/Shell/daemon startup between snapshots. Both private
runs remain **pixel diagnostics, not accepted isolated desktop passes**.
Their unchanged isolation reports and explicit `pixel-diagnostics.json` reports
are preserved locally. No third retry or soak is run. Installed default/nested
30/30 remains independently accepted, and the final release restore passes
30/30 after this check as well.

The old combined candidate's dedicated public AHB control selects thirteen
cases and stops at case ten: nine Pass, then
`dEQP-VK.api.external.memory.android_hardware_buffer.dedicated.image.bind_export_import_bind`
fails `VK_ERROR_INVALID_EXTERNAL_HANDLE` from AllocateMemory; the remaining
three cases are unrun. This is a pre-existing AHB image export/import failure,
not a regression established against the new platform candidate. Earlier
release AHB image probes also failed AllocateMemory with the same error.
Source inspection finds a plausible restriction: image layout needs mapper
metadata, while the verified linear fallback only permits explicitly tagged,
driver-owned AHBs. App namespaces on this vendor API cannot reach the normal
mapper backend. This is a hypothesis, not a measured call-stage diagnosis.
A separate one-case diagnostic with the CI-built forwarding trace loader
records a single first `AllocateMemory` call, size zero/type zero, returning
`-1000072003` (`VK_ERROR_INVALID_EXTERNAL_HANDLE`). The failure is therefore
already in the initial AHB-backed image export allocation, before the test
can export its handle and reimport it into image B. Source inspection narrows
this to the driver's internal import/layout of its newly allocated AHB:
AHardwareBuffer allocation failure would instead report out-of-host-memory.
The exact inner failing stage still needs instrumentation. The verified linear
fallback requires both an explicitly driver-owned tag and CPU-read usage;
the generic image export allocation path supplies neither for this test.
No speculative layout or ownership change has been made. Diagnostic evidence:
`vk-ahb-image-diagnostic-01/`; it is excluded from qualification pass counts.
Do not disable public AHB advertising merely to clear this check or guess
vendor image pitches. Preserve the buffer passes and image failure separately.
Complete evidence is preserved both on the phone at `combined/vk-ahb-control-01/`
and in the local combined evidence directory.

### Recovery checkpoint; no further soak requested

x1s is back at `192.168.1.238` after a reboot (new boot ID observed). No owned
soak/test process remained. The owned X74 socket and lock were removed only
after checking ownership, pre-reboot mtimes and connection refusal; the other
owner's current X84 display is preserved. No unknown processes were killed. The installed controller checksum
still matches the restored original
`46eea9ffcf91ca66fd31801c725ef97b9bcb635349d0efcac9887692dec35666`.
The last soak log reaches 1,425/1,800 seconds, with no final `result.json` or
`isolation.json`. Record it as interrupted, not a soak pass. Do not restart or
extend it, per the user's request.

The probes artifact also includes `variable-size.py --large-workgroups`, with
optional `--nested`. Exact-combined GL variable-size runs now pass all five
shapes and 206,304 output words in each mode (412,608 total), with exact driver
hash and library mapping recorded in `variable-gl-{straight,nested}-01/`.
Both report GL 4.6 without a version override. Evidence has been retrieved. Prior installed 30/30 and 20-cycle private checks remain valid for their
recorded binary. New platform corrections need their own short regressions.

## Progress on the source-package prerequisite

A side-by-side `mesa-vulkan-icd-panvk-kbase-source` recipe now packages the
unmodified reconstructed driver for both ABIs, with SHA-256 pins to durable
prerelease assets and installed source provenance. Its glibc binary has the CI
RUNPATH removed. [PANVK-SOURCE-PACKAGE.md](PANVK-SOURCE-PACKAGE.md) records the
build, asset identities, isolated patch variants and promotion procedure.
The normal package and launcher selection still use the upstream release.
The combined pair above passes installed validation; the pinned unmodified
package pair remains a separate identity. Neither package is repinned while the
combined candidate's conformance blockers remain open.

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

The final nested binary `2b57c92c…`, with both workgroup and nested opt-ins
enabled, now also passes those **195/195 GLES compute cases**, with no skips or
warnings. Every case's recorded maps include that exact staged ICD. Evidence:
`temp/panvk-qualification/evidence/gles-compute-nested-01/`. This adds the final
nested candidate to the earlier release and `0001`–`0006` controls; it does not
clear the Vulkan failures below.

The packaged release's Vulkan `api.info.*` run stopped after two passes and one
failure: `dEQP-VK.api.info.android.no_unknown_extensions` reports
`Unknown extension: VK_ANDROID_native_buffer`. The Android-specific test expects
private loader extensions to be hidden; this standalone build uses Termux's
Khronos loader. Preserve this failure as a platform/loader qualification issue;
do not edit the CTS test or count the remaining 10,487 cases as passed. Evidence:
`temp/panvk-qualification/evidence/vk-info-fixed-01/`.

There is a concrete Android-loader boundary to check here: AOSP's
[`EnumerateDeviceExtensionProperties`](https://android.googlesource.com/platform/frameworks/native/+/18fa257ea2/vulkan/libvulkan/driver.cpp)
translates the private `VK_ANDROID_native_buffer` entry into `VK_KHR_swapchain`
before returning it to applications. The observed Termux-loader result differs
from that path. Preserve the failing CTS result and investigate the intended
Termux ICD/loader contract; changing the CTS allowlist would not qualify that
contract. Changes to extension advertisement also need WSI/AHB regression checks.

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

The diagnostic forwarding loader passes a one-case lavapipe CPU control and
captures CTS's exact 732-byte SPIR-V 1.0 shader. On source baseline Android hash
`18373403292ec998ae55679b4a486e215d21692d7e6d39054a58b7f4790fb97f`,
that exact shader and the reduced legacy SSBO fixture both pass 512 words with
direct and copied readback, enabling supported Vulkan 1.1–1.3 core features.
Yet the same binary fails traced CTS: immediately after invalidate, 288 mapped
words equal 1 and 224 equal 0, first non-one at index 96. CTS reports the same
index. Thus the stale CPU-visible values precede its verification copy; this
does not distinguish absent GPU writes from incoherent CPU visibility. Shader
encoding and `memcpy` alone do not explain the failure. This separately built
baseline has its own identity; it is not the earlier `db0bf89a…` control.
Evidence: `reduced-cts-legacy-01/`, `vk-max-local-source-trace-01/` and
`vk-max-local-lavapipe-trace-01/` under the qualification evidence directory.
Moving buffer allocation before pipeline creation, matching CTS, also passes
with the exact captured shader and copied readback. Evidence:
`reduced-cts-buffer-first-01/`. Device extension/features outside Vulkan 1.1–1.3
core remain differences to investigate. The features2 creation form and a
second live instance also pass the reduced exact-shader test
(`reduced-cts-features2-01/`). The updated probe build additionally passes the
full 22-decision uncached nested matrix in `nested-slices/current-probe-uncached-01/`.

A separate release `dEQP-VK.info.*` run stopped after nine passes, one unsupported
case and `device_memory_budget_multi_instance` failing. Its QPA reports that
heap 0 usage did not increase when allocation and budget query used different
Vulkan instances. The single-instance budget case passed. Evidence:
`temp/panvk-qualification/evidence/vk-general-info-release-01/`. This is another
baseline blocker, separate from workgroup lowering.

The isolated `memory-budget` variant now fixes this accounting failure. It
shares an atomic application-allocation counter between physical-device objects
for the same kernel device node, with reference-counted registry lifetime,
while retaining the local counters used for internal trimming. Actions
[43660659573](https://github.com/cnshing/debian-livecd-termux/actions/runs/43660659573)
built both ABIs. The Android driver passes both budget cases, then completes
`dEQP-VK.info.*` with **22 passes and one unsupported case**. The unsupported
peer-memory case requires a group of at least two physical GPUs. Every case
maps the intended ICD. No test was edited or filtered. Evidence: `vk-budget-fix-01/` and `vk-info-budget-fix-01/`.

- Android SHA-256: `ce9fef7506cabf99f8299f3e15895542b023dfb670be24f8a345eed0eb0cb999`
- glibc SHA-256: `fee10abad5f97f18e9cf0a438b44fd407d9486656a87286254b832bf101e2b66`

The patch and isolated CI variant are on main under `budget-patches/`; the
package pins and installed drivers are unchanged. Both ABIs also pass seven
basic processes (enumeration, compute, three triangle paths and synchronization
controls), stopping on error; the SYNC_FD probe still reports its expected
baseline unavailability. Evidence: `budget-basic-01/`. A glibc CTS budget test
has not been run.

The compute failure is now narrowed to a device-feature-controlled allocation
path. Traced CTS passes when optional features are removed, but that filtered
run is diagnostic only. More decisively, the exact reduced shader fails when
the placed-mapping feature structure is added: 336 of 512 words are wrong.
The same executable with that feature structure disabled passes all 512 words
(`reduced-cts-placed-off-01/`). Enabling this feature
makes ordinary host-visible allocations shareable even without a placed-map
request. The ION allocator hardcoded cached backing while the Vulkan memory type
advertised host coherence. The isolated `ion-cache` fix in
[43661900884](https://github.com/cnshing/debian-livecd-termux/actions/runs/43661900884)
makes the ION cached flag follow `PAN_KMOD_BO_FLAG_WB_MMAP`. Both ABIs build.
The placed-mapping reproducer then passes all 512 words. The normal, unfiltered
Vulkan basic-compute run now passes all four empty-workgroup cases and maximum
local sizes X/Y/Z. It reaches a new first failure after **52 passes, eight
unsupported cases and one failure**: `ssbo_cmd_barrier_multiple`, expected
122,815, got 17,545. The remaining 20 selected cases were not attempted.
This producer/consumer test uses a 11×5×7 dispatch and an SSBO atomic reduction;
separate dispatch ordering, multidimensional group merging and global atomic
behavior before attributing the error to a barrier alone. Evidence:
`reduced-cts-ion-fix-01/` and `vk-basic-ion-fix-01/`. Every attempted case maps the
intended ION-fix ICD.

Matched controls on that same ION-fix binary confirm that the multiple-group
case fails standalone with normal features, passes when optional features are
filtered out, and the single-group case passes unfiltered. The older `0008`
driver also passes the multiple-group case in both merge modes under the core
feature filter; disabling merging is not established as the fix. Evidence:
`vk-ssbo-ion-{multiple,multiple-core,single}-01/` and
`vk-ssbo-{merged,unmerged}-core-filter-01/`. Filtered passes remain diagnostic.
Next isolate the placed-mapping/imported-output atomic path from the other
optional feature bits; do not treat this as proven barrier failure yet.

An additional same-driver control keeps both the forwarding loader and normal
features enabled and still fails (expected 122,815, got 26,620), whereas the
same loader with the core-feature filter passes. Both failing sums are exactly
one 11×5 Z-plane's contribution, not the full seven-plane sum. This is an
observation, not yet a diagnosis.

The existing import-flag escape hatch gives a positive control: clearing
`BASE_MEM_COHERENT_SYSTEM` (`0x400`) and setting `BASE_MEM_COHERENT_LOCAL`
(`0x800`) makes the multiple-group SSBO case pass with normal CTS features.
`--local-coherent-imports` records this configuration and marks it diagnostic
only; inherited import overrides are cleared by default. The ordinary kbase
allocation path already requests local coherence, whereas imported buffers
unconditionally requested system coherence even on this non-I/O-coherent GPU.
The research `import-coherence` variant combines the ION CPU cache-mode patch
with selecting local/system coherence according to `is_io_coherent`. Build
[43663975090](https://github.com/cnshing/debian-livecd-termux/actions/runs/43663975090)
now builds both ABIs. With the recorded override, the full selected
basic-compute run first completed with **73 passes and eight unsupported cases**.
The code-built Android candidate then repeats that complete result with no
trace loader, feature filter or import override. Every case maps the exact
requested ICD, and the report is not marked diagnostic-only. Evidence:
`vk-ssbo-ion-multiple-trace-01/`, `vk-ssbo-ion-local-import-01/` and
`vk-basic-local-import-01/`.

The final `import-coherence` artifact has reconstructed Mesa content tree
`db01c10f176b6b91e929175de79fe2a564b4c3a9` and these patched ICD identities:

- Android: `0f793fe3dc3fe8d91447401c5c3ed8b11ca6da7f87ad55511f1f0df373246b7c`
- glibc: `bd62a983339cad63a4c278dbc88d53a3a40baf144f0594fe0c7fed6fb9a8ec21`

It also passes **20 private GNOME/GTK cycles**, 40 exact captures, stale-frame
rejection and session isolation. Nautilus folder contents and Settings were
visually checked. The same default candidate also passes **195/195 selected
GLES compute cases**, with no skips or warnings and the intended ICD mapped
in every case. Evidence: `vk-basic-coherence-fix-01/`,
`gles-compute-coherence-01/` and `coherence/desktop-gtk-20-01/` under the
qualification evidence directory.
The GPU-local patch and `import-coherence` variant are on main under
`coherence-patches/`; this variant includes the ION cache-mode fix but does not
include budget, point-size or workgroup patches. No default package pins were
changed. The glibc binary is build-verified; this Vulkan CTS run is Bionic.

The preceding ION-only artifact, which still has the SSBO failure, is retained
for comparison:

- Android SHA-256: `e6d981b8e4bc8d56077fc90b22a782adb0b0db2c1c766007218a23a7b091b020`
- glibc SHA-256: `3a727046e1cfe1ed484b1c1910a0a6167a304b1bdb02b2db8be8e40e59132a9f`

The ION-fix Android binary also passes **20 private GNOME/GTK cycles**: 40
captures, maximum channel error 0, stale-frame rejection and session isolation.
Shell and Settings captures were visually checked; the Nautilus capture shows
its window still loading and does not establish folder-content correctness.
Evidence: `temp/panvk-qualification/evidence/ion/desktop-gtk-20-02/`. It exposes
GL 4.2 and was not used for a Ghostty qualification. Its glibc build has not had
the same placed-mapping runtime test. The patch and isolated variant are now on
main under `ion-patches/`. This is a separate binary from the budget and nested
candidates; combine and requalify the required patches before changing defaults.

`tools/panvk-probes/cts/run.py` lists the requested cases and executes one at a
time, recording QPA results, exit status, mapped libraries and binary hashes.
It stops at the first failure/crash/timeout, enforces a 3 GB available-memory
floor and a run time limit, and never counts an empty or all-skipped run as a
pass. Bounded successful chunks can resume only with matching binary identities
and selection. Resumed results retain their original QPA/log directory. Twelve
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

`--core-features-only` additionally filters optional device feature structures
through the trace loader while retaining CTS's core 1.0–1.3 feature values and
device extension list. This changes device creation, prints an explicit warning
and sets `diagnostic_only: true` in the report. A pass in that mode is a debugging
result and cannot clear CTS qualification. It requires `--trace-loader`.

## Historical standalone nested-driver desktop qualification

The records below concern the standalone nested binary. The combined and
corrected candidates now also pass installed default/nested validation 30/30,
as recorded above. Those identities do not inherit this standalone soak.
The user has cancelled additional soak minutes; do not restart one.

The fixed `0007` binary passed **20 private GNOME/Ghostty cycles** with caching
enabled and both opt-ins set. Both host checkers pass: 40 GTK captures with
maximum channel error 0, 40 GPU Ghostty captures, rejected stale-frame controls,
normal Ghostty exit and preserved session isolation. Presentation uses CPU
readback. Evidence:
`temp/panvk-qualification/evidence/nested-slices/desktop-20-01/`.

The fixed nested driver now also passes the **continuous 30-minute private
soak**: 1,800.000 seconds, 60 samples, stable Shell/vkcube/glxgears PIDs, the
same PanVK mapping and Mali FDs throughout, GL frame progress, and preserved
session isolation. Both pixel checkers also pass its four GTK and four Ghostty
captures, including stale-frame rejection and normal terminal exit. Shell RSS
changed from 337,816 to 335,200 KiB, cube stayed at 36,944 KiB, and gears changed
from 175,000 to 177,000 KiB; FD counts stayed at 31/10/10. These endpoints do not
establish a general leak bound. Evidence and the independent soak report:
`temp/panvk-qualification/evidence/nested-slices/soak-30min-03/`.

The first attempt stopped after six samples through 151.5 seconds because
another owner's private X93 display appeared. Retry 02 was stopped deliberately
to yield the shared lock to a previously queued short package test. Neither
partial interval was added to retry 03's continuous 1,800 seconds.

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

For a short correctness regression, run the private capture cycles without a soak:

```sh
python panvk-desktop.py --mode shm --cycles 2 \
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
Resolve the symlinked entrypoint and imported `graphics.py` first: the packaged
module is under `$PREFIX/libexec/livecd-native`, not the home compatibility
symlink. Once those checks pass and an interruption is authorized, save the
actual installed module/hash, compatibility link and session renderer. Stop the managed desktop through
its controller, atomically install that same tested graphics module, and start
the normal Zink session. Run `desktop.py validate` in that session, preserving
the output and compositor maps proving the candidate actually loaded. Restore
the saved graphics module and restart the previous renderer on failure; do not
repin the normal package unless all 30 checks pass. This reversible procedure
has now been completed for both candidates, with the release controller restored.

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
| The imported patches, G77 adaptation and follow-up fixes | `tools/panvk-probes/workgroup-patches/0001` to `0007` |
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
3. **Extend the conformance subset**: the 195 GLES compute cases pass on the
   release, `0001`–`0006` and final nested drivers. The budget fix clears its
   isolated information subset, and the ION fix clears the old compute
   failures, and the import-coherence variant clears the SSBO reduction failure
   and completes the selected basic-compute subset. The combined fixes now pass
   597 GLES cases and installed default/nested 30/30. The corrected platform
   candidate additionally passes 124 core/info/mapping cases and the Android
   extension gate, and withdraws unsafe ION placed mapping. AHB image
   export/import still fails; broader full-conformance coverage remains open.
4. **Cache identity is now covered.** `0006` hashes the architecture-9 opt-in into the
   physical device cache digest, uses that digest for both the pipeline UUID and the disk
   cache timestamp, and the phone tests confirm distinct UUIDs with correct repeated cached
   output. The older hash-pinned Ghostty experiment launcher still disables caching for its
   older binary. Continue testing cache reuse when changing the lowering pass.
5. **Register pressure.** The compiler statistics above quantify the straight-line
   cases and show heavy spilling in the nested scheduler. Measure GPU throughput
   and broader shader pressure; the 256-thread hardware cap is not a performance proof.
6. **Then drop the opt-ins** for architecture 9 after qualification. The fixed nested
   standalone driver passed its private 20-cycle run and historical 30-minute
   soak. Installed 30/30 now passes on the combined and corrected candidates.
   The AHB image failure, fuller conformance coverage and performance
   qualification remain. No additional soak is requested.

The separately qualified `ghostty-panvk-dmabuf` package now provides its own
private driver/Mesa stack. The terminal launcher uses it when its device and
payload guard passes; see [PANVK-SYNC-FD-HANDOFF.md](PANVK-SYNC-FD-HANDOFF.md).
That path does not depend on promoting this candidate to the general desktop
driver. Without that package, the fallback Ghostty path still requires GL 4.3
and selects software rendering when the desktop driver exposes only GL 4.2.

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
