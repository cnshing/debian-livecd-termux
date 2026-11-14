# Mali GPU and hardware video: one stack, and where each piece stands

State on 2026-11-12, Galaxy S20 (SM-G981B `x1s`, Exynos 990, Mali-G77 MC11, Android 13, stock
kernel, no root). This page is the entry point for the Mali work; the pages it links hold the
evidence. Everything below is on `main`: the work that was spread over the PanVK research, Zink,
VA-API, Firefox and browser-video branches was merged on this date.

## One driver, five consumers

Every GPU consumer on a Mali phone uses the same Vulkan driver, the package
`mesa-vulkan-icd-panvk-kbase` (Zenith's PanVK port to Android's `mali_kbase` kernel driver, as a
Bionic and a glibc library), and every hardware codec goes through the same `termux-va` daemon to
Android's MediaCodec. What differs is only the layer on top.

| Consumer | Rendering | Hardware decode | Hardware encode | More |
| --- | --- | --- | --- | --- |
| GNOME Shell and GTK apps | Zink (Mesa GL) on PanVK, MIT-SHM presentation | n/a | n/a | [PANVK-DESKTOP.md](PANVK-DESKTOP.md) |
| Ghostty | llvmpipe by default: it needs OpenGL 4.3 and Zink on this GPU gives 4.2. GPU rendering works with the experimental large-workgroup driver, opt-in only | n/a | n/a | [GHOSTTY-PANVK-HANDOFF.md](GHOSTTY-PANVK-HANDOFF.md) |
| Chromium (Bionic) | ANGLE's Vulkan back end on PanVK | VP9 and HEVC; H.264 software | WebRTC H.264 and VP9 work with `AcceleratedVideoEncoder`, which stays off by default | [X1S-BROWSER-VERIFICATION.md](X1S-BROWSER-VERIFICATION.md) |
| Google Chrome (glibc, Bionilux) | ANGLE's Vulkan back end on the glibc PanVK | VP9 (one frame comparison below threshold) and HEVC with `android-vaapi-glibc` revision 1; H.264 software | not testable: Chrome finds no network interfaces under Bionilux | same |
| Firefox | WebRender on Zink on PanVK (on a Zink desktop) | VP9 and HEVC; H.264 software | untested | [X1S-FIREFOX-VIDEO.md](X1S-FIREFOX-VIDEO.md) |

mpv is the one exception: it still renders through VirGL on the vendor's GLES driver
(`src/native/mali.py`) and decodes through MediaCodec directly. It passed direct Vulkan rendering on
PanVK in the desktop acceptance, so it can move to the shared driver; that has not been done.

## What each piece is for

| Package | Version | Why it exists on Mali |
| --- | --- | --- |
| `mesa-vulkan-icd-panvk-kbase` | 26.3.1 | The Vulkan driver itself, for Bionic and glibc programs |
| `mesa` | 26.2.6-103 | Zink, with three patches that each cover one consequence of the driver having no SYNC_FD semaphores (below), and the vtest socket lock |
| `android-vaapi` | 27.0.0~devel20261029-5 | The VA-API driver: decoded frames in ION dma-bufs so browsers can import them (3), its own Gallium driver variable (4), the HEVC reorder count (5) |
| `android-vaapi-glibc` | 27.0.0~devel20261025-1 | The same bridge, patches and ION surfaces built for glibc, for Chrome. Selected on Mali only; Adreno keeps the prebuilt Turnip stack beside it |
| `android-firefox-video` | 9.0.2-2 | Firefox's graphics probe accepts Zink on PanVK with `/dev/mali0`, and its VA-API FFmpeg |
| `livecd-desktop` | 0.2.0-17 | The launcher (`src/native/acceleration.py`, `graphics.py`) that picks all of the above by device |

The three Zink patches are not duplicates of one another. PanVK's kbase backend advertises the
external semaphore extensions but cannot create a SYNC_FD semaphore:

