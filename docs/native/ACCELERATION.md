# Shared GPU rendering and hardware video

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

The desktop's existing Turnip/Zink renderer remains the common native GPU layer.
The shared application launcher adds video support through ABI-specific private
drivers and the existing Termux:VA MediaCodec daemon. Native Termux libraries
remain separate from glibc libraries.

[Hardware encoding](ENCODING.md) offers the same stack's H.264 and HEVC encoders
to every desktop program as `/dev/dri/renderD128`, without per-program settings.
The Browser and Video Player overlays install it with the `android-vaapi` package.

Installation and successful compilation do not establish correct pixels, smooth
playback, or hardware decoding in a particular application. The
[fixes and checks](../browsers/native-acceleration-checks.md) pass Firefox
VP9/HEVC and mpv VP9/H.264/HEVC hardware decoding, GPU process checks and numbered-frame
pixel comparisons. Chromium is this repository's package built with VA-API.
The earlier fullscreen frame-freshness failure remains unresolved.

## Applications

| Application | GPU configuration | Video configuration |
| --- | --- | --- |
| Google Chrome | Shared glibc Turnip and ANGLE Vulkan | Shared glibc Termux:VA driver and ION adapter from `android-vaapi-glibc`; VP9/HEVC on by default |
| Native Firefox | Turnip/Zink and WebRender; KGSL graphics probe from `android-firefox-video` | Private VA-API FFmpeg libraries from the same package; the earlier development build passed VP9/HEVC GPU and pixel checks |
| Native Chromium | Existing Vulkan/ANGLE support | This repository's `chromium` package, built with VA-API; enabled when the installed package carries its VA-API build receipt |
| Native mpv | Vulkan `gpu-next` / `x11vk` | VP9/H.264/HEVC hardware decoding and pixel checks pass through native MediaCodec |
| Other applications | Inherited native rendering, or an explicit glibc profile | Standard VA-API available through the shared launcher when the application includes a compatible backend |

Chrome and the managed Firefox/mpv launchers use the shared module on their next
launch. Chromium's existing Termux launcher loads the common configuration from
`$PREFIX/etc/chromium/livecd-gpu.conf`, preserving its normal user flag overrides.
Applications already running must be fully quit and reopened to load new drivers
and preferences. No desktop restart is performed by this setup.

## Commands and overrides

```sh
# Read installation metadata; this does not launch a driver or decode a frame.
livecd-accelerate status

# Supply VA-API to a native client. The client still selects its decode backend.
livecd-accelerate run -- your-vaapi-application arguments

# A glibc client uses Bionilux and the separate glibc driver stack.
livecd-accelerate run --abi glibc -- /path/to/glibc-application arguments

# Keep GPU rendering and force software decoding for this launch.
livecd-accelerate run --profile mpv --video off -- mpv video.mp4
```

`~/.config/livecd-native/acceleration.json` stores `hardware_video` and
`disabled_va_codecs`. Without the file, hardware video is on. `LIVECD_HARDWARE_VIDEO=0` or `1` overrides the saved common
preference. Existing browser controls (`LIVECD_CHROME_HARDWARE_VIDEO`,
`LIVECD_CHROMIUM_HARDWARE_VIDEO`, `LIVECD_FIREFOX_HARDWARE_VIDEO`) take precedence
over that common variable. Chrome also retains its earlier saved opt-in.
`--video off/on` explicitly overrides those choices for a direct launcher call.

`LIVECD_CHROME_GPU`, `LIVECD_CHROMIUM_GPU`, `LIVECD_FIREFOX_GPU`,
`LIVECD_MPV_GPU`, and `LIVECD_GENERIC_GPU` select a per-application GPU override.
Automatic GPU selection follows the native renderer and checks the fullscreen-fix
receipt. Software rendering remains available through the existing desktop mode.

The conservative VA-API profile hides H.264, whose bridge path has an unresolved
stream failure, and AV1, which this phone cannot decode in hardware. Native mpv's
direct MediaCodec route is separate and can use H.264. Codec availability still
depends on the phone and stream.

Only the managed Firefox profile's marked block in `user.js` is updated;
surrounding preferences are preserved. Explicitly supplied Firefox profiles keep
their own settings. User mpv configuration remains in place, with the launcher's
GPU/decode options passed on the command line.

## Driver and daemon ownership

The packaged stacks are `$PREFIX/lib/android-vaapi` (Bionic) and
`$PREFIX/lib/android-vaapi-glibc` (glibc). A development stack selected under
`~/.local/opt/livecd-native/acceleration/`, through its `bionic` or `glibc`
selector, takes precedence. A launcher resolves its selector to an
immutable directory before starting a process. Updates therefore keep an
application on one driver version for its lifetime.

The existing daemon can serve both ABIs through its socket. When a caller supplies
`TERMUX_VA_SOCKET` or `TERMUX_VA_SOCKET_DIR`, the launcher respects its ownership.
Otherwise startup is serialized, reuses a listening endpoint, and starts the
daemon directly if absent. It never invokes upstream's process-wide kill helpers
or runs a decode health probe. There is no global video preload on GNOME Shell.

The Browser overlay also installs `android-firefox-video`. Its Mozilla graphics
probe port and VA-API FFmpeg decoder libraries live under
`$PREFIX/lib/android-firefox-video`; Firefox no longer requires a home-directory
build. The launcher verifies that the package matches the installed Firefox
loader and application.ini before using it. A newer or rebuilt Firefox can start
normally with software decoding and a diagnostic until the matching video
package is rebuilt. The optional development `firefox` / `firefox-ffmpeg` pair
under the acceleration directory remains supported when complete and compatible.

The Bionic `android-vaapi` stack also supplies private `libva.so.2` and
`libva-drm.so.2` aliases. Chromium explicitly dlopens those desktop ABI names;
Termux's native libva package uses unversioned filenames. The aliases refer to
the same native libraries and are searched through the application's environment.

The packages are built in CI from [packages/](../../packages/). Instructions for building
a development stack on the phone are in [prebuilt/native-video](../../prebuilt/native-video/README.md).
The upstream design and application settings are documented in the
[Termux:VA developer guide](https://github.com/lfdevs/termux-va/blob/main/doc/developer-guide.md)
and [user guide](https://github.com/lfdevs/termux-va/blob/main/doc/user-guide.md).
