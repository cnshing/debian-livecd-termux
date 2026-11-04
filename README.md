# debian-livecd-termux

> [!WARNING]
> Everything past this point for the whole project is completely generated with LLMs. Proceed at your own risk!

A port of [debian-livecd](https://github.com/cnshing/debian-livecd)'s GNOME desktop to native
Termux on Android, without PRoot. Tested on an arm64 Note10+ running Android 11.

## Requirements by feature

Start with native Termux and the Termux:X11 Android app. The validated setup uses
arm64 Android 11 with the standard `com.termux` prefix; other devices and Android
versions need their own validation. Follow the linked guides for the features you want:

| Feature set | Requirements and setup |
| --- | --- |
| GNOME desktop and native applications | [Native desktop setup](docs/native/README.md#install-and-run), including the separately installed Termux:X11 APK. |
| Phone microphone | [Microphone setup](docs/mic/README.md#set-up): matching-source Termux:API Android app, microphone permission and the Microphone overlay. |
| Bluetooth headset microphone and call audio | [Bluetooth setup](docs/mic/README.md#android-managed-bluetooth-audio-devices): microphone setup, running Shizuku with Termux authorized, exported `rish`, and a headset connected in Android with **Calls** enabled. See the [device and Android-version limits](docs/mic/BLUETOOTH.md#android-permission-boundary). |
| Whole-device CPU, processes and supported sensors | [Resource access setup](docs/resources/README.md#build-and-use): Shizuku, Termux authorization, exported `rish` and `livecd-resources`. |
| EasyEffects and AutoEq | [Audio effects setup](docs/audio/README.md#build-and-install): Audio Effects overlay and a running Termux PulseAudio server; see [application routing](docs/audio/README.md#run). |
| GSConnect phone/desktop sync | [GSConnect setup](docs/gsconnect/README.md#build-and-install) and [runtime requirements](docs/gsconnect/README.md#run): Phone Sync overlay, an X display and a compatible peer reachable on the LAN. |
| GPU rendering and hardware video | [Acceleration guide](docs/native/ACCELERATION.md): compatible device drivers, application backends and codec support; requirements and verified results vary by application. |
| Battery status and health | [Battery backend requirements](docs/battery/README.md#where-the-numbers-come-from): readable Android battery data, with Termux:API as a fallback; Shizuku enables event updates and supported health readings. |

Installed optional integrations can follow the desktop's lifetime; see
[session integration settings](docs/native/README.md#session-integrations).

## Install

Get this repository onto the phone, then run this in native Termux:

```sh
bash install.sh
```

The script fetches the compiled packages from this project's latest release into a local apt
repository, then installs them and applies the overlays. To add optional features, name their overlays:
`bash install.sh "Audio Effects"`.

To use a tarball you already have, run `bash install.sh --repo-tarball FILE`.

`livecd start` also starts installed microphone/Bluetooth,
EasyEffects and GSConnect integrations and stages the resource reader. They follow
the desktop's lifetime; see [session integrations](docs/native/README.md#session-integrations)
for prerequisites, routing and per-feature switches.

> **Status:** the programs have been built and tested on a phone, but this install flow has not run,
> and no release exists yet. See [the status section](docs/structure.md#status).

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

The GNOME recipes in `packages/` carry the source archives and patches of the GNOME 48 source port that passed device acceptance on the phone; the new packaging path still needs its own full build and device acceptance.

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
| [GNOME](https://www.gnome.org/), [GTK](https://www.gtk.org/), and [SpiderMonkey](https://spidermonkey.dev/) | Shell, Mutter/Cogl, GJS, gnome-session, Nautilus, Autoar, Settings Daemon, LocalSearch, libraries and schemas forming the desktop. See the [GNOME package source notes](packages/livecd-gnome-runtime/SOURCES.md). |
| [licy183's GNOME Shell PR #24585](https://github.com/termux/termux-packages/pull/24585) and [Termux's GNOME 48 recipes](https://github.com/termux/termux-packages/tree/77ae9db667103a2ea7575c8f23a497754796951a) | Earlier GNOME packaging and Android adaptations underpinning the source-port work, including retained patches and cross-build introspection data. |
| [Gass-OS/GNOME-Termux](https://github.com/Gass-OS/GNOME-Termux) | Earlier native GNOME bootstrap and readable Shell JavaScript adaptations. [`0200-termux-session.patch`](packages/livecd-gnome-shell/0200-termux-session.patch) derives from its resources at `42a890c…`, rebased and adjusted for this desktop. |
| [JesusChapman's GNOME 49 PR #32883](https://github.com/termux/termux-packages/pull/32883) | Native packaging, service adaptations and Nautilus recipe reference used during migration. This project's core runtime remains GNOME 48. |
| [Md Arif / sabamdarif](https://github.com/sabamdarif) | Retained Nautilus Android patches, including `getpwent` and compiler-warning changes, plus the [gnome-in-termux](https://github.com/sabamdarif/gnome-in-termux) startup reference. |
| [Debian](https://www.debian.org/) and its maintainers | Source archives, portable GNOME extension/font packages, library inputs for the glibc browser stack, and the earlier Debian/PRoot desktop. |

### Graphics, browsers and media

| Project or contributor | Contribution to this project |
| --- | --- |
| [lfdevs/Termux:VA](https://github.com/lfdevs/termux-va) | MediaCodec daemon and VA-API transport on which the experimental hardware-video integration and encoder extensions build. The [maintainer's explanation in issue #1](https://github.com/lfdevs/termux-va/issues/1#issuecomment-6488523619) also informed the native FFmpeg investigation. |
| [lfdevs/Mesa for Android Container](https://github.com/lfdevs/mesa-for-android-container) | Android-container Mesa sources and glibc graphics artifacts used in the browser GPU/video work. |
| [Mesa](https://www.mesa3d.org/), [Freedreno/Turnip](https://docs.mesa3d.org/drivers/freedreno.html), and [Zink](https://docs.mesa3d.org/drivers/zink.html) | Native and glibc GPU rendering, Vulkan/OpenGL drivers and software fallbacks. Termux supplies the packaged native drivers and port patches. |
| [theonuverse/Bionilux](https://github.com/theonuverse/bionilux) and [termux-pacman/glibc-packages](https://github.com/termux-pacman/glibc-packages) | glibc program launching and compatibility-package references for running Chrome alongside Bionic applications. |
| [libva](https://github.com/intel/libva), [FFmpeg](https://github.com/FFmpeg/FFmpeg), [GStreamer](https://gstreamer.freedesktop.org/), and [PipeWire](https://pipewire.org/) | Video APIs, codec implementations, media pipelines, camera experiments and audio transport. |
| [Chromium](https://www.chromium.org/), [Firefox](https://github.com/mozilla-firefox/firefox), [chromium-linux-tarballs](https://github.com/chromium-linux-tarballs/chromium-tarballs), and [ungoogled-chromium-portablelinux](https://github.com/ungoogled-software/ungoogled-chromium-portablelinux) | Browser sources, source archives and the optional portable Chromium input. Thanks also to licy183 and the Termux Chromium maintainers for the recipe and Android patches retained by this build. |
| [Android Open Source Project](https://source.android.com/), [Android NDK](https://developer.android.com/ndk), and [scrcpy](https://github.com/Genymobile/scrcpy) | Camera, Binder, Bluetooth, shared-memory, buffer-allocation and MediaCodec source/API references. The camera investigation also consulted [scrcpy PR #4213](https://github.com/Genymobile/scrcpy/pull/4213). |

Exact GPU/video inputs are recorded in the [native-video source lock](prebuilt/native-video/sources.lock.json),
[Termux:VA lock](prebuilt/native-video/daemon.lock.json), and [browser integration report](docs/browsers/native-gpu-and-video.md).

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
| [Ghostty](https://github.com/ghostty-org/ghostty) and [GourangaDasSamrat's Termux PR #32263](https://github.com/termux/termux-packages/pull/32263) | Native terminal and Termux packaging used by the desktop. |
| [Code OSS](https://github.com/microsoft/vscode), licy183, and the Termux editor maintainers | Editor sources, native package recipe and patches. The package records its [upstream recipe provenance](packages/code-oss/upstream.json). |
| [Open VSX](https://open-vsx.org/), GitHub Pull Requests, GitHub Actions, GitLens, Git Graph, [Open Remote - SSH](https://github.com/jeanp413/open-remote-ssh), and SSH FS | Extension distribution and the editing, Git and remote-work features installed by the Code OSS overlay. See the [extension inventory](docs/code-oss/README.md#what-replaces-what). |

### Desktop appearance and assets

Thanks to the authors and maintainers of [ArcMenu](https://gitlab.com/arcmenu/ArcMenu),
[Dash to Panel](https://github.com/home-sweet-gnome/dash-to-panel),
[Desktop Icons NG](https://packages.debian.org/trixie/gnome-shell-extension-desktop-icons-ng),
[AppIndicator](https://github.com/ubuntu/gnome-shell-extension-appindicator),
[User Themes](https://packages.debian.org/trixie/gnome-shell-extension-user-theme),
[NoAnnoyance](https://github.com/jirkavrba/noannoyance), and
[Tiling Assistant](https://packages.debian.org/trixie/gnome-shell-extension-tiling-assistant).
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
| [LinuxDroidMaster/Termux-Desktops](https://github.com/LinuxDroidMaster/Termux-Desktops), [pipewire-termux-proot](https://github.com/leefm0204/pipewire-termux-proot), and [lfdevs/anland-termux](https://github.com/lfdevs/anland-termux) | Community desktop, audio and alternative Android display/session references. |
| [Termux app #2366](https://github.com/termux/termux-app/issues/2366) | Android process-management restrictions considered in the earlier desktop assessment. |
| [Running Services Monitor](https://github.com/biplobsd/running_services_monitor), [AnotherMonitor](https://github.com/AntonioRedondo/AnotherMonitor), [tx-cpu](https://github.com/Welpyes/tx-cpu), [NVTOP](https://github.com/Syllo/nvtop), and [htop](https://github.com/htop-dev/htop) | Android process visibility, privileged CPU reads, GPU telemetry and monitoring alternatives. |
| [xdotool](https://github.com/jordansissel/xdotool), [Android Debug Bridge](https://developer.android.com/tools/adb), and [OpenSSH](https://www.openssh.com/) | Desktop automation and the phone test rig. |
| [Linux procfs documentation](https://www.kernel.org/doc/html/v6.15/filesystems/proc.html), [AOSP SELinux hooks](https://android.googlesource.com/kernel/common/+/4cdd5f9186bbe80306e76f11da7ecb0b9720433c/security/selinux/hooks.c#2085), [Android DMA-BUF heaps](https://source.android.com/docs/core/architecture/kernel/dma-buf-heaps), and [X11 MIT-SHM](https://xorg.freedesktop.org/archive/X11R7.5/doc/Xext/mit-shm.html) | Resource access, file-descriptor permission boundaries, video allocation and compositor debugging. |
| [GJS Guide](https://gjs.guide/), [freedesktop.org specifications](https://specifications.freedesktop.org/), and [Android resolver documentation](https://source.android.com/docs/core/ota/modular-system/dns-resolver#mdns-local-resolution) | Extension/session behavior, desktop integration and LAN hostname investigation. |

Further source links and pinned revisions remain beside the relevant code in `packages/`,
`prebuilt/`, overlay installers and the reports under `docs/`. Upstream copyright notices,
patch authorship and package licenses remain with their respective files.

</details>

## License

[MIT](LICENSE) for this repository's own code. Each package keeps its upstream license, and patches
follow the license of the program they change.
