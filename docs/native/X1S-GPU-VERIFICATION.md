# Native Termux GPU investigation: x1s / Exynos 990

**Hardware rendering works without ANGLE or PRoot on the tested SM-G981B.**
Two paths passed real window tests: Vulkan through a private Android ICD/WSI
wrapper, and Mesa virpipe through Android's proprietary GLES driver.
Current Zink did not initialize. The managed GNOME desktop remains in software
mode; this investigation establishes per-application acceleration, not an
accelerated GNOME session. Subsequent numbered-frame tests passed mpv GPU
rendering with hardware VP9/H.264/HEVC decoding; browser qualification remains
unresolved. Firefox workload testing is paused at the user's request.

Raw logs and screenshots are local under `temp/gpu-x1s/`, excluded from Git.
See [privacy notes](../privacy.md). These results are specific to this firmware.

## Device and inputs

- Samsung Galaxy S20 5G, SM-G981B / x1s, Exynos 990, Android 13.
- GPU queried from the driver: **Mali-G77**, ARM proprietary r38p1 driver,
  `driverVersion=38.1.0`, device Vulkan **1.1.213**.
- Native Termux 0.118.3, standard Bionic prefix, Mesa **26.2.6**,
  generic Vulkan loader **1.4.368**, existing Termux:X11 display `:0`.
- Privately extracted official packages: vulkan-tools **1.4.368**,
  virglrenderer-android **1.3.0-1**, glmark2 **2023.01-4**.
