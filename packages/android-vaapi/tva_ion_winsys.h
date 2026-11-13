/* SPDX-License-Identifier: MIT
 * Generated-by: LLM
 *
 * A softpipe winsys whose shared resources are dma-bufs, for GPUs the bridge
 * cannot drive (Mali through kbase, no DRM render node).
 *
 * The bridge's software backend used the null winsys, so its surfaces were
 * plain malloc'd memory: vaExportSurfaceHandle failed and browsers, which
 * import every decoded frame as a dma-buf, fell back to software decoding.
 * Here softpipe's display targets live in dma-bufs from the system dma-heap
 * or, on Android 11 and older kernels, ION.  Softpipe already routes shared
 * resources, imports, exports and CPU maps through the winsys, so the bridge's
 * contiguous NV12 surfaces, its DMA_BUF_IOCTL_SYNC write brackets and the VA
 * export all work unchanged on top of it.
 *
 * Include after tva_ion.h.  TERMUX_VA_ION_WINSYS=0 restores the null winsys.
 */
#ifndef LIVECD_TVA_ION_WINSYS_H
#define LIVECD_TVA_ION_WINSYS_H

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "frontend/sw_winsys.h"
#include "frontend/winsys_handle.h"
#include "util/format/u_format.h"

struct pipe_screen *softpipe_create_screen(struct sw_winsys *winsys);

/* Read by the bridge: surfaces from this winsys can be shared and exported. */
static bool tva_ion_winsys_active;

struct tva_ion_dt {
   int fd;
   uint8_t *base;       /* whole object, page-aligned mapping */
   size_t size;
   unsigned offset;     /* this resource's first byte within the object */
   unsigned stride;
};

static int
tva_ion_ws_alloc(size_t size)
{
#ifdef __linux__
   int heap = open("/dev/dma_heap/system", O_RDONLY | O_CLOEXEC);
   if (heap >= 0) {
      struct dma_heap_allocation_data alloc = {
         .len = size, .fd_flags = O_RDWR | O_CLOEXEC,
      };
      int ret = ioctl(heap, DMA_HEAP_IOCTL_ALLOC, &alloc);
      close(heap);
      if (ret == 0)
         return (int)alloc.fd;
   }
#endif
   return android_vaapi_tva_alloc_ion(size);
}

static struct sw_displaytarget *
tva_ion_dt_wrap(int fd, size_t size, unsigned offset, unsigned stride)
{
   struct tva_ion_dt *dt = calloc(1, sizeof(*dt));
   if (!dt)
      return NULL;
   void *base = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
   if (base == MAP_FAILED) {
      free(dt);
      return NULL;
   }
   dt->fd = fd;
   dt->base = base;
   dt->size = size;
   dt->offset = offset;
   dt->stride = stride;
   return (struct sw_displaytarget *)dt;
}

static bool
tva_ion_ws_format_supported(struct sw_winsys *ws, unsigned usage, enum pipe_format format)
{
   (void)ws, (void)usage;
   return util_format_get_blocksize(format) != 0;
}

static struct sw_displaytarget *
tva_ion_ws_create(struct sw_winsys *ws, unsigned usage, enum pipe_format format,
                  unsigned width, unsigned height, unsigned alignment,
                  const void *front_private, unsigned *stride)
{
   (void)ws, (void)usage, (void)front_private;
   const unsigned blocksize = util_format_get_blocksize(format);
   const unsigned rows = util_format_get_nblocksy(format, height);
   const uint64_t row = (uint64_t)util_format_get_nblocksx(format, width) * blocksize;
   if (!blocksize || !rows || !row || alignment < 64)
      alignment = 64;
   const uint64_t pitch = (row + alignment - 1) / alignment * alignment;
   const uint64_t size = (pitch * rows + 4095) & ~(uint64_t)4095;
   if (!blocksize || !pitch || pitch > UINT32_MAX || size > SIZE_MAX || size > UINT32_MAX)
      return NULL;
   int fd = tva_ion_ws_alloc((size_t)size);
   if (fd < 0)
      return NULL;
   struct sw_displaytarget *dt = tva_ion_dt_wrap(fd, (size_t)size, 0, (unsigned)pitch);
   if (!dt) {
      close(fd);
      return NULL;
   }
   *stride = (unsigned)pitch;
   return dt;
}

