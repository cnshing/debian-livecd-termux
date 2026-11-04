# Loupe

The default `Image Viewer` overlay installs Loupe and selects it for supported
image types in the private GNOME profile's `mimeapps.list`. Other associations
and added application choices are retained. The overlay follows the package
selection in [debian-livecd's Image Viewer overlay](https://github.com/cnshing/debian-livecd/tree/main/overlays/Image%20Viewer).

`packages/loupe` builds GNOME Loupe 51.1 from its checksummed release archive.
Glycin 4 selects its built-in image-rs decoder on Android. This needs no external
Glycin loaders, Bubblewrap or libseccomp. Decoding runs inside the viewer process.
JPEG, PNG/APNG, GIF, WebP, TIFF, BMP, ICO, JPEG 2000, QOI and the other image-rs
formats are available. SVG, HEIF/AVIF and JPEG XL need external loaders and are
excluded from this package's desktop MIME types.

The Meson patch keeps Cargo's locked dependencies, uses the Android cross target
and caches compiled crates. Meson installs the upstream desktop entry, D-Bus
activation service, translations, icons and GSettings schema.

Build on a host with Docker or Podman:

```sh
bash tools/build-packages.sh loupe
```

Or build and install in native Termux with the desktop stopped:

```sh
bash tools/build-packages.sh --install loupe
python src/apply-overlays.py "Image Viewer"
```

The default installer applies this overlay automatically once Loupe is available
in the project's package repository. For a separately built `.deb`, install it
with `apt-get install /absolute/path/to/loupe_51.1_aarch64.deb` first.
