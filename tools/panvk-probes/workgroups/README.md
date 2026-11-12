# G77 large-workgroup experiment

Research only. The installed PanVK package and desktop configuration are not
changed. Builds run only in GitHub Actions (`panvk-workgroups.yml`).

Source: soulexit/panvk-kirin990 c024c056ac2426acead6a8741ccc38081964fddb,
`patches/mesa-26.3/0012`, `0044`, `0061` (MIT; license beside the patches).
These three patches apply to our reconstructed p0175 tree without other G76
patches. The independent series deliberately excludes the earlier point-size
and X11-soname experiment, which regressed GTK presentation.

The fourth patch enables the pass for PAN_ARCH=9 only with PANVK_G77_LWG=1.
It uses half the device's thread limit, requires subgroup-aligned copy sizes,
and rejects compute shaders still above that limit after preprocessing.
Unsupported large workgroups must fail pipeline creation, never GPU execution.

For this opt-in **experimental subset only**, the Vulkan workgroup limits are
1024. This is not a claim of Vulkan or OpenGL 4.3 conformance. Barriers in
control flow, awkward workgroup sizes, variable workgroups and other unhandled
patterns are not a general implementation. No GL/GLSL version override is used.
Do not set this environment variable for the managed desktop or normal apps.
Shader caches must be disabled during the experiment because the opt-in is not
part of the upstream cache identity.

The CI artifact contains a baseline ICD, patched ICD and Android probes. On
x1s, in a fresh private directory, run its probes with:

```
python workgroups/run.py --baseline /private/libvulkan_panfrost.so \
  --patched /private/patched/libvulkan_panfrost.so --out /private/results-new
```

The runner tests 128/256-invocation baseline and opt-out controls before enabling
the pass. Larger workgroups are tested only with the pass enabled, since register
pressure can lower the original hardware residency limit. It
never dispatches beyond advertised limits. Each successful case checks all 16
output words per invocation against a CPU oracle: local/global IDs, workgroup
sizes, multiple dispatch groups, shared-memory atomics and barriers, subgroup
IDs/count/reduction/ballot, module-private variables and values live across
barriers. Tests cover 128, 256, 512, 960 and 1024 invocations with 1D, 2D and 3D
workgroups. Uniform loop barriers and a prime-sized workgroup are expected
pipeline rejections. Each process has a bounded wait; stop at the first error.

Further gates before promotion: handle all required valid workgroup patterns,
full capability audit against our exact Zink build, relevant Vulkan/GL CTS,
Ghostty output/input correctness, and presentation regressions. The previously
deferred 30-minute soak remains pending independently.
