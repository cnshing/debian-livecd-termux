# x1s PanVK continuation: desktop and driver validation

Continuation of `temp/gpu-x1s/PANVK-REST-HANDOFF.md`, 2026-11-11. Research branch:
`research/panvk-kbase-probes`. The earlier primary runs preserved the managed
software desktop; the later stopped-state checkpoint is recorded below.

## Private desktop results

The release Android PanVK ICD with Mesa 26.2.6 Zink starts GNOME Shell 48.8,
Nautilus, Settings, and a GTK4 GLES 3.1 GLArea. Shell and the GLArea process map
`libvulkan_panfrost.so` and hold `/dev/mali0` FDs; no ANGLE mapping was found.
The GLArea reports `zink Vulkan 1.3(Mali-G77 MC11 (MESA_PANVK))`. Captures of
Shell, Nautilus and Settings were inspected visually.

| Private server / transport | Window/fullscreen cycles | Captures checked | Color result |
| --- | ---: | ---: | --- |
| lorie, default MIT-SHM | 20 | 40 | PASS, maximum channel error 0 |
| lorie, raw DRI3 | 20 | 40 | PASS, maximum channel error 0 |
| Xvfb, MIT-SHM / Kopper DRI2 | 20 | 40 | PASS, maximum channel error 0 |

Each cycle includes odd-size window resizing, then fullscreen. The top-left
quadrant alternates red/yellow to detect stale content. Each image checks every
quadrant interior pixel (two-pixel boundary inset) plus 100 distributed samples.
The checker also compares
the drawable, X window and screenshot geometry; its deliberately stale-phase
negative control is rejected for all three transports. Existing color
thresholds were not relaxed.

Both private lorie transports also completed 100 normal vkcube start/stop
cycles (`--c 3`, bounded individually), without restarting Shell. All five
primary runs preserved the managed desktop, X server and shared codec-daemon
identities and status. Small smoke runs are retained separately, including an
initial failed driver load and a missing-tool harness correction.

Evidence is under `temp/gpu-x1s/panvk-runs/desktop-{shm,raw,xvfb}-20/` and the
phone's `~/gpu-x1s/panvk/desktop-*-restarts100/`. The test harness and oracle
are preserved in `tests/native/`; reproduction is in
`tools/panvk-probes/README.md`.

### Library lookup and native fences

The normal GNOME environment puts `$PREFIX/lib` on `LD_LIBRARY_PATH`. That
selects Termux's `libbinder_ndk.so` while loading Android's `libui.so`, and the
ICD then fails with a missing versioned dependency. A minimal enumerate control
reproduces the failure with that entry and passes without it. The private tests
remove that entry while keeping the private GNOME paths and X11 symlinks.
This is an experimental environment adjustment, not an installed default.

Shell's release-driver tests render correctly but repeatedly log
`vkCreateSemaphore ... VK_ERROR_INVALID_EXTERNAL_HANDLE`. The new `sync-fd`
probe shows both OPAQUE_FD and SYNC_FD with importable=0, exportable=0, and
exportable semaphore creation returning `-1000072003`. Zink 26.2.6 advertises
native fences based only on the extension names. The Mesa recipe patch queries
SYNC_FD's actual import/export features before advertising native fences.
The private Mesa 26.2.6-101 build passed another 20 window/fullscreen cycles
on each lorie transport: 80 captures, maximum channel error zero, with no
semaphore-creation errors in the Shell logs. The processes mapped the private
rebuilt libgallium. The SHM run briefly overlapped another private display;
its correct pixels and unchanged managed state remain useful correctness
evidence, but this is not an exclusive performance measurement.

