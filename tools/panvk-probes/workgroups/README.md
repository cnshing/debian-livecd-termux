# G77 large-workgroup experiment

Builds run in GitHub Actions (`panvk-workgroups.yml`). The installed driver and
managed desktop selection stay on their existing packages.

Patches `0001`–`0003` import soulexit/panvk-kirin990
`c024c056ac2426acead6a8741ccc38081964fddb`, patches `0012`, `0044`, `0061`
(MIT; license beside the patches). `0004` gates architecture-9 lowering with
`PANVK_G77_LWG=1`. `0005` pads partial subgroups and masks excess logical lanes;
`0006` separates pipeline and disk caches by mode. `0007` adds continuation-based
nested barriers, separately gated by `PANVK_G77_NESTED=1`, including live-value
spills, per-copy scratch and dynamic loops/branches. This series excludes the
independent X11-soname and point-size patches.

With the large-workgroup opt-in, the driver reports 1024 invocations and Zink
exposes GL 4.6/GLES 3.2 without version overrides. This remains experimental:
passing these probes does not establish conformance. Do not enable it globally
before the remaining CTS and desktop gates in
[PANVK-VERSION-BUMP-HANDOFF.md](../../../docs/native/PANVK-VERSION-BUMP-HANDOFF.md).
Unsupported large workgroups must fail pipeline creation before dispatch.

The CI artifact contains baseline/patched ICDs and Android probes. Run from a
fresh private directory on x1s:

```sh
python workgroups/run.py --baseline /private/base.so --patched /private/patched.so \
  --nested --out /private/results-uncached
```

Without `--nested`, the runner requires the nested case to be refused. With it,
loop, uniform-branch, break/continue and 769-invocation nested cases must produce
correct output. Baseline and opt-out controls precede opt-in dispatches; shaders
above advertised limits are never dispatched. Every successful case checks 16
words per invocation against a CPU oracle: local/global IDs, workgroup sizes,
shared memory, atomics, subgroup operations, module-private variables and values
live across barriers. Shapes include aligned and partial-subgroup workgroups in
one, two and three dimensions, through 1024 invocations. Stop at the first error.

Caches are disabled by default. Add `--shader-cache` for cold and warm runs in
fresh sibling output directories; they share a private cache in their parent.
The fixed nested driver passed all 66 decisions and 3,615,840 words across these
three modes. It also passed 20 private GNOME/Ghostty cycles. The handoff records
exact binary identities, 195 passing GLES compute cases on each control driver,
and Vulkan CTS failures that still block promotion.

## Diagnostic probes

`PANVK_PROBE_STATS=1` enables compiler executable statistics. `compile` creates
a pipeline without dispatch; preflight a new lowering before running it.
`PANVK_PROBE_ROBUST=0` disables core buffer robustness to match CTS defaults.

`bare-{256,512,769,1024}.spv` produces the same output layout without barriers,
shared memory or subgroup operations. A passing barrier-based probe alone does
not cover this path.

`cts-max-{1.1,1.3}.spv` reduces the CTS maximum-local-size test to one specialized
workgroup, scalar stores, buffer barriers and explicit mapped-memory cache
operations. Its CPU oracle requires every word to equal 1:

```sh
PANVK_PROBE_ROBUST=0 workgroups/check /private/driver.so \
  workgroups/cts-max-1.3.spv 512 1 1 compile-cts-max
PANVK_PROBE_ROBUST=0 workgroups/check /private/driver.so \
  workgroups/cts-max-1.3.spv 512 1 1 run-cts-max
```

`PANVK_PROBE_CORE_FEATURES=1` enables the supported Vulkan 1.1–1.3 core
features for this fixture. `PANVK_PROBE_COPY_READBACK=1` copies the mapped
output through `memcpy` before checking, matching the CTS readback operation.
The executable logs the selected memory type and allocation size.

The check executable can load either a raw ICD or a Vulkan loader. For a loader,
set `VK_DRIVER_FILES` to a private ICD JSON selecting the intended driver.

## Older Ghostty launcher snapshot

`ghostty-gpu.py` retains its older hash-pinned driver and Mesa 26.2.6-102 snapshot.
After staging those exact artifacts from the
[Ghostty handoff](../../../docs/native/GHOSTTY-PANVK-HANDOFF.md), copy the launcher
to `~/gpu-x1s/panvk/workgroups/` and invoke it with Python. It checks hashes and
joins the existing session without changing its defaults. That older snapshot
still requires its disabled shader cache and uses GPU rendering with CPU
presentation readback. It is distinct from the newer cache-qualified nested
binary. Current DMA-BUF work is documented separately in
[PANVK-SYNC-FD-HANDOFF.md](../../../docs/native/PANVK-SYNC-FD-HANDOFF.md).
