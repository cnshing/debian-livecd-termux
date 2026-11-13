"""Copy a Zenith offscreen triangle test, adding a full readback dump.

The whole 64x64 RGBA readback (row 0 first) is written to $TRIANGLE_DUMP so
the picture can be inspected instead of trusting two sampled pixels.

With --top-left-oracle, the sampled pixels are also moved to match
triangle.c. All three tests draw (-1,-1) (-0.25,-1) (-1,-0.25) with a
positive-height viewport, which puts the triangle at row 0 (top-left);
triangle_vb.c and triangle_const.c sample (8,55) and so fail a correct image.
"""
import sys

args = sys.argv[1:]
fix_oracle = "--top-left-oracle" in args
source, target = [a for a in args if not a.startswith("--")]
text = open(source).read()


def replace_once(old, new):
    global text
    if text.count(old) != 1:
        sys.exit(f"{source}: expected exactly one {old!r}")
    text = text.replace(old, new)


replace_once("   uint8_t *px = rp_;\n", """   uint8_t *px = rp_;
   {
      const char *dump_path = getenv("TRIANGLE_DUMP");
      if (dump_path) {
         FILE *dump = fopen(dump_path, "wb");
         if (dump) {
            fwrite(px, 4, W * H, dump);
            fclose(dump);
         }
      }
   }
""")
if fix_oracle:
    replace_once("px + (55 * W + 8) * 4;", "px + (8 * W + 8) * 4;")
    replace_once("px + (8 * W + 55) * 4;", "px + (55 * W + 55) * 4;")
open(target, "w").write(text)
