import sys

source, target = sys.argv[1:]
text = open(source).read()
anchor = "   uint8_t *px = rp_;\n"
dump = anchor + """   {
      const char *dump_path = getenv("TRIANGLE_DUMP");
      if (dump_path) {
         FILE *dump = fopen(dump_path, "wb");
         if (dump) {
            fwrite(px, 4, W * H, dump);
            fclose(dump);
         }
      }
   }
"""
if text.count(anchor) != 1:
    sys.exit("triangle.c readback anchor not found exactly once")
open(target, "w").write(text.replace(anchor, dump))
