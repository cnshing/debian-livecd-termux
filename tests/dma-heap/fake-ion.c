// Test double for /dev/ion, loaded after libandroid-dma-heap.so. ioctls on a
// descriptor of the file $FAKE_ION answer ION_IOC_HEAP_QUERY with a carveout
// heap and a system heap (named $FAKE_ION_NAME, default ion_system_heap), and
// ION_IOC_ALLOC with a memfd. Each allocation's mask and flags are appended to
// $FAKE_ION_LOG. Everything else passes through.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
struct ion_allocation_data { uint64_t len; uint32_t heap_id_mask, flags, fd, unused; };
struct ion_heap_data { char name[32]; uint32_t type, heap_id, r0, r1, r2; };
struct ion_heap_query { uint32_t cnt, r0; uint64_t heaps; uint32_t r1, r2; };
#define ION_IOC_ALLOC _IOWR('I', 0, struct ion_allocation_data)
#define ION_IOC_HEAP_QUERY _IOWR('I', 8, struct ion_heap_query)
static int is_ion(int fd) {
    const char *p = getenv("FAKE_ION");
    char link[64], target[4096];
    snprintf(link, sizeof link, "/proc/self/fd/%d", fd); // fstat is the preload's
    ssize_t n = readlink(link, target, sizeof target - 1);
    if (!p || n < 0) return 0;
    target[n] = 0;
    return !strcmp(target, p);
}
int ioctl(int fd, unsigned long req, ...) {
    va_list ap; va_start(ap, req); void *arg = va_arg(ap, void *); va_end(ap);
    static int (*real)(int, unsigned long, ...);
    if (!real) real = dlsym(RTLD_NEXT, "ioctl");
    if (!is_ion(fd)) return real(fd, req, arg);
    if (req == ION_IOC_HEAP_QUERY) {
        struct ion_heap_query *q = arg;
        const char *name = getenv("FAKE_ION_NAME");
        int sys = !getenv("FAKE_ION_NO_SYSTEM");
        struct ion_heap_data *h = (void *)(uintptr_t)q->heaps;
        memset(h, 0, sizeof *h * 2);
        strcpy(h[0].name, "carveout"); h[0].type = 2; h[0].heap_id = 2;
        strcpy(h[1].name, name ? name : "ion_system_heap"); h[1].type = sys ? 0 : 4; h[1].heap_id = 5;
        q->cnt = 2;
        return 0;
    }
    if (req == ION_IOC_ALLOC) {
        struct ion_allocation_data *a = arg;
        int m = memfd_create("fake-dmabuf", 0);
        if (ftruncate(m, a->len) < 0) return -1;
        a->fd = m;
        FILE *f = fopen(getenv("FAKE_ION_LOG"), "a");
        if (f) { fprintf(f, "mask=%#x flags=%u\n", a->heap_id_mask, a->flags); fclose(f); }
        return 0;
    }
    return real(fd, req, arg);
}
