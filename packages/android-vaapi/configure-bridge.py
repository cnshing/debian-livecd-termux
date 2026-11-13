#!/usr/bin/env python3
"""Add ION dma-buf surfaces to the pinned Bionic and glibc VA bridge."""
import sys
from pathlib import Path
path = Path(sys.argv[1]); text = path.read_text()
for before, after in (('#include <linux/dma-heap.h>',
                       '#include <linux/dma-heap.h>\n#include "tva_ion.h"\n#include "tva_ion_winsys.h"'),
                      ('if (heap_fd < 0)\n      return -1;',
                       'if (heap_fd < 0)\n      return errno == ENOENT ? android_vaapi_tva_alloc_ion(size) : -1;'),
                      ('struct pipe_screen *pscreen = pipe_loader_create_screen(dev, false);',
                       'struct pipe_screen *pscreen = tva_ion_screen_create();\n'
                       '    if (pscreen)\n'
                       '        fprintf(stderr, "tva: software backend on dma-buf surfaces\\n");\n'
                       '    else\n'
                       '        pscreen = pipe_loader_create_screen(dev, false);'),
                      ('if (tva_sw_backend_enabled())\n',
                       'if (tva_sw_backend_enabled() && !tva_ion_winsys_active)\n'),
                      ('        return !strcmp(e, "1") || !strcmp(e, "true") || !strcmp(e, "on");\n',
                       '        return !strcmp(e, "1") || !strcmp(e, "true") || !strcmp(e, "on");\n'
                       '    /* Browsers import an NV12 frame as one dma-buf object. */\n'
                       '    if (tva_ion_winsys_active)\n'
                       '        return true;\n')):
    if text.count(before) != 1:
        sys.exit('The pinned Termux:VA bridge changed near: ' + before)
    text = text.replace(before, after)
path.write_text(text)