Mesa CI [43147207382](https://github.com/cnshing/debian-livecd-termux/actions/runs/43147207382)
produced `debs-mesa-62755ab3f723f2a7`. It was extracted privately, not installed.
Evidence: `panvk-runs/desktop-{raw,shm}-fence101-atomic20/`.
An earlier raw run stopped after 23 captures because the harness read a
partially written JSON command. Atomic command replacement fixed that race;
the complete rerun above passed. This was a harness failure.

## Wider release-driver probes

CI run `43144865003` compiled both ABIs from the pinned Zenith tree with
Vulkan-Headers v1.4.363. The shader tools were glslang 16.6.0 and SPIRV-Tools
2026.4~rc2, with exact receipts in the artifacts. There were no test timeouts.

| Group | Android | glibc | Interpretation |
| --- | --- | --- | --- |
| Sync, compute, texture feature workloads | PASS | PASS | Actual submissions and readbacks |
| Phase7 API cases | 5/6 exit zero | 5/6 exit zero | Indirect-copy case returns extension-not-present |
| Phase7 compute cases | 7/7 | 7/7 | Expected shader outputs |
| Graphics features | FAIL | FAIL | Requested 11-pixel point produces 25 yellow pixels |
| BC format query | Exit zero | Exit zero | Capability query, not a BC workload acceptance |
| App AHB import variants | FAIL | Not applicable | No usable Samsung gralloc layout metadata |
| fdimport / fdimport_mtk | FAIL | Not applicable | No DMA heap / unsupported allocator path |

The runner executed 26 Android processes and 18 glibc processes; 16 in each ABI
exited zero. These totals include capability queries and are not a conformant
Vulkan acceptance score.

The graphics readback shows a correct red triangle and green 5-pixel line, but
the yellow point is 5x5 rather than the shader's requested 11x11. The upstream
test uses one combined boolean for both dynamicRendering and largePoints, so
its printed dynamicRendering FAIL does not isolate dynamic rendering as the
cause. The v9 malloc-vertex path omits `point_size_array_format` and always
sets fixed size from the line width. A small driver patch follows Panfrost's
JM path to select per-vertex FP16 point sizes. The source-build results below
retain the unmodified baseline as a control.

App AHB imports return INVALID_EXTERNAL_HANDLE. Logcat reports
`complete metadata unavailable rc=-95; refusing guessed layout`; the driver
cannot get usable Samsung mapper metadata. Raw DRI3's WSI-owned buffers still
work, which does not establish support for externally allocated app buffers.
No mapper ABI was guessed or enabled. The `ahb_render2` debug overread is
excluded from the CI builds. Raw logs: `panvk-runs/wider-*-release/`.

## Source builds and runtime results

The CI workflow now reconstructs and builds both ABIs without a rooted-device
build path. The reconstructed unmodified source content tree is
`4a8e9a8cbb34b9fb91a9ad2040319aceb075b973`. The upstream script creates
timestamped commits; the release label `795ca7ff3e8` is not a tree hash. The
release supplies no content-tree hash, so source reconstruction and matching
runtime results cannot establish byte-for-byte binary equivalence by themselves.

The workflow retains an unmodified control and a separately identified variant
with Termux X11 sonames and the v9 point-size patch. The patched content tree
is `d2076d81f3555a3375e25e323f16126da101813f`. Each build job independently
reconstructs the source and asserts the unmodified tree hash. The glibc
variant's RUNPATH is postprocessed to `$ORIGIN`, with the operation recorded
in its receipt.

Full source CI [43148192136](https://github.com/cnshing/debian-livecd-termux/actions/runs/43148192136)
passed both ABIs and both variants. Android runtime testing used its artifact;
glibc used the already completed job from run `43146817287`, which has the same
asserted content trees. Probe CI
[43148270758](https://github.com/cnshing/debian-livecd-termux/actions/runs/43148270758)
also passed both ABIs. Runtime `driverInfo` identifies each build's own
timestamped commit and agrees with its receipt; it is not the release label.

| Source-build check | Android | glibc |
| --- | --- | --- |
| Baseline basic probes | 7/7 exit zero | 7/7 exit zero |
| Patched basic probes | 7/7 exit zero | 7/7 exit zero |
| All three triangle RGBA dumps, both variants | Identical to release | Identical to release |
| Patched graphics workload | PASS, 121 yellow pixels | PASS, 121 yellow pixels |
| Patched wider processes | 17/26 exit zero | 17/18 exit zero |

The patched 64x64 graphics RGBA readback is byte-for-byte identical on Android,
glibc, and the separately selected CPU control. The unmodified glibc build
reproduces the release point-size failure (25 yellow pixels, 16/18 processes
exit zero). The remaining patched failures are the same unsupported
indirect-copy, Android AHB, and allocator paths described above; they are not
accepted as passes. External semaphore import/export remains unsupported.

![Graphics readback: release baseline left, corrected point size right](images/panvk-point-size.png)

Evidence: `panvk-runs/basic-{android,glibc}-rebuilt-{base,patched}/`,
`wider-glibc-rebuilt-base/`, `wider-{android,glibc}-rebuilt-patched/`, and
`55-final-identity-graphics.txt` / `56-android-graphics-dump.txt`.
### Rebuilt Android X11 check: loading passes, patched presentation fails

At the user's request, short correctness checks proceeded regardless of other
private displays, recording overlap separately. Without the X11 symlink
directory, the patched ICD starts private GNOME and maps the normal Termux
`libxcb`, `libX11-xcb`, extension libraries and `libxshmfence`, alongside the
expected rebuilt PanVK and private Mesa libraries. A direct `RTLD_NOW` check
loads all nine unversioned libraries and resolves all 89 symbols required by
the pinned `wsi_x11_dlopen.c`; none are missing. Device driver/Mesa checksums
match the CI artifacts. X11 library loading therefore passes.

The patched driver's GTK4 presentation nevertheless fails on both raw DRI3
and SHM with `zink: could not create swapchain` and `GLXBadCurrentWindow`.
Restoring the X11 symlink directory produces the same failure. During one
failure the audit attempted to inspect an exiting GTK process and received
`PermissionError` on its FDs; its GTK log identifies the presentation error.
An earlier attempt also exposed an xdotool search race, now corrected to
retry when the window has not appeared yet.

The release Android ICD and the rebuilt **unmodified baseline**, tested with
the same private Mesa 26.2.6-101, each complete two window/fullscreen cycles
and produce four correct captures (maximum channel error zero). Those controls
overlap other private activity, and their broad before/after snapshots differ;
they establish pixel correctness rather than exclusive isolation. The patched
variant's failures also reproduce with unchanged snapshots. This isolates an
unresolved presentation regression to the patched variant under the tested
setup; it does not identify which patch or interaction causes it. The two-patch
series needs separate-variant bisection before desktop acceptance. The passing
offscreen point-size workload does not override this failure.

Evidence: `panvk-runs/desktop-rebuilt-patched-{raw-short,raw-short2,shm-short,raw-xlibs-control}/`,
`desktop-release-current-control/`, `desktop-rebuilt-base-raw-control/`, and
logs 57–68. `68-x11-symbol-check.txt` records the direct library check.
No patched driver was installed globally. At the later continuation checkpoint,
the managed desktop and earlier shared-daemon PIDs were already absent; status
reported stopped. They were not restarted. This differs from the unchanged
live-state snapshots retained for the earlier primary validation runs.

## Soak pending and remaining acceptance

The attempted 30-minute raw-DRI3 soak did not complete. With the release driver
and original Mesa, the private Shell/session ended after about 16.5 minutes;
the last captured resource sample was at 970.9 seconds. vkcube subsequently
logged SIGSEGV in the driver during display shutdown. The test failed and
does not establish 30-minute stability. Another independent private session
was present initially and absent at the end, so the broad isolation comparison
also failed. The managed desktop, live X server and shared codec daemon retained
their identities and status. No evidence establishes whether the other session
contributed to the failure.

At the 789-second audit, Shell RSS was 291768 KiB versus 304840 initially;
vkcube stayed at 28108 KiB; glxgears increased from 168120 to 170232 KiB.
Each process retained two Mali FDs and six dma-buf FDs. Android thermal status
rose from 2 to 3; a mid-run snapshot recorded skin 43.7 C, AP 50.9 C and battery
41.5 C. These partial observations are not a leak or thermal acceptance result.
Raw evidence is retained in `panvk-runs/desktop-raw-soak30/` and logs 34–44.

The user requested finishing this short-run handoff and leaving the soak
pending. Do not count this attempt as a pass. A future quiet-window rerun must
cover each required ABI/transport/present-mode combination with bounded runs,
resource audits, thermal readings, and attributable crash/error logs. Separate
X displays share GPU, CPU, memory and thermal resources: competing activity
limits performance and failure attribution, but its presence alone does not
disprove a correct captured frame. The harness now refuses other private
displays conservatively and detects them during a run. Short correctness checks
can explicitly allow overlap with `--allow-other-displays`; this option is
rejected for soaks.

Production packaging, automatic renderer selection, full application/fresh
install acceptance, other-device regression acceptance, browser presentation,
and hardware video remain separate requirements. No driver or Mesa package
has been installed into the running desktop by these tests. Firefox workloads
remain skipped and ANGLE remains excluded.
