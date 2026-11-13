# debian-livecd-termux

> [!WARNING]
> Everything past this point for the whole project is completely generated with LLMs. Proceed at your own risk!

A port of [debian-livecd](https://github.com/cnshing/debian-livecd)'s GNOME desktop to native
Termux on Android, without PRoot. Tested on an arm64 Note10+ running Android 11.

## Requirements

A fresh arm64 Android phone needs only these apps. The validated setup is an Android 11 Note10+
with the standard `com.termux` prefix; other devices and Android versions need their own validation.

1. **Termux**, **Termux:X11** and **Termux:API**, all from the same source (F-Droid or each
   project's GitHub releases). Android rejects a differently signed mix, because Termux:API
   shares Termux's user ID.
2. **Shizuku** (or Shizuku+), running, with Termux allowed under its authorized applications.
   In Shizuku, choose **Use Shizuku in terminal apps** and export the files to a folder in shared
   storage, such as `Shizuku/`. The installer finds them there.

Everything else is automatic. `install.sh` asks Android for storage access (accept the prompt), and
through Shizuku it grants Termux:API's microphone and camera permissions, which cover Termux, and
exempts Termux from battery optimization.

Before it downloads anything, `install.sh` reports each feature whose app or permission is missing,
with the step that fixes it. Only a missing Termux:X11 stops it; any other feature stays off until
fixed, and the rest of the desktop works. Run `bash debian-livecd-termux/src/preflight.sh` to check
again later, such as after changing a permission in Android Settings, or add `--grant` to grant
through Shizuku again.

| Feature | Needs |
| --- | --- |
| The desktop | Termux:X11 (stops the installation) |
| GPU rendering, hardware video | A Qualcomm Adreno GPU; otherwise software rendering |
| Phone microphone | Termux:API, with its Microphone permission |
| Bluetooth headset microphone | The microphone's permission, Shizuku, and the headset paired with **Calls** enabled |
| Front and rear cameras | Termux:API, with its Camera permission |
| Battery status | Termux:API |
| Internal storage, SD card, USB drives in Files | Termux's storage permission |
| Whole-device CPU and processes in Mission Center | Shizuku |
| The desktop keeps running in the background | Termux exempt from battery optimization |

## Install

In Termux:

```sh
pkg install -y git
git clone https://github.com/cnshing/debian-livecd-termux
bash debian-livecd-termux/install.sh
```

If `pkg` stops at a mirror error, such as `429 Too Many Requests`, run `termux-change-repo`, choose
another mirror group, and run the command again.

The script fetches the compiled packages from this project's latest release into a local apt
repository, installs them and applies the default overlays. To use a release tarball you already
have, run `bash debian-livecd-termux/install.sh --repo-tarball FILE`. Its log is
`~/.local/state/livecd/install.log`.

An offline tarball, `livecd-termux-repo-aarch64-offline.tar.gz`, also carries every Termux package
the installation can need. Given one with `--repo-tarball`, apt installs from it alone and never
contacts a mirror. If a release has it in parts, join them first:
`cat livecd-termux-repo-aarch64-offline.tar.gz.part* > livecd-termux-repo-aarch64-offline.tar.gz`.
Google Chrome is the exception: Google does not allow redistributing it, so the tarball holds only
the Termux packages it needs. An offline install still downloads Chrome from Google when the phone
is online, and otherwise leaves it out and says how to add it later.

Then start the desktop. It opens the Termux:X11 app:

```sh
livecd start
```

`livecd stop` ends it, and `livecd status` reports it. On a Qualcomm GPU, setup installs Mesa's
Turnip driver and the desktop renders through Zink; elsewhere it renders in software.

Firefox, Chromium and Google Chrome are installed with GPU rendering and Android's hardware video
decoding and encoding. Chrome is downloaded from Google during installation, because its license
does not allow this project to redistribute it.

The desktop's Android integrations start with it: the phone microphone, or a connected Bluetooth
headset (pair it in Android with **Calls** enabled), EasyEffects, GSConnect, whole-device CPU and
process readings for Mission Center, battery status, and internal storage, SD card and USB drives
in Files. See [session integrations](docs/native/README.md#session-integrations) to switch one off.

### Optional applications

```sh
apt list '?archive(^livecd$)'   # every package from this project's repository
pkg install mixtapes            # or serein, ...
```

`install.sh` adds this project's packages as an apt repository, so `pkg install` installs the
applications that the default installation leaves out. It works while the desktop runs, unless it would
replace an installed package the desktop may have loaded; then it stops before changing anything and
asks you to run `livecd stop` first. ungoogled Chromium has its own installer; see the
[browser guide](docs/browsers/README.md).

### Feature guides

| Feature | Guide |
| --- | --- |
| GNOME desktop and native applications | [Native desktop](docs/native/README.md#install-and-run) |
| Front and rear cameras as `/dev/video0` and `/dev/video1` | [Cameras](docs/camera/README.md) |
| Phone microphone and Bluetooth headsets | [Microphone](docs/mic/README.md), [Bluetooth limits](docs/mic/BLUETOOTH.md#android-permission-boundary) |
| Whole-device CPU, processes and sensors | [Resource access](docs/resources/README.md) |
| EasyEffects and AutoEq | [Audio effects](docs/audio/README.md), [application routing](docs/audio/README.md#run) |
| GSConnect phone/desktop sync | [GSConnect](docs/gsconnect/README.md); needs a compatible peer on the LAN |
| GPU rendering and hardware video | [Acceleration guide](docs/native/ACCELERATION.md); results vary by application |
| Battery status and health | [Battery backend](docs/battery/README.md#where-the-numbers-come-from) |
| Shared storage and SD card | [Storage](docs/native/STORAGE.md) |

## Layout

| Directory | Holds |
|---|---|
| [`packages/`](packages) | Recipes in termux-packages format: `build.sh` plus `*.patch`. These build the base packages. |
| `repo/` | Compiled packages as a local apt repository. Git-ignored; filled from a release tarball. |
| [`overlays/`](overlays) | Our adjustments on top of the base packages, under upstream's feature names. |
| [`prebuilt/`](prebuilt) | Legacy GNOME bootstrap and specialized GPU/video setup. Normal GNOME installation uses source-built packages. |
| [`src/`](src) | Our own on-device code: the desktop controller and the overlay applier. |
| [`tests/`](tests) | Device tests. |
| [`tools/`](tools) | Build planning, repository generation and the phone rig. |
| [`docs/`](docs) | Public guides and reviewed verification reports. |

Build packages with `bash tools/build-packages.sh PACKAGE`, or add `--install` in native Termux to install the generated `.deb` files. Python helpers used by recipes remain part of the standard package build.

Read [docs/structure.md](docs/structure.md) for how these fit together, how to build one package and
how to add a new one.

[Loupe](docs/loupe/README.md) is the default image viewer, selected by the Image Viewer overlay.

The optional [Serein client package](docs/serein/README.md) carries forward the earlier
microphone probe work into a full native Termux desktop build.

The GNOME recipes in `packages/` carry the source archives and patches of the GNOME 48 source port that passed device acceptance on the phone; the packaged release was then installed and tested on a freshly wiped phone with `install.sh`.

The [shared resource backend](docs/resources/README.md) provides on-demand whole-device
CPU, Android processes and supported sensors to Mission Center and ordinary Linux tools.
Compatible native programs use their usual `/proc` and `/sys` paths, without a background sampler.
[Battery status](docs/battery/README.md) reaches GNOME's panel and Mission Center through UPower.

Local logs, screenshots and session notes are kept under the Git-ignored `temp/`
directory. See [privacy notes](docs/privacy.md) for the cleanup boundary.

## Acknowledgements

This port builds on the work of upstream developers, Termux package maintainers,
Android desktop projects, and contributors who shared patches and investigations.
Thank you to everyone behind the projects and references below.

### Desktop and Termux foundations

| Project or contributor | Contribution to this project |
| --- | --- |
| [debian-livecd](https://github.com/cnshing/debian-livecd) | Original desktop profile, overlay structure, settings and assets. The copied overlay files are recorded in [`overlays/UPSTREAM`](overlays/UPSTREAM). |
| [Termux](https://github.com/termux/termux-app), [termux-packages](https://github.com/termux/termux-packages), [Termux:X11](https://github.com/termux/termux-x11), and [Termux:API](https://github.com/termux/termux-api) | Android userspace, Bionic ports, package builder, graphical display and device APIs. The build checkout is pinned in [`tools/termux-build.json`](tools/termux-build.json). |
| [GNOME](https://www.gnome.org/), [GTK](https://www.gtk.org/), and [SpiderMonkey](https://spidermonkey.dev/) | Shell, Mutter/Cogl, GJS, gnome-session, Nautilus, Autoar, Settings Daemon, LocalSearch, libraries and schemas forming the desktop. See the [GNOME package source notes](packages/gnome-48-runtime/SOURCES.md). |
| [licy183's GNOME Shell PR #24585](https://github.com/termux/termux-packages/pull/24585) and [Termux's GNOME 48 recipes](https://github.com/termux/termux-packages/tree/77ae9db667103a2ea7575c8f23a497754796951a) | Earlier GNOME packaging and Android adaptations underpinning the source-port work, including retained patches and cross-build introspection data. |
| [Gass-OS/GNOME-Termux](https://github.com/Gass-OS/GNOME-Termux) | Earlier native GNOME bootstrap and readable Shell JavaScript adaptations. [`0200-termux-session.patch`](packages/gnome-48-shell/0200-termux-session.patch) derives from its resources at `42a890c…`, rebased and adjusted for this desktop. |
| [JesusChapman's GNOME 49 PR #32883](https://github.com/termux/termux-packages/pull/32883) | Native packaging, service adaptations and Nautilus recipe reference used during migration. This project's core runtime remains GNOME 48. |
| [Md Arif / sabamdarif](https://github.com/sabamdarif) | Retained Nautilus Android patches, including `getpwent` and compiler-warning changes, plus the [gnome-in-termux](https://github.com/sabamdarif/gnome-in-termux) startup reference. |
| [Debian](https://www.debian.org/) and its maintainers | Source archives, portable GNOME extension/font packages, library inputs for the glibc browser stack, and the earlier Debian/PRoot desktop. |

### Graphics, browsers and media

| Project or contributor | Contribution to this project |
| --- | --- |
| [lfdevs/Termux:VA](https://github.com/lfdevs/termux-va) | MediaCodec daemon and VA-API transport on which the experimental hardware-video integration and encoder extensions build. The [maintainer's explanation in issue #1](https://github.com/lfdevs/termux-va/issues/1#issuecomment-6488523619) also informed the native FFmpeg investigation. |
| [lfdevs/Mesa for Android Container](https://github.com/lfdevs/mesa-for-android-container) | Android-container Mesa sources and glibc graphics artifacts used in the browser GPU/video work. |
| [zenithblue-oss/panvk-kbase-android](https://github.com/zenithblue-oss/panvk-kbase-android) and [JimVulkan/mali-panvk](https://github.com/JimVulkan/mali-panvk) | Ports of Mesa's PanVK Vulkan driver to Mali GPUs on Android's stock `mali_kbase` kernel driver. Zenith's release is what `mesa-vulkan-icd-panvk-kbase` packages for the Galaxy S20's Mali-G77 desktop, browser and Firefox video work; JimVulkan's independent port was suggested as a reference for external semaphores and Android hardware-buffer import. |
| [Mesa](https://www.mesa3d.org/), [Freedreno/Turnip](https://docs.mesa3d.org/drivers/freedreno.html), [Panfrost/PanVK](https://docs.mesa3d.org/drivers/panfrost.html), and [Zink](https://docs.mesa3d.org/drivers/zink.html) | Native and glibc GPU rendering, Vulkan/OpenGL drivers and software fallbacks. Termux supplies the packaged native drivers and port patches. |
| [zenithblue-oss/panvk-kbase-android](https://github.com/zenithblue-oss/panvk-kbase-android) | PanVK ported to the Mali kbase kernel driver (`/dev/mali0`). Its Android and glibc release builds are packaged as [`mesa-vulkan-icd-panvk-kbase`](packages/mesa-vulkan-icd-panvk-kbase/build.sh) for Mali GPU acceleration, and its probes and sources guided the x1s (Galaxy S20) investigation. |
| [soulexit/panvk-kirin990](https://github.com/soulexit/panvk-kirin990) | MIT-licensed large-workgroup compiler patches 0012, 0044 and 0061, adapted from commit `c024c056ac2426acead6a8741ccc38081964fddb` for the experimental Mali-G77 Ghostty rendering work. The experiment remains separate from general Vulkan/OpenGL qualification. |
| [Khronos Vulkan Headers](https://github.com/KhronosGroup/Vulkan-Headers), [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools), and [glslang](https://github.com/KhronosGroup/glslang) | API headers, shader compilation and SPIR-V validation used by the PanVK compute and rendering probes. |
| [zenithblue-oss/PanPlay](https://github.com/zenithblue-oss/panplay) and [PanProbe](https://github.com/zenithblue-oss/panprobe) | Companion applications, probe results and release references used in the PanVK investigation. |
| [Khronos Vulkan Profiles](https://github.com/KhronosGroup/Vulkan-Profiles), [VK-GL-CTS](https://github.com/KhronosGroup/VK-GL-CTS), and the [Vulkan](https://docs.vulkan.org/) and [OpenGL specifications](https://registry.khronos.org/OpenGL/specs/gl/glspec43.core.pdf) | Capability requirements and conformance references used to assess the Vulkan-to-OpenGL feature gap. |
| [theonuverse/Bionilux](https://github.com/theonuverse/bionilux) and [termux-pacman/glibc-packages](https://github.com/termux-pacman/glibc-packages) | glibc program launching and compatibility-package references for running Chrome alongside Bionic applications. |
| [libva](https://github.com/intel/libva), [FFmpeg](https://github.com/FFmpeg/FFmpeg), [GStreamer](https://gstreamer.freedesktop.org/), and [PipeWire](https://pipewire.org/) | Video APIs, codec implementations, media pipelines, camera experiments and audio transport. |
| [Chromium](https://www.chromium.org/), [ANGLE](https://chromium.googlesource.com/angle/angle), [Firefox](https://github.com/mozilla-firefox/firefox), [chromium-linux-tarballs](https://github.com/chromium-linux-tarballs/chromium-tarballs), and [ungoogled-chromium-portablelinux](https://github.com/ungoogled-software/ungoogled-chromium-portablelinux) | Browser sources, source archives and the optional portable Chromium input. ANGLE's Vulkan back end gives both browsers GPU compositing and WebGL on Mali. Thanks also to licy183 and the Termux Chromium maintainers for the recipe and Android patches retained by this build. |
| [Android Open Source Project](https://source.android.com/), [Android NDK](https://developer.android.com/ndk), and [scrcpy](https://github.com/Genymobile/scrcpy) | Camera, Binder, Bluetooth, shared-memory, buffer-allocation and MediaCodec source/API references. The camera investigation also consulted [scrcpy PR #4213](https://github.com/Genymobile/scrcpy/pull/4213). |
| [Termux's libandroid-stub](https://github.com/termux/termux-packages/tree/master/packages/libandroid-stub) and [Capstone](https://www.capstone-engine.org/) | libandroid-stub's namespace forwarders let Termux programs reach Android's NDK libraries; understanding how they load a second libbinder led to the [Galaxy S20 camera fix](docs/camera/README.md#tested-phones). Capstone disassembled Android's libbinder to locate the Parcel abort in that investigation. |

Exact GPU/video inputs are pinned in the [android-vaapi](packages/android-vaapi/build.sh),
[android-vaapi-glibc](packages/android-vaapi-glibc/build.sh), [mesa-vulkan-icd-panvk-kbase](packages/mesa-vulkan-icd-panvk-kbase/build.sh), [termux-va](packages/termux-va/build.sh)
and [bionilux](packages/bionilux/build.sh) recipes; see also the [browser integration report](docs/browsers/native-gpu-and-video.md).

### Applications, audio and Android integration

| Project or contributor | Contribution to this project |
| --- | --- |
| [Mission Center](https://gitlab.com/mission-center-devs/mission-center), [Magpie](https://gitlab.com/mission-center-devs/gng), and [app-rummage](https://gitlab.com/mission-center-devs/app-detection) | Monitor UI, collectors, application detection and protocol adapted to the shared Android resource backend. |
| [Shizuku / Shizuku-API and rish](https://github.com/RikkaApps/Shizuku-API), and [thejaustin/ShizukuPlus](https://github.com/thejaustin/ShizukuPlus) | Privileged shell transport and privilege-model references for resource reads and Bluetooth routing. Shizuku+ was the implementation available for device testing. |
| [UPower](https://upower.freedesktop.org/) | Battery service and desktop-facing API adapted to Android battery data. |
| [EasyEffects](https://github.com/wwmm/easyeffects), [LSP Plugins](https://github.com/lsp-plugins/lsp-plugins), and [PulseAudio](https://www.freedesktop.org/wiki/Software/PulseAudio/) | Native effects, LV2 equalizer and Android audio endpoints. PipeWire's [Pulse tunnel](https://docs.pipewire.org/page_module_pulse_tunnel.html) and [parametric equalizer](https://docs.pipewire.org/page_module_parametric_equalizer.html) documentation informed the audio design. |
| [AutoEq](https://github.com/jaakkopasanen/AutoEq), its measurement/preset contributors including oratory1990, and [OPRA](https://github.com/opra-project/OPRA) | Equalization data, preset-format references and import/conversion fixtures. EQ presets retain their authors' credits. |
| [GSConnect](https://github.com/GSConnect/gnome-shell-extension-gsconnect), [KDE Connect](https://kdeconnect.kde.org/), and Daniel Landau | Phone/desktop protocol and integration. The GSConnect package retains Landau's encrypted-identity validation patch from Debian's source package. |
| [Serein / ViceVerse-cz](https://github.com/ViceVerse-cz/Serein) | Native Discord client and the audio/voice stack used by the Serein port and earlier microphone probes. |
| [Mixtapes / m-obeid](https://github.com/m-obeid/Mixtapes), [rustypipe-botguard / ThetaDev](https://codeberg.org/ThetaDev/rustypipe-botguard), and [rustls-platform-verifier](https://github.com/rustls/rustls-platform-verifier/issues/126#issuecomment-2306232794) | Music client, playback helper and trust-store adaptation reference for a native executable without an Android JVM. |
| [Ghostty](https://github.com/ghostty-org/ghostty) and [GourangaDasSamrat's Termux PR #32263](https://github.com/termux/termux-packages/pull/32263) | Native terminal and Termux packaging used by the desktop. Ghostty 1.4's OpenGL, EGL, render-target and GTK presentation sources guided the DMA-BUF synchronization investigation and GPU-rendered CPU-readback fallback. |
| [Code OSS](https://github.com/microsoft/vscode), licy183, and the Termux editor maintainers | Editor sources, native package recipe and patches. The package records its [upstream recipe provenance](packages/code-oss/upstream.json). |
| [Open VSX](https://open-vsx.org/), GitHub Pull Requests, GitHub Actions, GitLens, Git Graph, [Open Remote - SSH](https://github.com/jeanp413/open-remote-ssh), and SSH FS | Extension distribution and the editing, Git and remote-work features installed by the Code OSS overlay. See the [extension inventory](docs/code-oss/README.md#what-replaces-what). |

### Desktop appearance and assets

Thanks to the authors and maintainers of [ArcMenu](https://gitlab.com/arcmenu/ArcMenu),
[Dash to Panel](https://github.com/home-sweet-gnome/dash-to-panel),
[Desktop Icons NG](https://packages.debian.org/trixie/gnome-shell-extension-desktop-icons-ng),
[AppIndicator](https://github.com/ubuntu/gnome-shell-extension-appindicator),
[User Themes](https://packages.debian.org/trixie/gnome-shell-extension-user-theme),
[NoAnnoyance](https://github.com/jirkavrba/noannoyance), and
[Tiling Assistant](https://packages.debian.org/trixie/gnome-shell-extension-tiling-assistant), and of
florintanasa's [Accent GTK Theme](https://github.com/florintanasa/accent-gtk-theme),
[Accent Icons Theme](https://github.com/florintanasa/accent-icons-theme) and
[Accent User Theme](https://github.com/florintanasa/accent-user-theme).
Their extensions supply much of the desktop's layout and behavior.

[vinceliuice's WhiteSur GTK theme](https://github.com/vinceliuice/WhiteSur-gtk-theme) and
[Colloid icon theme](https://github.com/vinceliuice/Colloid-icon-theme) supply the optional theming.
Thanks also to the Adwaita, Cantarell, Noto, Unifont and Hanazono font/icon contributors,
and to the wallpaper photographers. Individual photographers, source images and applicable
licenses are listed in the [wallpaper attributions](overlays/Desktop%20Environment+Theming/filesystem/live_installed/usr/share/backgrounds/ATTRIBUTIONS.txt).

<details>
<summary>Additional PRs, issue discussions and research references</summary>

These references informed implementation choices and investigations, including paths that
were evaluated but did not become part of the native desktop. Their inclusion does not
imply that a proposed patch is installed or that its authors maintain this port.

| Reference | What it informed |
| --- | --- |
| [1d10t's Termux:API #857](https://github.com/termux/termux-api/pull/857) and [termux-api-package #236](https://github.com/termux/termux-api-package/pull/236) | Bluetooth SCO routing and microphone-source ideas; the implemented route is documented in the [Bluetooth report](docs/mic/BLUETOOTH.md). |
| [james28909's Termux:API #904](https://github.com/termux/termux-api/pull/904) and [termux-api-package #241](https://github.com/termux/termux-api-package/pull/241) | Camera2/MediaRecorder reference for the [live-camera investigation](docs/termux-camera-investigation.md). |
| [GourangaDasSamrat's termux-packages #32912](https://github.com/termux/termux-packages/pull/32912) | Preserving `LD_PRELOAD` in Code OSS child processes. |
| [termux-packages #24715](https://github.com/termux/termux-packages/issues/24715) and [#27463](https://github.com/termux/termux-packages/issues/27463#issuecomment-3592023141) | Native CodeLLDB packaging and working debugger configuration. |
| [termux-packages #24739](https://github.com/termux/termux-packages/issues/24739), [#27660](https://github.com/termux/termux-packages/issues/27660), [#30579](https://github.com/termux/termux-packages/issues/30579), and [TUR #1197](https://github.com/termux-user-repository/tur/issues/1197) | Editor, extension and remote-work compatibility discussions reviewed in the [Code OSS assessment](docs/code-oss/README.md). |
| [Codex #58398](https://github.com/openai/codex/issues/58398) | Extension startup issue consulted during Code OSS compatibility testing. |
| [Android NDK #201](https://github.com/android-ndk/ndk/issues/201) and [termux-packages #18823](https://github.com/termux/termux-packages/issues/18823) | Linker and fortified-libc constraints referenced by retained Mutter/Mesa patches. |
| [freedesktop-sdk compiler-warning change](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/commit/ce54a2527555e51e4ebf4cce9cbb6259cafa89a4) and [Arch Linux Code packaging](https://gitlab.archlinux.org/archlinux/packaging/packages/code/-/commit/e050d3e8120e052cd7af19d2f67bcd36dc52e436) | References preserved in the Nautilus patch and upstream Code OSS build recipe. |
| [sylirre's PRoot #359](https://github.com/termux/proot/pull/359), [PRoot #404](https://github.com/termux/proot/issues/404), [PRoot-Distro](https://github.com/termux/proot-distro), and [termux-proot-for-flatpak](https://github.com/jjtseng93/termux-proot-for-flatpak) | Earlier PRoot/Flatpak compatibility work and the decision to migrate to native applications. |
| [virglrenderer](https://gitlab.freedesktop.org/virgl/virglrenderer) and Termux's [virglrenderer-android](https://github.com/termux/termux-packages/tree/master/packages/virglrenderer-android) | VirGL/vtest host renderer used for the earlier Mali desktop route and the x1s Firefox virpipe comparison runs before the Zink-on-PanVK route. |
| [LinuxDroidMaster/Termux-Desktops issue #68](https://github.com/LinuxDroidMaster/Termux-Desktops/issues/68) and the [r/termux S20 Exynos 990 discussion](https://www.reddit.com/r/termux/comments/1rle12y/s20_exynos_990_cyberdeck_build_should_i_root_for/) | Galaxy S20 (Exynos 990) community context read during the x1s GPU investigation; not substituted for local hardware tests. |
| [LinuxDroidMaster/Termux-Desktops](https://github.com/LinuxDroidMaster/Termux-Desktops), [pipewire-termux-proot](https://github.com/leefm0204/pipewire-termux-proot), and [lfdevs/anland-termux](https://github.com/lfdevs/anland-termux) | Community desktop, audio and alternative Android display/session references. |
| [Termux app #2366](https://github.com/termux/termux-app/issues/2366) | Android process-management restrictions considered in the earlier desktop assessment. |
| [Running Services Monitor](https://github.com/biplobsd/running_services_monitor), [AnotherMonitor](https://github.com/AntonioRedondo/AnotherMonitor), [tx-cpu](https://github.com/Welpyes/tx-cpu), [NVTOP](https://github.com/Syllo/nvtop), and [htop](https://github.com/htop-dev/htop) | Android process visibility, privileged CPU reads, GPU telemetry and monitoring alternatives. |
| [FristOneRR/FristOneRR-Panvk-Driver](https://github.com/FristOneRR/FristOneRR-Panvk-Driver/) | Reference reviewed alongside Zenith for running a userspace PanVK kbase backend on stock Android kernels; its published material did not establish x1s acceptance. |
| [Mattcabrices/moto-pad-2026-arch-linux](https://github.com/Mattcabrices/moto-pad-2026-arch-linux) | Android hardware-buffer, GBM, libhybris and compositor integration references reviewed during the Mali graphics investigation. Its kernel, compositor and browser configuration differ from this native Termux setup. |
| [ar37-rs/virgl-angle](https://github.com/ar37-rs/virgl-angle) | Source of the privately staged Android Vulkan ICD/WSI wrapper artifact used in the initial x1s native Vulkan checks; its repository name does not establish use of an ANGLE rendering backend. |
| [libhybris](https://github.com/libhybris/libhybris) | glibc-to-Android graphics compatibility research lead; its mention was not a validated Chrome Vulkan bridge. |
| [Ghostty discussion #14395](https://github.com/ghostty-org/ghostty/discussions/14395) and [#13907](https://github.com/ghostty-org/ghostty/discussions/13907), [Ghostty's OpenGL backend](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/renderer/OpenGL.zig), and [GTK's feature switches](https://github.com/GNOME/gtk/blob/main/gdk/gdk.c) | OpenGL requirements, DMA-BUF presentation fallback and experimental GLES/Vulkan port research leads. Thanks to the discussion contributors and TensorFleet's experimental port work. The alternative backends were not built or validated in this investigation. |
| [Termux:Widget](https://github.com/termux/termux-widget) and [griffo's package repository](https://deb-free.griffo.io/) | Shortcut behavior and Debian package-availability references in the earlier Ghostty native/PRoot assessment. |
| [xdotool](https://github.com/jordansissel/xdotool), [Android Debug Bridge](https://developer.android.com/tools/adb), and [OpenSSH](https://www.openssh.com/) | Desktop automation and the phone test rig. |
| [Moonlight Android](https://github.com/moonlight-stream/moonlight-android), especially [MediaCodecHelper.java](https://github.com/moonlight-stream/moonlight-android/blob/master/app/src/main/java/com/limelight/binding/video/MediaCodecHelper.java) | Decoder latency and vendor-format-key references for the Firefox/Exynos HEVC investigation; the Exynos RTC low-latency option is documented there as an H.264 option. |
| [Mattcabrices/moto-pad-2026-arch-linux](https://github.com/Mattcabrices/moto-pad-2026-arch-linux) | Mali browser, libhybris and AHardwareBuffer-backed GBM design references reviewed for the x1s investigation; these are references, not a validated Termux driver or compositor integration. |
| [AOSP low-latency MediaCodec documentation](https://source.android.com/docs/core/media/low-latency-media) | Standard Android decoder low-latency behavior used as a reference during the HEVC buffering investigation. |
| [Linux procfs documentation](https://www.kernel.org/doc/html/v6.15/filesystems/proc.html), [AOSP SELinux hooks](https://android.googlesource.com/kernel/common/+/4cdd5f9186bbe80306e76f11da7ecb0b9720433c/security/selinux/hooks.c#2085), [Android DMA-BUF heaps](https://source.android.com/docs/core/architecture/kernel/dma-buf-heaps), and [X11 MIT-SHM](https://xorg.freedesktop.org/archive/X11R7.5/doc/Xext/mit-shm.html) | Resource access, file-descriptor permission boundaries, video allocation and compositor debugging. |
| [Hainer007's PanVK issue #29](https://github.com/zenithblue-oss/panvk-kbase-android/issues/29), [faux123's PanVK releases](https://github.com/faux123/panvk-faux123-driver-ace/releases), [JimVulkan/mesa-unified-drivers](https://github.com/JimVulkan/mesa-unified-drivers), and [Sky1-Linux](https://github.com/Sky1-Linux) | Device reports and alternative Mali driver/OpenGL approaches reviewed during the search for support beyond OpenGL 4.2. These references do not establish compatibility with this project's G77 setup. |
| [wonderkast02/panvk-g720-kbase-csf](https://github.com/wonderkast02/panvk-g720-kbase-csf), [LukeValen/panvk-mali-g52](https://github.com/LukeValen/panvk-mali-g52), and [Noysz/panvk-g99-jm](https://github.com/Noysz/panvk-g99-jm) | CSF, Bifrost and Valhall JM references recorded by the pinned Zenith source reconstruction and consulted during PanVK source review. |
| [FristOneRR-Panvk-Source](https://github.com/FristOneRR-Admin/FristOneRR-Panvk-Source), [bmdhacks/malisx2](https://github.com/bmdhacks/malisx2), and [m8l8th814n-eng/mesa-gs101](https://github.com/m8l8th814n-eng/mesa-gs101) | JM submission, kbase lifecycle and G77/G78 model references credited by the upstream PanVK patch series used in the investigation. |
| [nangitagamer777-art/PanVK-kbase](https://github.com/nangitagamer777-art/PanVK-kbase), [Panvk_Kmod](https://github.com/nangitagamer777-art/Panvk_Kmod), [GunaCharanTeja/panvk-kbase-android](https://github.com/GunaCharanTeja/panvk-kbase-android), [leegao/bcn_layer](https://github.com/leegao/bcn_layer), and [mesa-funnymdzz](https://github.com/leegao/mesa-funnymdzz) | Implementation-history and texture-format references recorded in Zenith's source provenance; inclusion credits the upstream research without claiming every path is enabled in this desktop. |
| [chaotic-cx/mesa-mirror](https://github.com/chaotic-cx/mesa-mirror) | Accessible mirror of Mesa source used to trace OpenGL version selection, Zink compute capability mapping and PanVK workgroup limits. |
| [GJS Guide](https://gjs.guide/), [freedesktop.org specifications](https://specifications.freedesktop.org/), and [Android resolver documentation](https://source.android.com/docs/core/ota/modular-system/dns-resolver#mdns-local-resolution) | Extension/session behavior, desktop integration and LAN hostname investigation. |

Further source links and pinned revisions remain beside the relevant code in `packages/`,
`prebuilt/`, overlay installers and the reports under `docs/`. Upstream copyright notices,
patch authorship and package licenses remain with their respective files.

</details>

## License

[MIT](LICENSE) for this repository's own code. Each package keeps its upstream license, and patches
follow the license of the program they change.
