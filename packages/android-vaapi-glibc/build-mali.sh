#!/bin/bash
# Build only the private VA driver with the NDK's Clang targeting Debian glibc.
# Usage: build-mali.sh SOURCE SYSROOT BUILD STAGE
set -euo pipefail
source_dir=$(realpath "$1")
sysroot=$(realpath "$2")
mkdir -p "$3" "$4"
build_dir=$(realpath "$3")
stage=$(realpath "$4")
meson=${TERMUX_MESON:-meson}
python3 - "$build_dir/cross.ini" "$sysroot" <<'PY'
import os
from pathlib import Path
import shlex
import sys
out, root = sys.argv[1:]
# Do not inherit Termux's Android headers, libc++, flags or pkg-config paths.
flags = ['--target=aarch64-linux-gnu', '--sysroot=' + root, '--gcc-toolchain=' + root + '/usr']
# Only flags a compile uses belong on the compilers: Meson's Clang checks compile with
# -Werror=unused-command-line-argument, so a linker flag there fails every one of them.
binaries = {'c': shlex.split(os.environ['CC']) + flags,
            'cpp': shlex.split(os.environ['CXX']) + flags + ['-stdlib=libstdc++'],
            'c_ld': 'lld', 'cpp_ld': 'lld',
            'ar': shlex.split(os.environ['AR']), 'strip': shlex.split(os.environ['STRIP']),
            'pkg-config': ['/usr/bin/pkg-config']}
text = '[binaries]\n' + ''.join(f'{key} = {value!r}\n' for key, value in binaries.items())
text += "[built-in options]\nc_link_args = ['-rtlib=libgcc']\ncpp_link_args = ['-rtlib=libgcc']\n"
text += "[host_machine]\nsystem = 'linux'\ncpu_family = 'aarch64'\ncpu = 'aarch64'\nendian = 'little'\n"
text += f"[properties]\nneeds_exe_wrapper = true\nsys_root = {root!r}\n"
text += f"pkg_config_libdir = {[root + '/usr/lib/aarch64-linux-gnu/pkgconfig', root + '/usr/share/pkgconfig']!r}\n"
Path(out).write_text(text)
PY
# The builder exports Android flags globally; a glibc sub-build must not use them.
unset CC CXX AR AS LD STRIP RANLIB CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
unset PKG_CONFIG PKG_CONFIG_PATH PKG_CONFIG_LIBDIR PKG_CONFIG_SYSROOT_DIR
# X11 only: the VA frontend needs no Wayland, and Mesa's Wayland code wants a wayland-scanner of
# exactly the sysroot's Wayland version, which the builder (x86_64) cannot run from Debian arm64.
# The builder has no meson on PATH: the recipe passes termux_setup_meson's command.
$meson setup "$build_dir/mesa" "$source_dir" --cross-file "$build_dir/cross.ini" \
  --prefix=/usr --libdir=lib/aarch64-linux-gnu --buildtype=release --wrap-mode=nodownload \
  -Dauto_features=disabled -Dplatforms=x11 -Dgallium-drivers=softpipe -Dvulkan-drivers= \
  -Dgallium-va=enabled -Dtermux-va-bridge=enabled \
  -Dvideo-codecs=h264dec,h265dec,vp9dec,av1dec,h264enc,h265enc \
  -Dllvm=disabled -Ddraw-use-llvm=false -Dglx=disabled -Degl=enabled -Dgles1=disabled \
  -Dgles2=enabled -Dopengl=true -Dgbm=enabled -Dglvnd=disabled -Dxmlconfig=disabled \
  -Dbuild-tests=false -Dtools= -Dspirv-tools=disabled || {
    # The builder keeps no build directory; without this a failed check leaves nothing to read.
    tail -n 150 "$build_dir/mesa/meson-logs/meson-log.txt" >&2
    exit 1
  }
ninja -C "$build_dir/mesa" -j "${TERMUX_PKG_MAKE_PROCESSES:-2}"
DESTDIR="$stage" ninja -C "$build_dir/mesa" install