static struct sw_displaytarget *
tva_ion_ws_from_handle(struct sw_winsys *ws, const struct pipe_resource *templat,
                       struct winsys_handle *whandle, unsigned *stride)
{
   (void)ws, (void)templat;
   if (whandle->type != WINSYS_HANDLE_TYPE_FD || !whandle->stride)
      return NULL;
   uint64_t size = whandle->size;
   if (!size) {
      off_t end = lseek((int)whandle->handle, 0, SEEK_END);
      if (end <= 0)
         return NULL;
      size = (uint64_t)end;
   }
   if (size > SIZE_MAX || whandle->offset >= size)
      return NULL;
   /* The caller keeps its descriptor; this target owns a duplicate. */
   int fd = fcntl((int)whandle->handle, F_DUPFD_CLOEXEC, 0);
   if (fd < 0)
      return NULL;
   struct sw_displaytarget *dt = tva_ion_dt_wrap(fd, (size_t)size, whandle->offset,
                                                 whandle->stride);
   if (!dt) {
      close(fd);
      return NULL;
   }
   *stride = whandle->stride;
   return dt;
}

static bool
tva_ion_ws_get_handle(struct sw_winsys *ws, struct sw_displaytarget *sdt,
                      struct winsys_handle *whandle)
{
   (void)ws;
   struct tva_ion_dt *dt = (struct tva_ion_dt *)sdt;
   if (whandle->type != WINSYS_HANDLE_TYPE_FD)
      return false;
   int fd = fcntl(dt->fd, F_DUPFD_CLOEXEC, 0);
   if (fd < 0)
      return false;
   whandle->handle = (unsigned)fd;
   whandle->stride = dt->stride;
   whandle->offset = dt->offset;
   whandle->size = dt->size;
   whandle->modifier = DRM_FORMAT_MOD_LINEAR;
   return true;
}

static void *
tva_ion_ws_map(struct sw_winsys *ws, struct sw_displaytarget *sdt, unsigned flags)
{
   (void)ws, (void)flags;
   struct tva_ion_dt *dt = (struct tva_ion_dt *)sdt;
   return dt->base + dt->offset;
}

static void
tva_ion_ws_unmap(struct sw_winsys *ws, struct sw_displaytarget *sdt)
{
   (void)ws, (void)sdt;
}

static void
tva_ion_ws_display(struct sw_winsys *ws, struct sw_displaytarget *sdt,
                   void *context_private, unsigned nboxes, struct pipe_box *box)
{
   (void)ws, (void)sdt, (void)context_private, (void)nboxes, (void)box;
}

static void
tva_ion_ws_dt_destroy(struct sw_winsys *ws, struct sw_displaytarget *sdt)
{
   (void)ws;
   struct tva_ion_dt *dt = (struct tva_ion_dt *)sdt;
   munmap(dt->base, dt->size);
   close(dt->fd);
   free(dt);
}

static int
tva_ion_ws_get_fd(struct sw_winsys *ws)
{
   (void)ws;
   return -1;
}

static void
tva_ion_ws_destroy(struct sw_winsys *ws)
{
   free(ws);
}

/* Softpipe on dma-buf display targets, or NULL to keep the null winsys. */
static struct pipe_screen *
tva_ion_screen_create(void)
{
   const char *e = getenv("TERMUX_VA_ION_WINSYS");
   if (e && (!strcmp(e, "0") || !strcmp(e, "false") || !strcmp(e, "off")))
      return NULL;
   /* Probe once: a working allocation proves the heap is usable here. */
   int probe = tva_ion_ws_alloc(4096);
   if (probe < 0)
      return NULL;
   close(probe);

   struct sw_winsys *ws = calloc(1, sizeof(*ws));
   if (!ws)
      return NULL;
   ws->destroy = tva_ion_ws_destroy;
   ws->get_fd = tva_ion_ws_get_fd;
   ws->is_displaytarget_format_supported = tva_ion_ws_format_supported;
   ws->displaytarget_create = tva_ion_ws_create;
   ws->displaytarget_from_handle = tva_ion_ws_from_handle;
   ws->displaytarget_get_handle = tva_ion_ws_get_handle;
   ws->displaytarget_map = tva_ion_ws_map;
   ws->displaytarget_unmap = tva_ion_ws_unmap;
   ws->displaytarget_display = tva_ion_ws_display;
   ws->displaytarget_destroy = tva_ion_ws_dt_destroy;

   struct pipe_screen *screen = softpipe_create_screen(ws);
   if (!screen) {
      free(ws);
      return NULL;
   }
   tva_ion_winsys_active = true;
   return screen;
}

#endif
