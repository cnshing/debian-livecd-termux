# G77 JM sync-file experiment

This series applies directly to the reconstructed p0175 source (tree
`4a8e9a8cbb34b9fb91a9ad2040319aceb075b973`). It excludes both original
`driver-patches/` experiments and the large-workgroup series.

The fence-trigger mechanism comes from JimVulkan/mali-panvk v1.6.0
(`58f2c55854`, `src/panfrost/lib/kmod/kbase_kmod.c`, MIT). Its source credits
XclipseTools; the repository's license is retained as `UPSTREAM-LICENSE`.
Only the soft-atom mechanism is adapted. The existing atom allocator, probed
kernel layout and event draining remain responsible for atom lifetime; the
new fence atom has no CPU waiter and is reclaimed on its own event.
GPU completion remains tracked by GPU atoms rather than the later soft atom.

The sync object owns a copy of the submitted fence until reset, replacement,
move or destruction. Each export owns another copy. Import of `-1` signals the
object immediately. Imported waiter storage is freed on replacement and on a
successful CPU wait. Export is enabled for architecture 9, while the existing
CSF path and the disabled v6/v7 export path are preserved.

Builds: `.github/workflows/panvk-sync-fd.yml`, Bionic and arm64 glibc. The
unpatched ICD and `patched/` ICD are separate artifacts in the same build.
This is a validation artifact; the package recipe still selects its existing
upstream binaries until qualification and provenance pinning are complete.

The pending fixture is specific to the verified x1s JM uAPI 11.35, 56-byte
v2 atom layout. It submits a software-event wait and a dependent fence trigger;
no GPU job is blocked. It checks the fence is pending, runs the probe with a
2-second process deadline, and releases the event in `finally`. The probe
requires a 100-ms Vulkan CPU-wait timeout as well as a 100-ms poll timeout on
the imported-and-re-exported semaphore payload. The fixture requires a clean
signal after release. Other kernels need their own verified fixture layout.

On the phone, with privately staged CI artifacts:

```sh
sync-fd /private/patched/libvulkan_panfrost.so --exercise
python jm-pending-fence.py /private/sync-fd /private/patched/libvulkan_panfrost.so
```

`--exercise` checks an empty first submission, 300 GPU fills with every output
word checked, fence export/poll/import, semaphore reuse, FD lifetime, completed
export and import of `-1`. Unsupported SYNC_FD returns 77, not an acceptance
pass. Normal invocation without a mode retains the old capability report.

SYNC_FD support alone cannot make a dma-buf safe on the S20 kernel. Mesa patch
`0024-zink-wait-for-unattached-dmabuf-fences.patch` supplies the separate batch
completion wait when attaching a fence fails. Keep Mesa patches 0021–0023 for
older ICDs. Ghostty additionally needs the workgroup/version qualification
tracked by the version-bump handoff.
