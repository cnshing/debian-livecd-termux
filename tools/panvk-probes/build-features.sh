#!/bin/bash
# Wider upstream tests; compilation only. Runtime failures remain evidence.
set -euo pipefail
zenith=$(realpath "$1")
vk=$(realpath "$2")/include
mkdir -p "$3"
out=$(realpath "$3")
src="$zenith/tests/features"
shaders="$out/shaders"
mkdir -p "$shaders"
# New phase7 SPIR-V instructions are newer than Ubuntu 24.04's assembler.
# Use a private container for shader tools and retain their exact versions.
docker run --rm -v "$src:/src:ro" -v "$shaders:/out" debian:sid sh -ec '
  apt-get update -qq
  apt-get install -y --no-install-recommends spirv-tools glslang-tools xxd
  dpkg-query -W spirv-tools glslang-tools xxd > /out/TOOLS.txt
  for shader in descriptor.comp bda.comp push.comp robust.comp draw.vert draw.frag texture.comp; do
    glslangValidator --target-env vulkan1.2 -V "/src/$shader" -o "/out/$shader.spv"
    xxd -i -n "${shader%.*}_${shader##*.}_spv" "/out/$shader.spv" > "/out/$shader.spv.h"
  done
  for name in derivatives-quads derivatives-linear untyped relaxed constant-data user-type; do
    spirv-as --target-env spv1.6 "/src/phase7-$name.comp.spvasm" -o "/out/phase7-$name.spv"
    if [ "$name" != constant-data ]; then spirv-val --target-env vulkan1.3 "/out/phase7-$name.spv"; fi
    symbol=$(printf "%s" "$name" | tr - _)
    xxd -i -n "phase7_${symbol}_spv" "/out/phase7-$name.spv" > "/out/phase7-$name.spv.h"
  done
  glslangValidator --target-env vulkan1.3 -V /src/phase7-fma.comp -o /out/phase7-fma.spv
  spirv-val --target-env vulkan1.3 /out/phase7-fma.spv
  xxd -i -n phase7_fma_spv /out/phase7-fma.spv > /out/phase7-fma.spv.h
  chmod -R a+rX /out
'
if [ -n "${CC:-}" ]; then
  cc=$CC
else
  ndk=${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_HOME:?no NDK}}
  cc="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android29-clang"
fi
# Preserve the upstream graphics oracle, but make the complete image available
# to distinguish a faulty sample/threshold from an actual rasterization error.
python3 - "$src/graphics-features.c" "$out/graphics-features-dump.c" <<'PY'
import pathlib, sys
source = pathlib.Path(sys.argv[1]).read_text()
needle = '   vkUnmapMemory(c.device,rb.memory);int ok='
assert source.count(needle) == 1
source = source.replace(needle, '''   const char *dump = getenv("FEATURE_DUMP");
   if (dump) {
      FILE *file = fopen(dump, "wb");
      if (!file || fwrite(px, 4, W * H, file) != W * H || fclose(file)) return 1;
   }
''' + needle)
pathlib.Path(sys.argv[2]).write_text(source)
PY
for name in sync-features compute-features graphics-features texture-features phase7-compute phase7-api bc-format-probe; do
  source="$src/$name.c"
  if [ "$name" = graphics-features ]; then source="$out/graphics-features-dump.c"; fi
  "$cc" -std=gnu11 -O2 -Wall -Wextra -I"$vk" -I"$shaders" -I"$src" "$source" -ldl -lm -pthread -o "$out/$name"
done
rm "$out/graphics-features-dump.c"
if [ -n "${CC:-}" ]; then
  "$cc" -O2 -Wall "$zenith/tests/x11-shm/x11_shm_present_test.c" -lxcb -lxcb-shm -o "$out/x11-shm"
fi
if [ -z "${CC:-}" ]; then
  for name in ahb ahb_linear ahb_render ahb_vendor ahb_vendor_linear fdimport fdimport_mtk; do
    "$cc" -std=gnu11 -O2 -Wall -I"$vk" "$zenith/tests/ahb/$name.c" -ldl -landroid -lm -o "$out/$name"
  done
  # ahb_render2 is intentionally excluded: its debug loop unconditionally
  # reads 69632 bytes from an allocation whose actual stride/size may be less.
  echo 'Excluded ahb_render2: unchecked 69632-byte debug read' > "$out/EXCLUSIONS.txt"
fi
cp "$shaders/TOOLS.txt" "$out/SHADER-TOOLS.txt"
rm -rf "$shaders"
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
