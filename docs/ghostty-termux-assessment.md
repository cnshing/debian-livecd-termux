# Ghostty on Termux: native shells, Debian shells, and separate shortcuts

**Superseded:** the desktop is native-only, so the two launchers recommended below are gone. The menu has one Ghostty entry, the package's own, and the [`Terminal` overlay](../overlays/Terminal) supplies its theme and login shell. The rest of this document is the earlier assessment.

**Runtime work added:** native Ghostty 1.3.1 renders on the physical rig with llvmpipe/OpenGL 4.6. Both Termux and Debian identities were checked in windows, tabs, and splits. The JSON bridge and Nautilus context action preserve guest paths containing spaces, Unicode, quotes, and shell syntax. Native terminal launch was also checked with a missing guest. See [device validation](termux-device-validation.md), installed launchers (since removed), and verification report (since removed). The examples below remain the initial design; they are not the installer used by the new profile. GPU results for guest applications do not establish native Ghostty GPU acceleration. A final normal close/confirmation test removed the window but left the client and guest shell alive; per-window lifecycle is not fully accepted. Typing `exit` was subsequently verified to close the window and tracked processes in both modes; the failed close-button path remains the limit. GNOME Terminal remains the default for ordinary close-button use.

Reviewed as an expansion of the [Termux/PRoot assessment](termux-proot-analysis.md#graphics-and-native-termux-ghostty). The historical sections below are a package/source assessment and proposed setup; the subsequent report above supplies the later device evidence. The examples assume ordinary Termux paths, an aarch64 device, an existing Debian guest named `debian`, and an existing guest user `desktop` with home `/home/desktop` and Bash installed. Substitute the actual guest/user before using them.

**Recommendation: install Ghostty once in native Termux and offer two launchers: “Ghostty — Termux” and “Ghostty — Debian.”** Both can use the same native terminal window; their shells and package environments differ. Running Ghostty itself inside Debian remains possible, but no arm64 Debian package was found, so it means a source build. Keep Debian's gnome-terminal as the fallback if native Ghostty does not render acceptably.

## What “native” means here

| Arrangement | Window and renderer | Shell and commands | Package manager and configuration |
| --- | --- | --- | --- |
| Ordinary Termux Android terminal | Termux Android app | Native Termux | Termux `pkg`; Termux shell startup files |
| Native Ghostty with Termux shell | Termux Ghostty on Termux:X11 | Native Termux | Termux `pkg`; Ghostty config in the Termux home |
| Native Ghostty with Debian shell | Termux Ghostty on Termux:X11 | Debian under PRoot | Termux manages Ghostty; Debian `apt` manages guest tools; Ghostty config stays in the Termux home |
| Debian Ghostty with Debian shell | Debian Ghostty under PRoot, displayed on Termux:X11 | Debian under PRoot | Debian-compatible Ghostty package; Ghostty config in the Debian user's home |

The third arrangement is the original report's recommendation. It preserves Debian commands and libraries while keeping Ghostty's own process outside PRoot. A Debian shell does not turn the native Ghostty binary into a Debian binary. Conversely, running a native Termux shell in Ghostty does not require a Debian session.

“Use Termux in PRoot” usually means entering Debian from a Termux terminal. The Android Termux app continues to host that terminal; the shell it displays changes. Installing Termux's Android UI inside Debian is not part of this setup. There is also a separate choice to install a Linux build of Ghostty inside Debian.

## What the native package actually does

The official Termux X11 aarch64 index was checked directly and publishes **Ghostty 1.3.1**. Its package recipe and six patches were reviewed at Termux commit [`e71e4cd408f82f53ff0063be22745f6495357f60`](https://github.com/termux/termux-packages/tree/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty). This is an official Termux repository package, maintained for Termux; that does not imply an Android APK distributed by the Ghostty project. [Repository index](https://packages.termux.dev/apt/termux-x11/dists/x11/main/binary-aarch64/Packages.gz), [Ghostty's packaging policy](https://ghostty.org/docs/install/binary)

The [recipe](https://github.com/termux/termux-packages/blob/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty/build.sh) builds the real GTK4/libadwaita application against **Android/Bionic**, with X11 enabled and Wayland disabled. It excludes `arm` and `i686`; aarch64 publication was verified, rather than inferring availability for every other architecture. Dependencies include GTK4, libadwaita, Fontconfig, FreeType, HarfBuzz, and X11 libraries. Internationalization and generated documentation are disabled in this recipe, and systemd unit directories are removed.

The package is new. At review time the merge was its only commit, the PR's device evidence was one recorded test on an aarch64 tablet, and the recipe sets `TERMUX_PKG_AUTO_UPDATE=false`, so upstream releases wait for a manual bump. The patches below are carried by Termux, not upstream Ghostty; the child-process watcher in particular changes how Ghostty notices a shell exiting. Acceptance testing, not packaging, establishes stability. [PR discussion](https://github.com/termux/termux-packages/pull/32263)

| Adaptation in the package | Practical effect |
| --- | --- |
| [Android shell/home patch](https://github.com/termux/termux-packages/blob/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty/0004-android-default-shell-home-and-bin-sh.patch) | Uses an accessible `$SHELL`, with Termux's `bin/login` as fallback; uses `$HOME`/the Termux home instead of Android's passwd defaults. Shell command expansion uses Termux's `bin/sh`. Launcher starts in `/` are treated as home starts. Cgroup integration defaults to disabled on Android. |
| [Temporary directory patch](https://github.com/termux/termux-packages/blob/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty/0005-os-file-android-tmpdir.patch) | Adds `$PREFIX/tmp` as the Android fallback after environment-specified temporary directories. |
| [Event-loop patch](https://github.com/termux/termux-packages/blob/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty/0003-global-skip-xev-io-uring-probe-on-android.patch) | Skips an io_uring probe that can trigger Android's syscall filter; retains the compatible epoll backend. |
| [Child-process watcher patch](https://github.com/termux/termux-packages/blob/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty/0006-termio-android-process-watcher-without-pidfd.patch) | Uses a waitid-based helper thread rather than relying on pidfd behavior missing on older Android kernels. This addresses terminals closing immediately after their shell starts. |
| [Graphics loader patch](https://github.com/termux/termux-packages/blob/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty/0001-dcimgui-use-desktop-gl-loader-on-android.patch) | Selects the desktop GL loader for the ImGui backend on Android. It does not convert Ghostty into an Android GLES terminal. |
| [Kitty graphics patch](https://github.com/termux/termux-packages/blob/e71e4cd408f82f53ff0063be22745f6495357f60/x11-packages/ghostty/0002-kitty-graphics-no-shm-open-on-android.patch) | Rejects the shared-memory image transport requiring `shm_open`/`shm_unlink`. This is a specific transport limitation, not removal of the entire image protocol. |

The published `.deb` was also inspected without executing it. It contains `$PREFIX/bin/ghostty`, resources/themes, shell-integration scripts, `ghostty`/`xterm-ghostty` terminfo, a `.desktop` file, a D-Bus activation file, icons, and the ordinary Nautilus Python extension. Its desktop entry invokes `/data/data/com.termux/files/usr/bin/ghostty --gtk-single-instance=true` and advertises D-Bus activation. It contains no Android APK or PRoot entry script. [Inspected package](https://packages.termux.dev/apt/termux-x11/pool/main/g/ghostty/ghostty_1.3.1_aarch64.deb)

Installing it therefore supplies a graphical terminal executable. It does not install Debian, enter PRoot, start a complete desktop, replace the Termux app's terminal view, or create an Android launcher icon by itself. A native shell is the normal outcome when Ghostty inherits a native Termux environment and no custom command overrides it.

### The remaining graphics requirement

**Ghostty 1.3.1's OpenGL renderer requires desktop OpenGL 4.3.** Its tagged source checks this version explicitly, and OpenGL is its only renderer outside Apple platforms: Ghostty has no software or GLES fallback of its own. A working X11 window or an Android GPU supporting OpenGL ES does not by itself establish that requirement. The native process uses Termux's Mesa, not the guest's; a driver working only inside Debian is insufficient. [Version requirement and check](https://github.com/ghostty-org/ghostty/blob/v1.3.1/src/renderer/OpenGL.zig#L36), [renderer backends](https://github.com/ghostty-org/ghostty/blob/v1.3.1/src/renderer/backend.zig)

Termux's Mesa is built with llvmpipe, softpipe, VirGL, and Zink. llvmpipe implements OpenGL 4.5 on the CPU and is what Mesa normally falls back to when no hardware driver is configured, so the requirement is likely met by default, in software. [Termux Mesa recipe](https://github.com/termux/termux-packages/blob/master/packages/mesa/build.sh) Two things need checking instead:

- **Responsiveness.** Whether CPU rendering keeps typing, scrolling, and resizing responsive at the device's resolution, and at what CPU and battery cost.
- **Inherited driver selection.** Desktop launchers often set variables such as `GALLIUM_DRIVER` or `MESA_LOADER_DRIVER_OVERRIDE` to select VirGL or Zink. If Ghostty inherits a selection whose driver reports less than OpenGL 4.3, it fails to open a terminal rather than running slowly. The sample launcher below neither sets nor clears these; add the chosen driver variables there once a profile is validated. Forcing a reported version with `MESA_GL_VERSION_OVERRIDE` does not implement missing features.

`GSK_RENDERER=cairo` changes GTK rendering; it does not supply Ghostty's terminal-content renderer. A hardware path such as Turnip with Zink on supported Adreno devices is optional performance work. Do not count native package availability as a completed graphics validation or promise a performance gain without measurement.

If Ghostty does not render acceptably, fall back to Debian's arm64 gnome-terminal. It draws through VTE and GTK rather than Ghostty's renderer, and joins GNOME's session and Nautilus without a host bridge. Termux also packages native Alacritty, kitty, gnome-terminal, and xfce4-terminal.

## Making the normal launch native

Run these commands **in native Termux**, outside Debian:

```bash
pkg install x11-repo
pkg install ghostty termux-x11-nightly dbus
```

Install the separate Termux:X11 Android app as well. Start or reuse the display established for the desktop; this document uses `:1`. For a display that is not already running:

```bash
termux-x11 :1 &
```

Once the display is ready, a native-shell launch can be explicit:

```bash
DISPLAY=:1 GDK_BACKEND=x11 dbus-run-session -- ghostty \
    --gtk-single-instance=false \
    --command="direct:/data/data/com.termux/files/usr/bin/bash -l"
```

This only starts Ghostty and a shell. Reuse the established desktop/window manager for normal window handling. Termux:X11 needs both its Android app and its companion package; sharing its socket with the guest is a separate launch concern. [Termux:X11 setup and PRoot instructions](https://github.com/termux/termux-x11#readme)

If tapping the **Termux Android app icon** currently enters Debian, inspect the Termux shell's startup files for an automatic `proot-distro login`, custom rootfs launcher, or an `exec` that enters the guest. Remove that automatic entry from the general startup path and put it in a dedicated Debian launcher. Native Ghostty's Bash will otherwise read the same startup logic and can enter Debian too. Keep the normal Termux icon as a native recovery path; Ghostty's package cannot override those shell customizations.

## Preferring a Debian shell

Keep the same native Ghostty installation and make its terminal command enter the existing guest. Use the same guest name, user, binds, and compatibility launcher as the desktop. Each terminal creates another shell session in the same guest filesystem, not another installed Debian system.

There are two important launch details:

- **Use `command` for a persistent preference.** It applies to new windows, tabs, and splits. `ghostty -e proot-distro …` sets `initial-command`, so later terminals can revert to the configured native shell.
- **Keep profiles in separate Ghostty processes initially.** The packaged desktop file explicitly requests single-instance mode. Reusing that instance can reuse its original configuration. `gtk-single-instance=false` makes each selected profile unambiguous. Separate application classes can also distinguish the two window groups.

These behaviors are documented in the [configuration reference](https://ghostty.org/docs/config/reference#command) and the [1.3.1 configuration source](https://github.com/ghostty-org/ghostty/blob/v1.3.1/src/config/Config.zig). The examples below deliberately set a command for every terminal surface rather than relying on a first-window command.

### A concrete pair of native-host profiles

These are **proposed files to install in Termux**, not changes applied to this liveCD's overlays. They assume PRoot-Distro **5.10.3**, the version selected by the reviewed [Termux recipe](https://github.com/termux/termux-packages/blob/master/packages/proot-distro/build.sh). Its [tagged login documentation](https://github.com/termux/proot-distro/blob/v5.10.3/README.md#login--start-a-shell-inside-a-container) supports `--user`, `--work-dir`, `--env`, and `--shared-tmp`. Check the installed `proot-distro login --help`; older releases and custom launchers have different interfaces.

Create the directories:

```bash
mkdir -p "$HOME/.local/bin" "$HOME/.config/ghostty"
```

Copy the repository's [appearance configuration](../overlays/Terminal/filesystem/live_installed/etc/skel/.config/ghostty/config.ghostty) to Termux's `~/.config/ghostty/config.ghostty`. Keep that common file limited to appearance and terminal behavior; put environment-selection commands in the profiles below. Fonts used by Ghostty must be installed or discoverable on the Termux side. Check `ghostty +list-fonts` and `ghostty +list-themes` there.

Save `~/.local/bin/ghostty-debian-shell`:

```bash
#!/data/data/com.termux/files/usr/bin/bash
set -eu
termux_prefix=${PREFIX:-/data/data/com.termux/files/usr}
guest_directory=${GHOSTTY_DEBIAN_DIRECTORY:-/home/desktop}
exec "$termux_prefix/bin/proot-distro" login \
    --user desktop --shared-tmp --work-dir "$guest_directory" \
    --env "DISPLAY=${DISPLAY:-:1}" \
    debian -- /bin/bash -l
```

`--shared-tmp` makes the established X11 socket available to guest GUI clients; it is not needed merely to display text from a guest shell. PRoot-Distro constructs the guest environment, so this example passes `DISPLAY` explicitly. Do not copy the Termux process's `LD_LIBRARY_PATH`, `LD_PRELOAD`, `HOME`, or session-bus address into Debian wholesale. To launch GUI applications from this shell as part of the existing GNOME session, also recover that guest session's actual bus/runtime environment using the common desktop launcher. Starting an unrelated D-Bus session for every guest shell does not join GNOME's session. One proposed way, not yet tested: have the desktop launcher write the session's `DBUS_SESSION_BUS_ADDRESS` and `XDG_RUNTIME_DIR` to a file in the guest user's home when GNOME starts and remove it at logout, and have the Debian profile's login shell read it when present. Until that works, `gsettings`, `xdg-open`, `notify-send`, and similar commands from a Debian tab cannot be assumed to reach the running desktop.

Each Debian tab or split runs its own `proot-distro login`: PRoot-Distro's Python launcher, then a PRoot instance separate from the one running GNOME. Measure how long a new tab takes to open.

If the desktop uses the Flatpak report's custom outer PRoot launcher, adapt that launcher's command-entry support here instead of independently entering the rootfs with inconsistent mappings. Do not run one PRoot login from inside another. The example above demonstrates the ordinary PRoot-Distro path; it does not install the Flatpak compatibility layers.

Save `~/.config/ghostty/termux.ghostty`:

```ini
config-file = config.ghostty
command = direct:/data/data/com.termux/files/usr/bin/bash -l
class = com.mitchellh.ghostty.termux
title = Termux
working-directory = home
window-inherit-working-directory = false
tab-inherit-working-directory = false
split-inherit-working-directory = false
```

Save `~/.config/ghostty/debian.ghostty`:

```ini
config-file = config.ghostty
command = direct:/data/data/com.termux/files/home/.local/bin/ghostty-debian-shell
class = com.mitchellh.ghostty.debian
title = Debian
working-directory = home
window-inherit-working-directory = false
tab-inherit-working-directory = false
split-inherit-working-directory = false
```

The inheritance settings deliberately give predictable directories: the native profile starts in the Termux home; the Debian helper selects a guest directory. These examples do not promise that opening a tab copies the previous Debian tab's current directory. That needs a tested translation of guest shell-integration paths into host launch requests. The fixed titles identify launch intent; use a distinct prompt to show the shell's actual environment after manual environment changes.

Save `~/.local/bin/ghostty-launch`:

```bash
#!/data/data/com.termux/files/usr/bin/bash
set -eu
termux_prefix=${PREFIX:-/data/data/com.termux/files/usr}
mode=${1:-termux}
case "$mode" in
    termux) test "$#" -le 1 ;;
    debian) test "$#" -le 2 ;;
    *) printf '%s\n' 'Usage: ghostty-launch termux | debian [guest-directory]' >&2; exit 2 ;;
esac
if test "$mode" = debian; then
    export GHOSTTY_DEBIAN_DIRECTORY="${2:-/home/desktop}"
    case "$GHOSTTY_DEBIAN_DIRECTORY" in
        /*) ;;
        *) printf '%s\n' 'The Debian directory must be an absolute guest path.' >&2; exit 2 ;;
    esac
fi
export DISPLAY="${DISPLAY:-:1}"
export GDK_BACKEND=x11
unset WAYLAND_DISPLAY
cd -- "$HOME"
exec "$termux_prefix/bin/dbus-run-session" -- "$termux_prefix/bin/ghostty" \
    --config-default-files=false \
    --config-file="$HOME/.config/ghostty/$mode.ghostty" \
    --gtk-single-instance=false
```

Make both scripts executable and launch either mode:

```bash
chmod 700 "$HOME/.local/bin/ghostty-launch" "$HOME/.local/bin/ghostty-debian-shell"
"$HOME/.local/bin/ghostty-launch" termux
"$HOME/.local/bin/ghostty-launch" debian
# Optional initial directory, interpreted inside Debian:
"$HOME/.local/bin/ghostty-launch" debian '/home/desktop/Project files'
```

Each invocation owns a small native D-Bus session for Ghostty. An established Termux session bus can be reused instead after validating its environment; the per-launch bus keeps the example independent of that setup. Its address is not the Debian desktop's bus address.

`config-default-files=false` selects only the explicit profile, which includes the common appearance file. Included configuration is loaded later, so keep `command`, `initial-command`, and profile-specific options out of that common file. These profiles do not require changing the default command for the ordinary Termux Android terminal. [Configuration loading in 1.3.1](https://github.com/ghostty-org/ghostty/blob/v1.3.1/src/config/Config.zig#L2425)

With the helper's `exec`, exiting the Debian shell normally closes that terminal. To return to a native prompt on `exit`, open a native Ghostty terminal first and run the guest login as a command within its shell. That is a different, useful workflow from a dedicated Debian-only profile.

## Shortcuts for both

### Android home-screen shortcuts

Use **Termux:Widget** to invoke the native-host launcher. For example, save these as two executable scripts under Termux's `~/.shortcuts/tasks/`:

`ghostty-termux`:

```bash
#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/home/.local/bin/ghostty-launch termux
```

`ghostty-debian`:

```bash
#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/home/.local/bin/ghostty-launch debian
```

Create that directory if needed, make the scripts executable, and refresh the widget. Termux:Widget runs `tasks` scripts in the background; scripts directly under `~/.shortcuts/` open a Termux terminal session. Use a Termux:Widget installation compatible with the installed Termux app's signing source, and keep the full Termux shebangs. [Widget installation and script directories](https://github.com/termux/termux-widget#readme)

These shortcuts assume the chosen X11 display is already ready. For launch from a stopped session, have both call the same session starter first: start/reuse Termux:X11, wait for a real display-readiness check, start/reuse the desktop if desired, then run the selected profile. Opening the Termux:X11 Android activity and starting the X server are distinct steps. Do not start another GNOME desktop or X server on every terminal shortcut click.

### Desktop menu entries and keyboard shortcuts

In a **native Termux desktop**, `.desktop` entries can execute the two fixed commands directly:

```ini
[Desktop Entry]
Type=Application
Name=Ghostty — Termux
Exec=/data/data/com.termux/files/home/.local/bin/ghostty-launch termux
Terminal=false
Categories=System;TerminalEmulator;
StartupWMClass=com.mitchellh.ghostty.termux
```

Create another entry with `Name=Ghostty — Debian`, `Exec=…/ghostty-launch debian` using the full path, and `StartupWMClass=com.mitchellh.ghostty.debian`. Save them under that desktop user's `~/.local/share/applications/`. Do not copy the packaged `DBusActivatable=true` setting: these entries must execute the selected wrapper. Keyboard shortcuts can invoke the same two commands.

In a **Debian PRoot desktop**, a menu entry runs inside the guest. Merely placing the native binary's path in `Exec` does not establish that the new process runs outside the PRoot tracer with the correct host environment. Use a host-side launch bridge. This is additional integration work beyond the two native-host profiles.

One existing mechanism is **OpenSSH over loopback**: run the server in native Termux, have the guest connect to it, and let the server invoke the native wrapper. That creates a new outer PRoot session for the Debian shell, avoiding nested PRoot. Configure the native server for loopback, key authentication, and a known host key. The Termux SSH package normally uses port `8022`; use the actual configured port. [Termux OpenSSH packaging](https://github.com/termux/termux-packages/tree/master/packages/openssh), [OpenSSH server options](https://man.openbsd.org/sshd_config)

For example, after configuring a guest SSH host alias `termux-host` with the actual Termux username, `HostName 127.0.0.1`, port, identity, and verified host key, these are fixed guest-side commands:

```bash
ssh -T termux-host /data/data/com.termux/files/home/.local/bin/ghostty-launch termux
ssh -T termux-host /data/data/com.termux/files/home/.local/bin/ghostty-launch debian
```

The guest `.desktop` entries can use `/usr/bin/ssh -T termux-host …` as `Exec`, with `Terminal=false`. Give each a `StartupWMClass` matching its profile's `class` so the panel groups the windows with their launchers, and an `Icon` the guest can resolve: without a guest Ghostty package the guest has no Ghostty icon, so copy it from the Termux package. Configure authentication before relying on a graphical entry; an invisible password or host-key prompt is not a working launcher. The SSH connection lasts for the foreground Ghostty invocation in this simple design. A local socket dispatcher started outside PRoot is another option if an SSH server is unwanted; that dispatcher still needs implementation, lifecycle handling, and testing.

Bind one desktop key combination to each entry if desired. Choose the default terminal action separately from whether both entries exist. Under the original Debian-focused report, “Debian” is the sensible default, while “Termux” remains explicitly available.

## Nautilus directories and the default terminal

For **Open in Debian Terminal**, keep the selected directory as a **guest path** and pass it to the Debian login's working-directory mechanism. Do not send `/home/desktop/Project files` to the native Ghostty process's `--working-directory`: that path is resolved on the Termux side. The sample host launcher already accepts a guest directory as its second argument after `debian`.

For a guest-to-host bridge, transport variable paths as data. OpenSSH remote command arguments ultimately pass through a remote shell, so a local argument list alone does not solve remote quoting. A small fixed dispatcher reading a JSON request on standard input is a suitable design: validate the mode and absolute directory, then invoke `ghostty-launch` with a subprocess argument array. Do not concatenate a Nautilus path into a shell command, and do not `eval` it. [OpenSSH command handling](https://man.openbsd.org/ssh)

For **Open in Termux Terminal**, define what the selected guest directory should mean. A practical first version opens the Termux home. Preserving the selected directory requires an explicit shared-folder mapping. A guest `/home/desktop` is not Termux's home, and guest bind mounts or emulated symlinks make string-prefix conversion unreliable. Avoid treating the guest rootfs's host storage path as a general native working directory.

The package's Nautilus extension invokes `ghostty --working-directory=…` in its own environment. It does not implement this bridge or translate guest paths. Without a guest Ghostty package, the guest does not have this extension at all; copy it from the Termux package only if a guest wrapper named `ghostty` will implement the interface it calls. Neither does the repository's [Debian alternatives hook](https://github.com/cnshing/debian-livecd/blob/cd769287d6511b90d54ad7682416b201e4c44e2f/overlays/Terminal/lb/hooks/normal/2900-register-ghostty-terminal.hook.chroot.overlay.tmpl). For a PRoot profile, register a real guest wrapper implementing the terminal argument interface needed by the caller, or provide a dedicated Nautilus action. Do not register an absent `/usr/bin/ghostty` or fabricate a man-page slave for a host-only package. Keep administrative terminal actions excluded as in the parent report.

## If Ghostty itself should run inside PRoot

That is a valid fourth arrangement, rather than a requirement for a Debian shell. Install a **Debian/glibc-compatible build for the guest architecture** inside Debian, run it with the existing guest display/session environment, and keep its config/fonts in the Debian user's home. Installing the Termux `.deb` into Debian does not supply this: its ABI, dependencies, and install prefix target Termux.

The existing [Terminal overlay](https://github.com/cnshing/debian-livecd/blob/cd769287d6511b90d54ad7682416b201e4c44e2f/overlays/Terminal/repos/griffo-free.yaml) selects griffo's Trixie repository, whose arm64 index has no `ghostty` package; its amd64 index publishes `1.3.1-6~trixie`. Debian's own archive does not package Ghostty either. In an arm64 guest this arrangement therefore means a Zig source build, plus keeping it current. Graphics are a smaller difference: GNOME Shell already needs a working guest OpenGL path, and a guest Ghostty would need OpenGL 4.3 from it. [griffo arm64 index](https://deb-free.griffo.io/apt/dists/trixie/main/binary-arm64/Packages), [Debian package search](https://packages.debian.org/search?keywords=ghostty&searchon=names&suite=all&section=all)

| Preference | Reasonable choice | Remaining effort |
| --- | --- | --- |
| Native tools and Termux shell | Native Ghostty → Termux Bash | Package/display/GL validation; host config and fonts |
| Debian command-line tools | Native Ghostty → existing Debian login | Small host helper; correct guest user, paths, and session environment |
| Both shell environments | Two profiles using native Ghostty | Low host-launcher cost; moderate guest menu/Nautilus bridge work |
| Every desktop executable managed by Debian | Debian Ghostty → Debian shell | Source build (no arm64 package found); guest OpenGL 4.3 and PRoot process compatibility |
| Fallback when Ghostty does not render acceptably | Debian gnome-terminal → Debian shell | Low; joins the GNOME session and Nautilus without a bridge |
| No graphical display needed | Ordinary Termux Android terminal, optionally entering Debian | Ghostty and Termux:X11 are unnecessary for this workflow |

A native renderer avoids tracing Ghostty's own work; Debian programs launched in its terminals retain PRoot overhead. This is an architectural benefit, not a measured speed or battery claim. A guest Ghostty may simplify guest file-manager integration while increasing the number of components depending on guest compatibility.

## Configuration boundaries and acceptance checks

Keep shared visual preferences where appropriate, but maintain separate Termux and Debian shell startup files, package environments, and homes. `pkg` should resolve to Termux tools in the native shell; `apt` and guest executables should resolve to Debian tools in the guest shell. A PRoot root prompt does not grant Android root privileges.

Ghostty's GTK/libadwaita window uses the native process's settings and accessible assets. Copying Debian's Ghostty color configuration does not also migrate GNOME's dconf preferences, WhiteSur CSS, icon theme, or fonts into Termux. Assess matching window appearance separately, and keep host configuration paths distinct from guest paths. URL opening and clipboard behavior also cross this boundary: check which host opener handles links, whether local file links need path translation, and whether the Termux:X11 clipboard reaches Android as intended.

The repository's `term = xterm-256color` is a practical starting point for both profiles. If switching to `xterm-ghostty`, install its terminfo in each environment that interprets `$TERM`, including remote SSH targets. Native package installation alone does not install it into Debian. Ghostty recognizes the shell for automatic integration from the command's executable name, so it does not inject integration when the command is `ghostty-debian-shell`. The repository's `shell-integration-features = no-cursor` therefore has no effect in the Debian profile; source compatible integration in the guest if wanted. [Shell detection in 1.3.1](https://github.com/ghostty-org/ghostty/blob/v1.3.1/src/termio/shell_integration.zig#L136-L165) Keep current-directory inheritance disabled until its cross-environment behavior is tested.

Before calling this integrated, verify:

1. **Package and graphics:** record installed package versions, device/GPU, the Mesa driver Ghostty actually uses (llvmpipe, Zink, or VirGL), and the driver variables in its environment; open a terminal, render text, resize, scroll, copy/paste, and close it normally. Typing and scrolling must stay responsive at the everyday resolution. Confirm fonts and required image transports.
2. **Native identity:** the native profile has the Termux home/prefix, a Termux Bash, and native package commands. It must still work when Debian is not installed or its launcher fails.
3. **Guest identity:** the Debian profile reaches the intended user/home and guest release. Run `pwd`, `id`, `command -v bash`, and `cat /etc/os-release` there; a title alone proves nothing.
4. **Every new surface:** test windows, tabs, and splits after launching both profiles in either order. Each must use its selected environment; opening one must not silently inherit the other's command.
5. **Paths:** test home, a shared folder, an absent directory, and paths with spaces, quotes, Unicode, and shell metacharacters. A failed requested directory must be reported instead of silently opening another directory.
6. **Guest desktop bridge:** menu, keybinding, and Nautilus launches must start Ghostty outside PRoot and enter the correct guest path. Check guest GUI applications launched from the terminal use the intended session bus/runtime environment.
7. **Lifecycle:** test shell exit, closing windows, repeated shortcut clicks, desktop logout, and display restart. Record whether terminal sessions survive desktop logout; do not let one terminal wrapper terminate the shared desktop or X server. Native Ghostty, its shells, and every PRoot process it starts count toward Android's phantom-process limit together with the GNOME session; test several open tabs with the full desktop running. See the [PRoot assessment](termux-proot-analysis.md#12-android-input-storage-and-lifecycle).

Local checks passed for the Bash examples' syntax, mock launches of both profiles, directory arguments containing spaces/quotes/Unicode/shell metacharacters, invalid argument rejection, the sample desktop entry, and relative documentation links. These check the examples' structure and argument handling without executing Ghostty or PRoot on Android.

The source review supports the package behavior and proposed launcher design. The later [device follow-up](termux-device-validation.md) records native software rendering, separate host/guest appearance and settings buses, actual shell identities on each surface, the Nautilus bridge, and lifecycle tests for the implemented profile. Physical keyboards/IME, native GPU rendering, and sustained performance remain open.
