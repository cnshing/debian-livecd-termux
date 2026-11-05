/* SPDX-License-Identifier: MIT
 * Linux 4.12+ unprotected ION system-heap fallback for the Mesa TVA allocator.
 * A dma-buf object may have physically scattered pages. No legacy ION ABI or
 * protected heaps are used. Both Bionic and glibc can compile this header.
 */
#ifndef LIVECD_TVA_ION_H
#define LIVECD_TVA_ION_H

#include <stdint.h>

struct android_vaapi_ion_allocation {
   uint64_t len;
   uint32_t heap_id_mask, flags, fd, unused;
};
struct android_vaapi_ion_heap {
   char name[32];
   uint32_t type, heap_id, reserved[3];
};
struct android_vaapi_ion_query {
   uint32_t cnt, reserved0;
   uint64_t heaps;
   uint32_t reserved[2];
};

static int
android_vaapi_tva_alloc_ion(size_t size)
{
   int fd = open("/dev/ion", O_RDONLY | O_CLOEXEC);
   if (fd < 0)
      return -1;

   struct android_vaapi_ion_heap heaps[32] = {0};
   struct android_vaapi_ion_query query = {
      .cnt = 32, .heaps = (uintptr_t)heaps,
   };
   int result = -1;
   if (ioctl(fd, _IOWR('I', 8, struct android_vaapi_ion_query), &query) < 0)
      goto out;
   errno = ENODEV;
   for (unsigned i = 0; i < query.cnt && i < 32; i++) {
      if (heaps[i].type != 0 || heaps[i].heap_id >= 32)
         continue;
      struct android_vaapi_ion_allocation alloc = {
         .len = size, .heap_id_mask = 1u << heaps[i].heap_id,
         .flags = 1, /* ION_FLAG_CACHED; existing TVA DMA_BUF sync is retained. */
      };
      if (ioctl(fd, _IOWR('I', 0, struct android_vaapi_ion_allocation), &alloc) < 0)
         break;
      result = (int)alloc.fd;
      if (fcntl(result, F_SETFD, FD_CLOEXEC) < 0) {
         int saved = errno;
         close(result);
         errno = saved;
         result = -1;
      }
      break;
   }
out:;
   int saved = errno;
   close(fd);
   errno = saved;
   return result;
}
#endif
