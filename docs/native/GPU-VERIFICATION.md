# Native Turnip + Zink verification

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

> Recorded before the repository restructure. Paths were updated, but build steps and
> install locations describe the earlier on-device flow.

Tested on the Note10+ SM-N975U1,
Android 11, `Adreno640v2`. This follows the initial
[native desktop verification](VERIFICATION.md). GPU rendering is now an explicit
native renderer mode; neither its startup nor its applications enter PRoot.

The phone is left running the **native backend with Zink selected as its
default renderer**. `selected.json`, `final-start.json` and `final-inventory.json`
record that state; plain `livecd start` follows it. `livecd start --safe` uses
native llvmpipe recovery, and an explicit `--renderer software` starts the normal
desktop on the CPU. Debian remains stopped on disk as optional recovery data.

## Driver and compositor integration

The official Termux `mesa-vulkan-icd-freedreno` **26.2.6** and `vulkan-tools`
**1.4.366** packages were downloaded and checked against their APT-index SHA-256
values. `gpu-setup.py` now takes them through APT at the installed Mesa's version. Their Bionic
files are staged privately under `~/.local/opt/livecd-native/gpu-26.2.6`, with an
owned `gpu` selector. The GPU work did not install or replace shared APT packages;
an unrelated native package download was allowed to continue.

The installed native Mesa **26.2.6** supplies Zink. The private Turnip ICD is
selected explicitly with `VK_DRIVER_FILES` / `VK_ICD_FILENAMES`. The generic
Vulkan loader and native dependencies were already installed. The recursive
audit including the GPU driver/tools resolves **178 ELF files with no missing
dependencies** (`evidence/gpu/elf-audit.json`). Executable interpreters are native
Android `/system/bin/linker64`.

Initial Vulkan and GL context queries worked, but Mutter's **GLX compositor path
produced black application windows**. These results were not accepted as a usable
desktop. Disabling vblank, forcing immediate presentation, using software WSI,
and changing Termux:X11's legacy drawing mode did not resolve those windows.

Selecting **`COGL_DRIVER=gles2`** fixed the compositor's application display.
Mutter's [X11 renderer selection](https://github.com/GNOME/mutter/blob/48.1/src/backends/x11/meta-renderer-x11.c)
chooses EGL for this driver; the runtime reports that it is not using GLX TFP.
The accepted profile uses EGL/GLES for Shell, Zink/Turnip underneath, GTK4's GL
renderer, and Termux:X11's normal drawing mode. The final profile does **not**
force immediate presentation, disable vblank, or enable software WSI.

Compositor captures and a real Android screenshot after the user opened
Termux:X11 establish visible editor content. X11 framebuffer readback sometimes
returned the desktop background without the GPU application window, so the
tests now use the compositor's screenshot API (`capture.py`). This neither
enables Shell's unsafe evaluation mode nor changes its screenshot access policy.

## Accepted application and rendering checks

Evidence is under `evidence/gpu/` (`temp/docs/evidence/native/gpu`). Failed probes remain there
with names describing their attempted configuration or test failure.