| Patch | What goes wrong without it |
| --- | --- |
| `0021-zink-check-native-fence-handle-support` | Zink advertised native fences from the extension names alone; GNOME Shell logged a semaphore error for every frame |
| `0022-zink-reject-unsynchronized-dmabuf-export` | Exporting a texture as a dma-buf with no way to synchronise it; Ghostty crashed. With the patch it falls back to its CPU readback |
| `0023-zink-skip-missing-dmabuf-fence-semaphores` | Importing a dma-buf read one semaphore per plane from an empty array; Firefox crashed on its first hardware-decoded frame |

All three do nothing on a driver that has working SYNC_FD semaphores, such as Turnip.

## JimVulkan/mali-panvk: tested, not adopted

[JimVulkan/mali-panvk](https://github.com/JimVulkan/mali-panvk) is an independent port of PanVK
to kbase (Mesa 27.0.0-devel, lists the S20's G77 as tested). The question was whether to move all
of the above onto it, and which of our patches it would make unnecessary. Its v1.6.0 release
driver (commit `58f2c55`, SHA-256 `80acd461bdf07f5fb99af5c7f516e272103340b6775c22dcd347a6d418c7ac0d`)
was staged privately on the S20 and run from Termux beside the packaged driver.

| Check on the S20 | Packaged (Zenith 26.3.1) | JimVulkan v1.6.0 |
| --- | --- | --- |
| Loads from Termux and creates the device | yes, Vulkan 1.3 | yes, Vulkan 1.4 |
| SYNC_FD and OPAQUE_FD semaphores | neither importable nor exportable; creating one fails | importable, exportable, and creation succeeds |
| `VK_KHR_swapchain`, X11 surfaces | yes: MIT-SHM, and raw DRI3 | none. The instance offers only a headless surface and the device has no swapchain |
| Exporting memory as a dma-buf | yes, ION-backed | no: `kbase_kmod_bo_export` is "not implemented" in its source |
| glibc build, for Chrome | released by upstream | none; the driver links Android platform libraries |
| OpenGL through Zink (surfaceless) | 4.2 | 4.2 |
| `maxComputeWorkGroupInvocations` | 512 | 512 |

So it is not a replacement today:

- **It cannot put a picture on the X server.** It presents through Android's own window system
  only. The desktop, Ghostty and all three browsers present to X11, so each would first need a
  new presentation path written for this driver, and Chrome a glibc port of it. Zenith's port
  already has both, and they are what the 30/30 desktop validation and the browser checks ran on.
- **It does not lift Ghostty's limit.** OpenGL 4.3 needs 1024 invocations per compute workgroup;
  both drivers report the GPU's 512. The large-workgroup compiler pass would have to be carried
  on either.
- **What it would remove is small.** Working SYNC_FD semaphores would turn Mesa patches 0021 to
  0023 into no-ops. They are 30 lines or fewer each and are needed for as long as the packaged
  driver is.

Its sync-file mechanism can be ported into the packaged driver instead
([PANVK-SYNC-FD-HANDOFF.md](PANVK-SYNC-FD-HANDOFF.md)). The driver as a whole is worth
revisiting if it gains an X11 surface or dma-buf export, or for its hardware-buffer import:
that could let decoded frames reach the GPU without the copy the software surfaces make today.
Two things to know before trying it again: from v1.6.0 it names the device `PanVK-G77`, not
`Mali-G77`, and both Zenith's probes and Firefox's probe patch (`android-firefox-video/stage.py`)
look for `Mali` in that name.

To repeat the comparison (the driver is a release download; nothing is installed):

```sh
L=~/gpu-x1s/jim/android/lib/libvulkan_panfrost.so        # from mali-panvk-27.0.0-devel-r10.zip
~/gpu-x1s/panvk/probes/sync-fd "$L"                      # built by .github/workflows/panvk-probes.yml
VK_DRIVER_FILES=~/gpu-x1s/jim/android/icd.json vulkaninfo
VK_DRIVER_FILES=~/gpu-x1s/jim/android/icd.json GALLIUM_DRIVER=zink \
  MESA_LOADER_DRIVER_OVERRIDE=zink EGL_PLATFORM=surfaceless eglinfo -B
```

Raw output: local `temp/gpu-x1s/jim-eval/`.

## What was consolidated

| Branch | What it carried | Now |
| --- | --- | --- |
| `research/panvk-g77-workgroups` (PR 11) and `research/panvk-kbase-probes` | Probe and driver rebuild workflows, the experimental large-workgroup driver, Mesa patch 0022, the Ghostty readback result | merged |
| `fix/zink-dmabuf-without-sync-fd` | Mesa patch 0023, Mesa revision 103 | merged |
| `fix/vaapi-own-gallium-driver` | `android-vaapi` revision 4 | merged |
| `feat/firefox-mali-video` | Firefox probe for Mali, launcher wiring, `android-firefox-video` 9.0.2-1 | merged |
| `fix/exynos-hevc-latency` | `android-vaapi` revision 5, HEVC in Firefox, `android-firefox-video` 9.0.2-2 | merged |
| `feat/browser-mali-video` (was local only) | `android-vaapi-glibc` revision 1 built from source for Mali, launcher selection, CI artifact check | merged, and compiled for the first time |

Fixed while merging:

- `feat/browser-mali-video` deleted the lock file Bionilux's recipe linked to. Staging copies
  every recipe, so that dangling link failed every package build. Bionilux now reads the shared
  sysroot lock, and a packaging test fails on any dangling link under `packages/`.
- The glibc driver had never been compiled. Getting it through CI took four fixes: the
  builder's meson, linker flags kept off the compiler command, Debian's `/lib` link in the
  sysroot, and X11 as its only platform.
- Chromium and Chrome fell back to software for HEVC. The reorder setting that fixed Firefox
  fixes them too, so the launcher now applies it to every VA-API client on Mali.
- The glibc driver applied a fixed list of bridge patches and missed the HEVC one; it now
  applies every `01xx` patch of the Bionic recipe.
- `tools/panvk-probes/va-glibc.sh` and its CI job, the research build the glibc package
  replaced, are removed. The script could no longer run against the current recipe.
- `tests/browsers/test-acceleration.py` required Turnip on every phone; it now expects the
  driver the launcher selected.

## What is left

In order of value. None of it needs a different driver.

1. **Chrome's VP9 frame comparison.** Hardware decode works, but one of four compositor
   comparisons misses the SSIM threshold by 0.0013, the same through the installed launcher
   ([X1S-BROWSER-VERIFICATION.md](X1S-BROWSER-VERIFICATION.md)).
2. **H.264 decoding**, off on every phone and every browser: the bridge rebuilds the PPS with a
   guessed reference count ([X1S-FIREFOX-VIDEO.md](X1S-FIREFOX-VIDEO.md), item 2).
3. **Browser encoding.** WebRTC works in Chromium behind a feature flag; WebCodecs aborts the
   GPU process inside Chromium, so the flag stays off until our Chromium is patched
   ([ENCODING.md](ENCODING.md)). Chrome's WebRTC has no network under Bionilux. Firefox's
   encoder is untested. [VIDEO-ENCODING-HANDOFF.md](VIDEO-ENCODING-HANDOFF.md) has the causes
   and the order to take them in.
4. **Ghostty on the GPU by default.** Needs the large-workgroup pass qualified beyond the tested
   shapes and packaged ([GHOSTTY-PANVK-HANDOFF.md](GHOSTTY-PANVK-HANDOFF.md)). The work is laid
   out in [PANVK-VERSION-BUMP-HANDOFF.md](PANVK-VERSION-BUMP-HANDOFF.md) (OpenGL 4.3, and
   Vulkan 1.4) and [PANVK-SYNC-FD-HANDOFF.md](PANVK-SYNC-FD-HANDOFF.md) (sync-file semaphores,
   for presenting its frame as a DMA-BUF).
5. **mpv on the shared driver**, replacing its VirGL route.
6. The 30-minute desktop soak, and an Adreno regression run of the Firefox and Chromium tests
   with these packages on the Note10+.

## Verification

Two rounds on the S20, both on private displays with private codec daemons.

### Installed, 2026-11-13

The five packages built from `main` (run 43414277233) were installed through the phone's local
APT repository with the desktop stopped, and the desktop was started again: `mesa` 26.2.6-103,
`android-vaapi` 27.0.0~devel20261029-5, `android-vaapi-glibc` 27.0.0~devel20261025-1,
`android-firefox-video` 9.0.2-2, `livecd-desktop` 0.2.0-17. `apt` upgraded those five and
nothing else.

| Check, through what is installed | Result |
| --- | --- |
| `livecd validate` on the restarted desktop (Zink on PanVK) | 30 of 30, twice |
| Chromium VP9, `chromium-browser` | pass: `VaapiVideoDecoder`, 196 frames out of the hardware decoder, 4 of 4 frame comparisons |
| Chromium HEVC, `chromium-browser` | pass: 199 frames out of `OMX.Exynos.hevc.dec`, 4 of 4 |
| Chrome VP9, `google-chrome` | hardware decode works (196 frames out), **fails acceptance**: 3 of 4; the windowed compositor capture scores SSIM 0.8987 against 0.90 |
| Chrome HEVC, `google-chrome` | pass: 198 frames out of the hardware decoder, 4 of 4 |
| Firefox VP9, `tests/browsers/test-acceleration.py firefox` | pass: WebRender, VA-API, 65 frames out of the hardware decoder, PSNR 48.0 dB, SSIM 0.971, Firefox's GPU processes on PanVK |
| Firefox HEVC, same test | pass: 69 frames out of the hardware decoder, PSNR 48.1 dB, SSIM 0.971 |

This was the maintained Firefox test's first run on Mali. The first start after the install
reported the resources integration unavailable, because `android-procfs-setup` timed out waiting
for Shizuku; run by hand it took under a second, and a second start reported it staged. That
package was not changed.

The phone's copy of the video fixtures held 5 of each clip's 48 reference frames, and the
Firefox test compares whichever frame it captures. The missing frames were regenerated on the PC
with the recorded FFmpeg command; all 48 match the manifest's hashes.

### Before installing, 2026-11-12 and 13

The same packages extracted privately, with the launcher code on `main` pointed at them as its
stack root.

| Check | Result |
| --- | --- |
| GNOME Shell and GTK on Zink over PanVK with Mesa 26.2.6-103 | pass: 4 captures over 2 resize and fullscreen cycles, maximum channel error 0, stale-frame control rejected; Shell and GTK map this Mesa and the PanVK driver; Nautilus and Settings inspected |
| Chromium VP9 | pass: 200 frames out of the hardware decoder, 4 of 4 |
| Chromium HEVC | pass: 198 frames out, 4 of 4. Control without the reorder variable: `vaEndPicture failed`, software fallback |
| Chrome VP9 | hardware decode works (192 frames out), fails acceptance on the same comparison: SSIM 0.8987 |
| Chrome HEVC | pass: 190 frames out, 4 of 4 |
| Firefox HEVC on Zink over PanVK, with a concurrent WebGL canvas | pass: 370 frames out of the hardware decoder, frames 12 and 36 correct at the browser and compositor layers, 466 WebGL frames with none wrong |

In both rounds every run's before and after comparison of the live desktop, X server and codec
daemon passed. The Chromium and Chrome comparisons are numbered frames 12 and 36, each at the
browser and the compositor layer, with the unchanged thresholds (PSNR ≥ 28 dB, SSIM ≥ 0.90).
Captures were opened and looked at, not only scored. Each browser run was two fullscreen
cycles: enough to show the path works, not a soak.

Not run: Ghostty, encoding, H.264, a long soak, and the Note10+ (Adreno).

Raw results: local `temp/gpu-x1s/unify/` and `temp/gpu-x1s/unify-install/results/`. On the
phone, the previous repository index and package list are in
`~/gpu-x1s/unify/backup-20261113/`.
