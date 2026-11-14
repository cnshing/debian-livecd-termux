TERMUX_PKG_HOMEPAGE=https://github.com/lfdevs/mesa-for-android-container
TERMUX_PKG_DESCRIPTION="Android's hardware video codecs as a VA-API driver, with the GPU as /dev/dri/renderD128 for every program"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_LICENSE_FILE="docs/license.rst"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="27.0.0~devel20261029"
TERMUX_PKG_REVISION=10
TERMUX_PKG_SRCURL=https://codeload.github.com/lfdevs/mesa-for-android-container/tar.gz/eb3e7fd4f009cab04b1482aad4843c0bde28a786
TERMUX_PKG_SHA256=123af0b3b2f7c83273a51f28367a64054201d524cbfa52f99ba76696e619927a
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DEPENDS="libandroid-shmem, libarchive, libc++, libdrm, libva, libwayland, libx11, libxcb, libxext, libxfixes, libxshmfence, termux-va, vulkan-loader, zlib, zstd"
TERMUX_PKG_BUILD_DEPENDS="libarchive, libwayland-cross-scanner, libwayland-protocols, vulkan-headers, xorgproto"
# lfdevs' Mesa fork carries the Termux:VA bridge: a VA-API frontend that hands decoding and encoding
# to the termux-va daemon. Only its VA-API driver is packaged. Termux's own Mesa keeps OpenGL,
# EGL and GBM.
# Build against Termux's libraries only, as the phone builds did: a bundled fallback such as
# libarchive's needs posix_spawn, which Android API 24 lacks.
TERMUX_PKG_EXTRA_CONFIGURE_ARGS="
--wrap-mode=nodownload
-Dauto_features=disabled
-Dplatforms=x11,wayland
-Dgallium-drivers=freedreno,zink,softpipe
-Dvulkan-drivers=
-Dfreedreno-kmds=msm,kgsl
-Dgallium-va=enabled
-Dtermux-va-bridge=enabled
-Dtermux-va-wayland-shim=enabled
-Dvideo-codecs=h264dec,h265dec,vp9dec,av1dec,h264enc,h265enc
-Dllvm=disabled
-Ddraw-use-llvm=false
-Dgallium-rusticl=false
-Dglx=disabled
-Degl=enabled
-Dgles1=disabled
-Dgles2=enabled
-Dopengl=true
-Dgbm=enabled
-Dglvnd=disabled
-Dxmlconfig=disabled
-Dbuild-tests=false
-Denable-glcpp-tests=false
-Dtools=
-Dprecomp-compiler=auto
-Dmesa-clc=auto
-Dspirv-tools=disabled
"

termux_step_pre_configure() {
	termux_setup_wayland_cross_pkg_config_wrapper
	# Android 10's APIs, as the phone builds of this stack used.
	CFLAGS+=" --target=aarch64-linux-android29"
	CXXFLAGS+=" --target=aarch64-linux-android29"
	CPPFLAGS+=" -D__TERMUX__ -D__USE_GNU"
	LDFLAGS+=" --target=aarch64-linux-android29 -landroid-shmem -Wl,-rpath=$TERMUX_PREFIX/lib/android-vaapi"
	# Without /dev/dma_heap/system, as on Android 11 phones, allocate shared buffers through ION.
	cp "$TERMUX_PKG_BUILDER_DIR/tva_ion.h" src/gallium/frontends/va/
	# Without a GPU the bridge can drive (Mali), its software surfaces live in dma-bufs, so
	# browsers can import decoded frames. See tva_ion_winsys.h.
	cp "$TERMUX_PKG_BUILDER_DIR/tva_ion_winsys.h" src/gallium/frontends/va/
	python3 "$TERMUX_PKG_BUILDER_DIR/configure-bridge.py" src/gallium/frontends/va/tva_bridge.c
}

termux_step_make_install() {
	local stage="$TERMUX_PKG_TMPDIR/stage" private="$TERMUX_PREFIX/lib/android-vaapi"
	DESTDIR="$stage" ninja -C "$TERMUX_PKG_BUILDDIR" install
	install -d "$private/dri" "$TERMUX_PREFIX/lib/dri"
	cp -P "$stage$TERMUX_PREFIX"/lib/dri/*_drv_video.so "$private/dri/"
	cp -P "$stage$TERMUX_PREFIX"/lib/libgallium*.so* "$private/" 2>/dev/null || true
	cp -P "$stage$TERMUX_PREFIX/lib/libtva_drm_shim_wayland.so" "$private/"
	test -f "$private/dri/termuxva_drv_video.so"
	# Chromium dlopens the desktop ABI names. Termux's Meson omits those
	# soversions, so expose aliases only in the application's private search path.
	install -d "$private/lib/va-client"
	local library
	for library in va va-drm va-x11; do
		test -f "$TERMUX_PREFIX/lib/lib${library}.so"
		ln -sf "../../../lib${library}.so" "$private/lib/va-client/lib${library}.so.2"
	done
	# libva names a driver after the DRM device, and the render node reports "kgsl". These links
	# in libva's own driver directory let every program find it without settings.
	ln -sf termuxva_drv_video.so "$private/dri/kgsl_drv_video.so"
	ln -sf ../android-vaapi/dri/termuxva_drv_video.so "$TERMUX_PREFIX/lib/dri/kgsl_drv_video.so"
	ln -sf ../android-vaapi/dri/termuxva_drv_video.so "$TERMUX_PREFIX/lib/dri/termuxva_drv_video.so"
	# Presents the GPU's KGSL device as /dev/dri/renderD128, with the sysfs view libdrm reads.
	$CC --target=aarch64-linux-android29 -O2 -Wall -shared -fPIC -U_FORTIFY_SOURCE \
		-o "$private/libandroid-vaapi-render-node.so" "$TERMUX_PKG_BUILDER_DIR/render-node.c"
	local node uevent='DRIVER=kgsl-3d0\nOF_NAME=qcom,kgsl-3d0\nOF_FULLNAME=/soc/qcom,kgsl-3d0@2c00000\nOF_COMPATIBLE_0=qcom,kgsl-3d0\nOF_COMPATIBLE_N=1\nMODALIAS=of:Nqcom,kgsl-3d0T(null)Cqcom,kgsl-3d0\n'
	for node in class/drm/renderD128 dev/char/226:128; do
		node="$private/render-node-sys/$node"
		install -d "$node/device/drm/renderD128"
		printf '226:128\n' > "$node/dev"
		printf 'MAJOR=226\nMINOR=128\nDEVNAME=dri/renderD128\nDEVTYPE=drm_minor\n' > "$node/uevent"
		printf "$uevent" > "$node/device/uevent"
		ln -sfn /sys/bus/platform "$node/device/subsystem"
		printf '226:128\n' > "$node/device/drm/renderD128/dev"
	done
	cat > "$private/manifest.json" <<-JSON
		{"format": 1, "abi": "bionic", "libraries": ["lib/va-client"], "driver_directory": "dri",
		 "preloads": ["libtva_drm_shim_wayland.so"], "session_preload": "libandroid-vaapi-render-node.so",
		 "ion_fallback": "built-in", "encoders": ["h264", "hevc"]}
	JSON
}
