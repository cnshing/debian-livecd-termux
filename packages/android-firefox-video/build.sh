TERMUX_PKG_HOMEPAGE=https://www.mozilla.org/firefox
TERMUX_PKG_DESCRIPTION="Firefox's KGSL and Mali graphics probe and private VA-API FFmpeg codecs for Android"
TERMUX_PKG_LICENSE="LGPL-2.1, MPL-2.0"
TERMUX_PKG_LICENSE_FILE="COPYING.LGPLv2.1"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="9.0.2"
TERMUX_PKG_REVISION=4
TERMUX_PKG_SRCURL="https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/tags/n${TERMUX_PKG_VERSION}"
TERMUX_PKG_SHA256=6e374ed621e48faa40639307dff48ba6fe574a509977956d2cce9669b7cc27e9
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_EXCLUDED_ARCHES="arm, i686, x86_64"
# Firefox on PanVK needs the VA driver's own Gallium variable and Zink's dma-buf fence fix.
TERMUX_PKG_DEPENDS="firefox, android-vaapi (>= 27.0.0~devel20261029-8), libc++, libdrm, libva, libx11, libxrandr, mesa (>= 26.2.6-103)"
TERMUX_PKG_BUILD_DEPENDS="libnspr"

termux_step_post_get_source() {
	local commit path sha name
	commit=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$TERMUX_PKG_BUILDER_DIR/probe.lock.json")
	mkdir -p gfx/mozilla
	while read -r path sha name; do
		termux_download "https://raw.githubusercontent.com/mozilla-firefox/firefox/$commit/$path" \
			"$TERMUX_PKG_CACHEDIR/probe-$sha" "$sha"
		cp "$TERMUX_PKG_CACHEDIR/probe-$sha" "gfx/$name"
	done < <(python3 - "$TERMUX_PKG_BUILDER_DIR/probe.lock.json" <<-'PY'
		import json,sys
		from pathlib import Path
		for item in json.load(open(sys.argv[1]))['files']:
		    name = Path(item['path']).name
		    print(item['path'], item['sha256'], 'mozilla/' + name if name == 'GfxInfoUtils.h' else name)
	PY
	)
	cp "$TERMUX_PKG_BUILDER_DIR/mozilla/ScopeExit.h" gfx/mozilla/
	python3 "$TERMUX_PKG_BUILDER_DIR/stage.py" patch gfx
}

termux_step_configure() {
	# Keep the desktop FFmpeg command and mpv's libraries separate. Firefox loads
	# these versioned libraries through its own application environment only.
	"$TERMUX_PKG_SRCDIR/configure" \
		--prefix="$TERMUX_PREFIX/lib/android-firefox-video/ffmpeg" \
		--target-os=android --arch=aarch64 --enable-cross-compile \
		--cc="$CC" --cxx="$CXX" --ar="$AR" --nm="$NM" --ranlib="$RANLIB" --strip="$STRIP" \
		--pkg-config="$PKG_CONFIG" \
		--extra-cflags="$CFLAGS --target=aarch64-linux-android29" \
		--extra-ldflags="$LDFLAGS --target=aarch64-linux-android29 -Wl,-rpath,$TERMUX_PREFIX/lib/android-firefox-video/ffmpeg/lib" \
		--disable-autodetect --disable-programs --disable-doc --disable-debug \
		--disable-static --enable-shared --disable-symver --enable-pic \
		--disable-encoders --disable-muxers --disable-demuxers --disable-protocols \
		--enable-encoder=h264_vaapi,hevc_vaapi,vp9_vaapi \
		--disable-devices --disable-filters --disable-avdevice --disable-avfilter \
		--disable-avformat --disable-network --enable-vaapi \
		--enable-hwaccel=hevc_vaapi,h264_vaapi,vp9_vaapi,av1_vaapi,vp8_vaapi
}

termux_step_make() {
	make -j "$TERMUX_PKG_MAKE_PROCESSES"
	# The runtime must advertise actual encoders, not only the VA probe's profiles.
	local codec
	for codec in H264 HEVC VP9; do
		grep -qx "#define CONFIG_${codec}_VAAPI_ENCODER 1" config_components.h
	done
	$CXX $CPPFLAGS $CXXFLAGS --target=aarch64-linux-android29 -std=c++17 -DMOZ_X11 -DMOZ_ENABLE_VAAPI \
		-I"$TERMUX_PKG_SRCDIR/gfx" -I"$TERMUX_PREFIX/include/nspr" \
		"$TERMUX_PKG_SRCDIR/gfx/gfxtest.cpp" "$TERMUX_PKG_SRCDIR/gfx/glxtest.cpp" \
		"$TERMUX_PKG_SRCDIR/gfx/vaapitest.cpp" $LDFLAGS --target=aarch64-linux-android29 \
		-lva -lX11 -lXrandr -ldl -o gfxtest
}

termux_step_make_install() {
	make install
	local private="$TERMUX_PREFIX/lib/android-firefox-video"
	install -Dm755 gfxtest "$private/application/gfxtest"
	python3 "$TERMUX_PKG_BUILDER_DIR/stage.py" install "$TERMUX_PREFIX" "$private"
	python3 - "$private/manifest.json" <<-'PY'
		import json, sys
		from pathlib import Path
		path = Path(sys.argv[1])
		manifest = json.loads(path.read_text())
		manifest['encoding'] = {'input': 'i420', 'codecs': ['h264', 'hevc', 'vp9']}
		path.write_text(json.dumps(manifest, indent=2) + '\n')
	PY
	# No compiler headers or pkg-config entries are needed at runtime.
	rm -rf "$private/ffmpeg/include" "$private/ffmpeg/lib/pkgconfig" "$private/ffmpeg/share"
	# Firefox dlopens these ABI versions. Refuse an artifact whose build lost them.
	test -f "$private/ffmpeg/lib/libavcodec.so.63"
	test -f "$private/ffmpeg/lib/libavutil.so.61"
}
