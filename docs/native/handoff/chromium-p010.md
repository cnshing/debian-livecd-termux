# Handoff: Chromium and Chrome show 10-bit (P010) video black

State on 2026-11-18, Note10+ (Adreno 640). Context: [ADRENO-640-PARITY.md](../ADRENO-640-PARITY.md),
"10-bit decoding". Until this is fixed the launcher keeps Chromium and Chrome on software 10-bit
(`TERMUX_VA_DISABLE_10BIT=1` in `prepare()`, `src/native/acceleration.py`); Firefox and native
programs decode and show 10-bit in hardware.

## What happens

With `TERMUX_VA_DISABLE_10BIT=0`, Chromium 156 (`VaapiVideoDecoder`) decodes HEVC Main10 and VP9
profile 2 in hardware: the daemon logs P010 sessions and the frames are right (FFmpeg reads the same
surfaces bit-exact). The page and the compositor show black. Chromium's GPU process logs, once per
frame, `skia_output_surface_impl.cc: Failed to create the promise sk image` and
`skia_renderer.cc: Failed to create the promise sk image or get paint ops`. The 8-bit (NV12) run of the
same build logs neither. The `zink: failed drmPrimeFDToHandle` lines appear in both and are unrelated.
Chrome (prebuilt, glibc Turnip from lfdevs) fails the pixel check the same way.

## Cause, part 1: Turnip had no P010 formats (fixed by a patch, not shipped)

Turnip 26.2.6 and upstream main advertise no `VK_FORMAT_G10X6_B10X6R10X6_2PLANE_420_UNORM_3PACK16`,
`VK_FORMAT_R10X6_UNORM_PACK16` or `VK_FORMAT_R10X6G10X6_UNORM_2PACK16`, so Skia has no Vulkan format
for a P010 frame. The a6xx hardware has `FMT6_P010` (0x9a, `a6xx_enums.xml`), and the 16-bit plane
formats share P010's memory layout. [`note10-p010/turnip-p010.diff`](note10-p010/turnip-p010.diff)
(against Mesa 26.2.6 with `packages/mesa`'s patches) maps the two-plane format to `FMT6_P010`, the
planes to `FMT6_16_UNORM`/`FMT6_16_16_UNORM`, adds it to the plane-address descriptor path next to
NV12 (`fd6_view.cc`), and keeps all three linear-only (`tiling_possible()`), which is what imported
frames need. Built (Turnip only, NDK cross-build) and checked: vulkaninfo on the phone lists the three
formats with linear sampled/filter/transfer features. It is not in `packages/mesa`: Termux applies
every `.patch` file in a recipe, and on its own it does not fix Chromium.

## Cause, part 2: Chromium still refuses the P010 shared image (open)

With the patched Turnip selected (`VK_ICD_FILENAMES`), Chromium still logs the promise-image failure
and shows black. Next steps, in order:

1. Read Chromium 156's `OzoneImageBacking` Skia/Vulkan representation and
   `shared_image_format_service_utils.cc` (`ToVkFormat*`) for P010 (`SharedImageFormat` multiplanar
   P010 or legacy `kP010`). Check whether it maps P010 to the two-plane format with a
   `VkSamplerYcbcrConversion`, or per plane to `R16`/`RG16`, and which check fails. Run with
   `--vmodule=ozone_image_backing=3,skia_vk_ozone_image_representation=3,vulkan_image*=3`.
2. If it is a Chromium-side gap, patch `packages/chromium` (stack after the current chain: one
   Chromium CI chain at a time), or make the bridge export P010 in the form Chromium accepts.
3. Ship the Turnip patch together with the fix, then drop `TERMUX_VA_DISABLE_10BIT` for Chromium in
   `prepare()`, and verify with `tests/browsers/test-fullscreen.py chromium --require-hardware-decode
   --private-daemon --media-dir fixtures-10bit` (fixtures from
   `tests/browsers/make-video-fixtures.py --ten-bit`). Chrome uses its own prebuilt glibc Turnip
   (`android-vaapi-glibc`), so it also needs that Mesa rebuilt with the patch.