- Private ICD/WSI adapter from
  [ar37-rs/virgl-angle's release](https://github.com/ar37-rs/virgl-angle/releases/tag/latest):
  `mesa-vulkan-icd-wrapper_25.0.0-1_aarch64.deb`, SHA-256
  `c028d0cfa8ba536728dc19f080371e901c5b4888ee754434d7d7fae554f1ef51`.
  The mutable release URL must be checked against this hash to reproduce this test.

The adapter provides a desktop Vulkan ICD and X11 presentation around Android's
driver. It is not ANGLE and does not translate OpenGL to Vulkan. Vulkan applications
still use Samsung's installed GPU driver. Its `libGLES_mali.so` name also appears
in Vulkan processes because Samsung shares the implementation library.

Initial tests used private extraction only. Follow-up installed the official
`virglrenderer-android` package and its `angle-android` dependency. The installed
ANGLE dependency is not selected in any accepted path. Following the user's
latest instruction, the diagnostic launcher offers no ANGLE fallback. Process maps confirmed system EGL/Mali rather
than ANGLE. No root, kernel replacement or device-permission changes were used.
An independent query loading `/system/lib64/libvulkan.so` directly also returned
device API 1.1.213, with both Vulkan 1.1 and 1.3 instance requests. The reported
device limit is therefore not just an artifact of the private wrapper.

## Results

| Path / check | Observation |
| --- | --- |
| Baseline GL/Vulkan | llvmpipe, CPU device, `Accelerated: no` |
| Vulkan + private ICD adapter | Mali-G77, integrated GPU, Vulkan 1.1.213 |
| `vkcube --wsi xcb` | Visible rotating textured cube; remained alive through subsequent application tests |
| Vulkan process evidence | Private wrapper, vendor Vulkan HAL and Mali implementation mapped; open `/dev/mali0`; no ANGLE maps |
| Zink + wrapper, GLX | Failed to create drisw screen / load Zink; no RGB GLX visual or fbconfig |
| Zink + wrapper, EGL | All queried platforms failed `eglInitialize` |
| Native virpipe → Android GLES | `virgl (Mali-G77)`, `Accelerated: yes`, desktop GL 2.1 / GLSL 1.20, GLES 3.1 |
| Native GLX gears | Visible animation, alive for 60-second sample; twelve intervals spanning 221–258 FPS |
| Native GLES gears | Alive for 20-second sample; four intervals spanning 217–242 FPS |
| glmark2 GLES texture / shading | Both scenes completed and visible; initial 300×300 eight-second scenes: 230 / 206 FPS |
| GTK4 | Animated label and button visible; application reported `GskGLRenderer` |
| mpv direct Vulkan `gpu-next` | Failed: libplacebo excluded Mali due to too low an API version; audio-only continuation is not a video pass |
| mpv VirGL `gpu` / `x11egl`, initial desktop-GL attempt | Visible but extremely slow; superseded by the explicit GLES route below |
| mpv `gpu-next` / `x11egl` / explicit GLES | VP9/H.264/HEVC hardware MediaCodec decoding and strict numbered-frame pixel checks passed |
| Launcher verification | Vulkan query, native VirGL GL query and texture/shading scenes passed through the supplied launcher; its private server group was cleaned up after exit |

The server's actual rendering children mapped `/system/lib64/libEGL.so` and
`/vendor/lib64/egl/libGLES_mali.so` and held `/dev/mali0`. The client uses the
socket rather than opening the GPU itself. This is native Bionic client/server
rendering, with no PRoot requirement.

For context, the same two glmark2 software scenes gave 236 / 69 FPS. A second
VirGL run through the launcher gave 213 / 190 FPS. These short samples used a
300×300 window and the existing software compositor, with changing concurrent
load. They show that benefit depends on workload; they are not a controlled
whole-desktop speedup measurement. The two-scene scores are not comparable to
the linked guides' full-suite scores. Gears FPS is not a game benchmark.

VirGL logged fence-export failures (`err=-9`) despite visible frames. The
texture/shading tests and GTK window did not reproduce the other Mali guide's
fatal texture initialization errors. Rendering success does not prove working
explicit synchronization for every application.

## Why the other routes were not selected

The device exposes `/dev/mali0`, but no `/dev/dri` render node. Termux's current
[Mesa recipe](https://github.com/termux/termux-packages/blob/master/packages/mesa/build.sh)
builds Zink/virgl/software Gallium drivers and software/virtio/Freedreno Vulkan
drivers, not PanVK. The current
[Panfrost support table](https://docs.mesa3d.org/drivers/panfrost.html) does not
list G77. There is no packaged, supported PanVK route established here for
Samsung's existing kernel interface. Rooting alone would not supply one.

The Vulkan dump lacks `VK_KHR_dynamic_rendering`, `VK_KHR_maintenance5`, both
robustness2 extensions and `VK_EXT_border_color_swizzle`, which appear in current
[Zink minimum requirements](https://docs.mesa3d.org/drivers/zink.html).
This capability mismatch supports the failed initialization result. Vulkan
1.1 alone is not sufficient evidence that current Zink will work. An older Mesa
build or a different wrapper could behave differently; those were not validated.
No GL/GLSL version overrides were used to claim unsupported features.

The [DeadKnox native guide](https://github.com/DeadKnox/Termux-Desktops/blob/main/Documentation/termux-native-desktop.md)
documents llvmpipe for Mali and incorrectly treats VirGL as requiring PRoot.
This device's native socket-client tests show otherwise.
[Theguilherm3's guide](https://github.com/Theguilherm3/termux-mali-gpu-acceleration)
documents a different Mali device using VirGL → ANGLE → Vulkan. That is a
different route; it is excluded from further work by the user's instruction. The supplied
[S20 issue](https://github.com/LinuxDroidMaster/Termux-Desktops/issues/68) and
[Reddit discussion](https://www.reddit.com/r/termux/comments/1rle12y/s20_exynos_990_cyberdeck_build_should_i_root_for/)
were read as context, not substituted for local hardware tests.

## Reproduce and use per application

Run preparation in native Termux. This extracts files privately instead of
installing a competing loader or removing the software ICD:

```sh
mkdir -p ~/gpu-x1s/packages ~/gpu-x1s/root
cd ~/gpu-x1s/packages
apt download vulkan-tools virglrenderer-android glmark2
curl -fL https://github.com/ar37-rs/virgl-angle/releases/download/latest/mesa-vulkan-icd-wrapper_25.0.0-1_aarch64.deb -o wrapper.deb
echo 'c028d0cfa8ba536728dc19f080371e901c5b4888ee754434d7d7fae554f1ef51  wrapper.deb' | sha256sum -c -
# Continue only after the hash check succeeds.
for deb in *.deb; do dpkg-deb -x "$deb" ../root; done
```

The official repository is rolling; `apt download` on another installation may
fetch newer versions. Existing Mesa, Python, X11 and Vulkan-loader dependencies
must already be present, as on this rig. This is an experimental staged setup,
not a fresh-device dependency installer.

Copy [tools/x1s-gpu.py](../../tools/x1s-gpu.py) to `~/gpu-x1s/run.py` on the phone.
That copy is already present on the tested device. With Termux:X11 running:

```sh
python ~/gpu-x1s/run.py vulkan vulkaninfo --summary
python ~/gpu-x1s/run.py vulkan vkcube --wsi xcb --width 300 --height 300
python ~/gpu-x1s/run.py virgl glxinfo -B
python ~/gpu-x1s/run.py virgl glxgears -info
python ~/gpu-x1s/run.py virgl glmark2-es2 \
  --data-path ~/gpu-x1s/root/data/data/com.termux/files/usr/share/glmark2 \
  --size 300x300 --benchmark texture:duration=8 --benchmark shading:duration=8
```

`vulkan` selects only the private ICD for one command. `virgl` starts its own
server/socket, clears inherited software and version overrides, selects virpipe
and GTK's GL renderer for the command, then stops its server process group.
The server uses Android GLES; it receives no ANGLE flags or ANGLE library path.
Applications that hand their window to an already-running instance may ignore
the new environment; use a separate application instance for a meaningful test.

The desktop's `software`/`zink` selection was not extended or switched. Whole
GNOME/Mutter acceleration, successful browser compositing/WebGL, newer desktop
GL profiles, reboot/recovery and long thermal testing remain unvalidated.
The existing desktop and shared video daemon remain available.

## Application and video follow-up

The accepted mpv route is explicit GLES, rather than desktop GL or Vulkan:

```sh
python ~/gpu-x1s/run.py virgl mpv --vo=gpu-next --gpu-api=opengl \
  --gpu-context=x11egl --opengl-es=yes --hwdec=mediacodec-copy \
  --vd-lavc-o=ndk_codec=1 video.mp4
```

mpv's bundled libplacebo 7.387.0 requires Vulkan 1.2; this GPU's driver exposes
1.1.213. This explains Vulkan rejection despite a working Vulkan cube. GLES
avoids that API requirement. MediaCodec decoding and surface copies are separate
from GPU rendering; this is hardware decoding with CPU surface transfer, not
zero-copy video.

`src/native/mali.py` owns a separate VirGL server/socket for each qualified mpv
launch and cleans it up on exit. The shared acceleration profile selects it on
native Mali devices with the server installed, even when the desktop is software
rendered. The Video Player overlay installs the server and managed mpv wrapper.
Explicit `LIVECD_MPV_GPU=0` disables rendering acceleration while retaining
hardware decode; `--video off` disables decode independently. Caller mpv flags
remain after defaults and can override them.

The updated profile and managed launcher were applied to this device. The
previous installed acceleration module is backed up under
`~/gpu-x1s/applied-backup/`. The live desktop was not restarted. Source changes
are pending packaging/review; no new desktop package has been installed.

| Application / backend | Acceptance result on x1s |
| --- | --- |
| Native MediaCodec, VP9/H.264/HEVC | All 48 numbered frames in order, pixel comparisons pass, Samsung hardware decoder components |
| mpv, Mali GLES + MediaCodec | All three codecs pass strict rendered frame 12/36 comparisons; installed managed wrapper independently passes VP9 |
| VA-API decode via X11 display | VP9 and H.264: all 48 frame IDs and sampled pixels pass. HEVC stalls after 37 frames and fails completion |
| VA-API H.264 High / HEVC Main encode | 48-frame sequence and sampled pixels pass after explicit BT.709 bitstream metadata correction |
| Encoder daemon control suite | 28 pass, 2 fail: extra unrequested H.264 Baseline IDR frame; do not call this a complete pass |
| Native Chromium, direct Vulkan | Vulkan rasterization works; compositing/decoding remain software. VP9/H.264/HEVC pass corrected browser/compositor pixel checks, fail hardware acceptance |
| Google Chrome | Installed ARM64 Linux Chrome 157 with Bionilux. VP9/H.264 pixels pass, software decoding; HEVC does not advance. No hardware acceptance |
| Firefox | No accepted acceleration pass. Further workload tests skipped; detailed local handoff is `temp/gpu-x1s/FIREFOX-HANDOFF.md` |
| GNOME and other applications | No general acceleration qualification; managed desktop remains software |

The image oracle checks frame IDs, color patches, PSNR >=28 dB and SSIM >=0.90.
VP9/H.264 VA-API decode samples measured about 50 dB and 0.982 SSIM.
Decoder and encoder sequences check IDs 0–47; rendered mpv samples use frames
12/36. Hardware strings alone are insufficient. Application tests used private
X displays and checked that existing desktop/daemon processes survived.

### VA-API details and remaining failures

The Mali device has no DRM render node. X11 VA initialization nevertheless works
with the installed Termux:VA driver (VA API 1.22), a private daemon socket and
`TERMUX_VA_GPU_BACKEND=sw`. Here `sw` selects CPU-backed surfaces; the codecs still
run through Samsung hardware MediaCodec. The launcher avoids Adreno KGSL/dma-buf
settings on native Mali. Explicit generic VA clients select the driver's built
`softpipe` surface renderer instead of inheriting desktop `llvmpipe`.

The stock FFmpeg package lacks VA-API encoders. A locally rebuilt
`ffmpeg_9.0.2-100_aarch64.deb` exposes them and was extracted privately under
`~/gpu-x1s/ffmpeg-vaapi-new/`; it was not installed over live FFmpeg libraries.
VA-API encode tests used `h264_vaapi` and `hevc_vaapi`. Their original streams
lacked sufficient bitstream color metadata and failed the color-patch threshold.
Explicitly adding BT.709 metadata without re-encoding fixes that test:

```sh
# Choose h264_metadata or hevc_metadata for the encoded stream.
ffmpeg -i encoded.mp4 -c copy \
  -bsf:v h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1 \
  corrected.mp4
```

Corrected H.264 samples measured about 42–44 dB and HEVC 43–48 dB, with maximum
color-channel error 1. This correction is explicit in the tested encode path;
it has not been added automatically to every application's encoder. HEVC
VA-API decode stalled at end-of-stream after 37 frames and was terminated by its
specific PID. Direct MediaCodec/mpv HEVC decoding passes separately. H.264/AV1
VA-API defaults remain conservative; successful H.264 tests explicitly opted in.

Raw follow-up evidence on the phone is under `~/gpu-x1s/`: `mpv-integration-*`,
`mpv-installed-vp9/result.json`, `browser-tests/native-mediacodec/`,
`encode-daemon/`, `va-encode/pixel-results-fixed.json`, and
`va-decode/pixel-results.json`. PC-side logs are in `temp/gpu-x1s/`.

GitHub CI run [43026620093](https://github.com/cnshing/debian-livecd-termux/actions/runs/43026620093)
was dispatched for FFmpeg and Chromium using the authorized token. FFmpeg built
successfully; Chromium exceeded the six-hour job limit without producing an
artifact. The installed Chromium already matches an earlier VA-API-enabled CI
build. See the [browser follow-up](X1S-BROWSER-VERIFICATION.md) for final serial
Chrome/Chromium tests and the Moto Pad reference analysis. No browser hardware
acceptance pass is claimed.

