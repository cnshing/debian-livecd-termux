/* Diagnostic only: preload into the private shell to log invalid SHM reads.
 * cc -shared -fPIC fullscreen-xshm-trace.c -o fullscreen-xshm-trace.so -lX11 -ldl
 */
#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <X11/extensions/XShm.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Shell prepends its compiled-in typelib directory after reading the environment.
 * Redirect that one path when testing a private Cogl build, to avoid loading a
 * second copy through introspection. Without this variable this is a pass-through.
 */
void
g_irepository_prepend_search_path(const char *path)
{
    typedef void (*Prepend)(const char *);
    Prepend original = (Prepend)dlsym(RTLD_NEXT, "g_irepository_prepend_search_path");
    const char *override = getenv("LIVECD_FULLSCREEN_GI_DIR");
    original(override && strstr(path, "/lib/mutter-16") ? override : path);
}

void
g_irepository_prepend_library_path(const char *path)
{
    typedef void (*Prepend)(const char *);
    Prepend original = (Prepend)dlsym(RTLD_NEXT, "g_irepository_prepend_library_path");
    const char *override = getenv("LIVECD_FULLSCREEN_GI_DIR");
    original(override && strstr(path, "/lib/mutter-16") ? override : path);
}

Bool
XShmGetImage(Display *display, Drawable drawable, XImage *image,
             int x, int y, unsigned long planes)
{
    typedef Bool (*GetImage)(Display *, Drawable, XImage *, int, int, unsigned long);
    static GetImage original;
    Window root;
    int px, py;
    unsigned int width, height, border, depth;
    if (!original)
        original = (GetImage)dlsym(RTLD_NEXT, "XShmGetImage");
    if (XGetGeometry(display, drawable, &root, &px, &py, &width, &height, &border, &depth)
        && (x < 0 || y < 0 || (int64_t)x + image->width > width
            || (int64_t)y + image->height > height || image->depth != depth)) {
        Dl_info caller = {0};
        void *address = __builtin_return_address(0);
        dladdr(address, &caller);
        fprintf(stderr, "FULLSCREEN_INVALID_SHM_READ drawable=0x%lx "
                "pixmap=%ux%u depth=%u request=%d,%d %dx%d depth=%d "
                "caller=%s+0x%lx\n", drawable, width, height, depth,
                x, y, image->width, image->height, image->depth,
                caller.dli_fname ? caller.dli_fname : "unknown",
                (unsigned long)((uintptr_t)address - (uintptr_t)caller.dli_fbase));
        fflush(stderr);
    }
    return original(display, drawable, image, x, y, planes);
}
