# Opt-in Ghostty GTK GL DMA-BUF package

`ghostty-panvk-dmabuf` installs the exact private stack qualified on Galaxy S20
`x1s` (Mali-G77, Android 13, Linux 4.19.87, kbase JM 11.35, Termux aarch64).
It provides its own command and libraries. Installing it does not change the
desktop controller, normal `ghostty`, system GTK/Mesa, global Vulkan ICDs or
default terminal selection. Python, Ghostty 1.4.0 or later, normal GTK resources
and the declared Termux library dependencies must already be available or
installed by apt.

Download both artifacts from the manual **Ghostty opt-in DMA-BUF package**
Actions run: the binary package and its complete corresponding source bundle.
Check their `SHA256SUMS`, copy the `.deb` to Termux, then:

```sh
apt install ./ghostty-panvk-dmabuf_1.0-2_aarch64.deb
ghostty-panvk-dmabuf --check
# In the environment of an existing X11 desktop (DISPLAY, XAUTHORITY, D-Bus):
ghostty-panvk-dmabuf
# Remove only the opt-in package:
apt remove ghostty-panvk-dmabuf
```

The command starts a separate Ghostty process with GTK's GL renderer. It verifies
its library checksums and device ABI before starting. It forces Zink's opt-in
LINEAR backing allocation, the tested SYNC_FD/workgroup driver and synchronous
dma-buf fence fallback. Kernel 4.19.87 rejects dma-buf IMPORT/EXPORT_SYNC_FILE;
the Mesa wait fallback remains necessary even with Vulkan semaphore support.
Shader caching stays disabled because this exact four-patch workgroup driver
predates the cache identity fix. Avoid `--gtk-single-instance` options; the
launcher owns instance separation. Other Ghostty arguments, including `-e`,
are forwarded normally.

**Opt-in scope includes this terminal and its descendants.** Shells, applications
and URL helpers launched from it inherit the experimental graphics environment.
Ghostty 1.4's `--env=KEY=` removes a configured override, but cannot unset a
variable inherited from Ghostty itself; this launcher does not use it as an
isolation mechanism. Use an ordinary terminal to launch applications with the
normal graphics environment. The caller and other desktop processes keep their
original environment.
This follows Ghostty 1.4's [environment map parser](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/config/RepeatableStringMap.zig)
and [child environment overrides](https://github.com/ghostty-org/ghostty/blob/v1.4.0/src/termio/Exec.zig).
The launcher joins an existing X11 session; it does not start or modify one.
Use the ordinary desktop terminal entry when this experimental path is unwanted.

Validation established fresh terminal captures and GPU buffer mappings, actual
GTK `GL_TEXTURE_2D` DMA-BUF imports, no GTK CPU downloads, and clean exit in a
private X11/SHM session. SHM presentation can copy elsewhere in the pipeline;
this is not a claim of end-to-end zero-copy or general Vulkan/GL conformance.
Nested workgroup barriers and other devices remain outside this qualification.
The package uses the original four workgroup patches, not newer standalone
workgroup fixes or the nested barrier prototype.

## Reproducing the package

On an Ubuntu runner with `gh`, `curl`, Python 3.11+, `dpkg-deb`, and an Actions
read token, run from this repository:

```sh
python3 tools/ghostty-dmabuf/fetch.py work
python3 tools/ghostty-dmabuf/package.py work/inputs dist --sources work/sources
python3 tools/ghostty-dmabuf/test.py --deb dist/ghostty-panvk-dmabuf_1.0-2_aarch64.deb
```

`lock.json` pins original runs, exact `.deb` hashes, runtime hashes, source trees
and upstream archives. Expired or missing inputs fail; a new build must be
reviewed and requalified before updating the lock. Assembly preserves all
tested library bytes. Only private ICD metadata, X11 soname aliases, the launcher
and documentation are new. No maintainer scripts, alternatives or post-install
configuration run. The linker stubs referenced by the driver's original
RUNPATH are deliberately absent.

## Rebuilding the libraries from the companion source bundle

Extract `*_sources.tar.gz` and verify `sources/SHA256SUMS`. It contains the
complete GTK/Mesa upstream archives, reconstructed PanVK base source, exact
project snapshots for each build, the pinned Termux and Zenith repositories,
and this packaging code. All modifications and build scripts are included;
the source bundle can be retained independently of Actions artifact expiry.
The `packaging-recipes-*.tar.gz` snapshot contains this entire repository at
the assembly revision, including the packaging workflow and tests. Use that
snapshot's directory layout when rerunning packaging scripts.

* GTK: extract the `gtk-recipes-8fb9...tar.gz` project snapshot and the
  `termux-recipes-538685...tar.gz` snapshot. Set `GTK_DMABUF_X11_EGL=1` and run
  `tools/panvk-probes/prepare-gtk-dmabuf.py TERMUX_CHECKOUT`. Follow that project's
  `.github/workflows/gtk-dmabuf.yml` with its pinned `tools/termux-build.json`
  builder image, architecture aarch64. The prepared recipe retains the original
  GTK source checksum and all Termux patches except `no-egl.patch`.
* Mesa: use the `mesa-recipes-9ead3...tar.gz` snapshot. Follow its normal recipe
  workflow / `tools/recipes.py prepare TERMUX_CHECKOUT mesa` with the pinned
  Termux builder. `packages/mesa` contains the full patch series through 0026,
  including the failed-fence-handoff wait and opt-in LINEAR allocation patches.
* Driver: use `driver-recipes-593463...tar.gz` and `zenith-recipes-cf70...tar.gz`.
  Follow `.github/workflows/panvk-sync-fd.yml` with `workgroups=true`, selecting
  `android`. That snapshot contains exactly four workgroup patches. The workflow
  reconstructs the p0175 base tree `4a8e9a8cbb34b9fb91a9ad2040319aceb075b973`
  (also supplied as `panvk-prepared-source.tar.zst`), applies SYNC_FD then those
  four patches, and builds the final tree recorded in `lock.json`. Compiler,
  dependency and link metadata from the measured binary are installed in the
  binary package's documentation. Obtain Android NDK r30 and the LLVM 18 native
  tools specified by that workflow; no proprietary driver source is needed.

Rebuilt binaries are candidates requiring device qualification; this packaging
workflow always selects the original measured bytes. GTK's LGPL and Mesa/PanVK
license texts are included in the binary package; full upstream licensing and
individual file copyrights accompany the complete sources. Private dynamic
libraries can be replaced for local modification; update `MANIFEST.json` to
match deliberate changes (which invalidates the recorded qualification).