| Check | Observed result |
| --- | --- |
| Native GPU access | The native Termux app opens `/dev/kgsl-3d0`; GPU reports `Adreno640v2` |
| Vulkan device | **Turnip Adreno (TM) 640**, device Vulkan **1.3.354**, Mesa **26.2.6**. Loader/instance version 1.4.366 is a separate value |
| OpenGL | **OpenGL 4.6**, `zink Vulkan 1.3(Turnip Adreno (TM) 640 (MESA_TURNIP))`, `Accelerated: yes` |
| Native core validation | `core-final.json`: **27 checks pass**, including eight extensions, actual Shell Turnip mapping, KGSL descriptor, EGL/GLES selection and no running PRoot |
| Editor and Nautilus GPU rendering | `gpu-apps.json`: each actual GUI process maps the private Turnip driver and holds a KGSL descriptor; compositor screenshots show their contents |
| Native application workflows | `apps.json`: editor save, Nautilus browse/rename/copy/trash, Firefox local and HTTPS pages, audio sink monitor, and Writer GUI edit/save all pass |
| Writer output | 10,268-byte ODT; typed text verified inside `content.xml` after native GUI save |
| Ghostty | Actual GPU process, real native UID/home, typed shell command, screenshot, then shell exit closes its window |
| mpv GPU video | Native `gpu-next`, **Vulkan / x11vk**, PulseAudio, software decoding explicitly selected; actual Turnip mapping/KGSL descriptor and visible generated video |
| Vulkan cube and GLX animation | Real native windows, verified GPU processes; **60.62 seconds** of concurrent rendering with overview transitions, unchanged Shell PID and a final compositor capture |
| Per-client software override | `client-software-override.txt`: llvmpipe, `Accelerated: no`, while the desktop remains on Zink |
| Setup/session exclusion | `setup-running-refusal.log`: GPU setup rejects the running managed desktop before modifying driver files |
| Stopped installer rerun | `setup-rerun.json`: private driver/tools staged again from verified inputs; subsequent GPU startup and validation pass |
| Repeated lifecycle and isolation | `lifecycle.jsonl`: ten GPU start/stop cycles, **8.145–12.351 s**, median **9.358 s**; repeated start is idempotent and an unrelated process survives |
| Crash and recovery | Forced GPU Shell death cleans its session; `--safe` starts software and passes validation; normal startup returns to the saved Zink mode |
| Default GNOME Terminal | `terminal.json`: literal Unicode/quote/shell-syntax paths, real native UID, and both shell exit and WM close terminate the window, launcher and Bash |
| Appearance and CSS ownership | `appearance.json`: light/red and dark/yellow switching pass; regular user CSS and unrelated broken symlinks survive |

The concurrent animation sample produced GLX five-second averages of
**46.964–59.746 FPS**, with normal synchronization enabled. Across that sample,
Shell used about **40.7% of one CPU core**, cube 5.1%, and gears 12.0%. Shell RSS
was approximately **245–247 MiB**. This includes compositor copies, two active
clients and overview transitions. It is not a controlled comparison with
software rendering, a prediction for games, or a whole-device energy benchmark.

The first demo test assumed a client `_NET_WM_PID` and then an incorrect cube
window title. The shipped Vulkan demo reports **`Vkcube X11`**, and Mutter's
frame-helper windows can publish their own PID. The corrected test locates the
actual named window and independently verifies the launched rendering process.
ADB port forwarding also reset during probes; later commands used direct LAN
SSH with the same server key verified through the established ADB connection.

The first safe-mode validation reached the extension helper before startup had
settled; that helper disconnected, while a later validation passed. The owner
now waits for `org.gnome.SessionManager.IsSessionRunning` before activating the
extension helper and declaring readiness. Another complete ten-cycle run,
crash recovery and immediate safe/normal validations passed with that change.
These measurements are complete **start/stop cycle times**, not startup-only
times. The appearance probe also now dispatches GLib notifications while waiting,
so it observes asynchronous icon-setting updates after the CSS file changes.

## Boundary

Rendering acceleration does not establish hardware video decoding. Browser UI
tests do not establish Firefox WebRender acceleration for every page, WebGL or
video codec. Ghostty's previously documented normal-window-close limitation
is unchanged; this test accepted shell exit.

The compositor still uses the earlier pinned community Shell/Mutter/GJS binaries.
No complete source rebuild, newer GNOME patch level or new graphics kernel was
introduced. The EGL path does not establish zero-copy pixmap import, and CPU
presentation/copy overhead remains. Multi-hour sessions, thermal endurance,
rotation, reboot and newer Android/device combinations need separate validation.

Commands, renderer selection and native software recovery are in
[README.md](README.md#native-turnip--zink).
