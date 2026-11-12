# x1s PanVK continuation: desktop and driver validation

Continuation of `temp/gpu-x1s/PANVK-REST-HANDOFF.md`, 2026-11-11. Research branch:
`research/panvk-kbase-probes`. The managed desktop remains in software mode.

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
quadrant alternates red/yellow to detect stale content. Each image has 100
sampled pixels across four GL-rendered quadrants. The checker also compares
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
Its private rebuilt-Mesa validation is tracked below; the release tests above
do not include this patch.

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
JM path to select per-vertex FP16 point sizes. Its validation remains separate
from the unmodified baseline.

App AHB imports return INVALID_EXTERNAL_HANDLE. Logcat reports
`complete metadata unavailable rc=-95; refusing guessed layout`; the driver
cannot get usable Samsung mapper metadata. Raw DRI3's WSI-owned buffers still
work, which does not establish support for externally allocated app buffers.
No mapper ABI was guessed or enabled. The `ahb_render2` debug overread is
excluded from the CI builds. Raw logs: `panvk-runs/wider-*-release/`.

## Source builds and open validation

The CI workflow now reconstructs and builds both ABIs without a rooted-device
build path. The reconstructed unmodified source content tree is
`4a8e9a8cbb34b9fb91a9ad2040319aceb075b973`. The upstream script creates
timestamped commits; the release label `795ca7ff3e8` is not a tree hash. The
release supplies no content-tree hash, so source reconstruction and matching
runtime results cannot establish byte-for-byte binary equivalence by themselves.

The workflow retains an unmodified control and a separately identified variant
with Termux X11 sonames and the v9 point-size patch. The glibc variant's RUNPATH
is postprocessed to `$ORIGIN`, with the operation recorded in its receipt.

Source-build runtime validation, rebuilt-Mesa native-fence validation, and
the 30-minute soak are in progress. This report will be updated with their
actual results before the continuation finishes.

Production packaging, automatic renderer selection, full application/fresh
install acceptance, other-device regression acceptance, browser presentation,
and hardware video remain separate requirements. No driver or Mesa package
has been installed into the running desktop by these tests. Firefox workloads
remain skipped and ANGLE remains excluded.
