/* Experimental glibc-only adapter for Mesa's /dev/dma_heap/system allocator.
 * Not installed by the product. Select with LIVECD_TVA_ION_FALLBACK=1 and preload
 * ONLY into the private browser through Bionilux, never a Bionic process.
 * Native ION UAPI is Linux 4.12+; no legacy/secure heap allocation is attempted.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/dma-heap.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <va/va.h>
#include <va/va_drmcommon.h>

struct ion_allocation { uint64_t len; uint32_t heap_id_mask, flags, fd, unused; };
struct ion_heap { char name[32]; uint32_t type, heap_id, reserved[3]; };
struct ion_query { uint32_t cnt, reserved0; uint64_t heaps; uint32_t reserved[2]; };

static VAStatus (*export_function)(VADisplay, VASurfaceID, uint32_t, uint32_t, void *);
static VAStatus trace_export(VADisplay, VASurfaceID, uint32_t, uint32_t, void *);

/* Chromium resolves VA entry points against its explicit libva dlopen handle,
 * bypassing ordinary symbol interposition. Observe that lookup as well. This
 * diagnostic is limited to aarch64 glibc, whose dlsym baseline is GLIBC_2.17. */
void *dlsym(void *handle, const char *name) {
    void *(*system_dlsym)(void *, const char *) = dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.17");
    if (!system_dlsym) return NULL;
    if (strcmp(name, "vaExportSurfaceHandle") || !getenv("LIVECD_TVA_TRACE_EXPORT")) {
        /* RTLD_NEXT is relative to dlsym's caller. A mandatory tail call keeps
         * that original return address, including libtva's open/ioctl lookups. */
        __attribute__((musttail)) return system_dlsym(handle, name);
    }
    void *address = system_dlsym(handle, name);
    if (address) {
        export_function = address;
        return (void *)trace_export;
    }
    return address;
}

static int enabled(void) {
    const char *value = getenv("LIVECD_TVA_ION_FALLBACK");
    return value && !strcmp(value, "1");
}

static int redirected_open(const char *path, int flags, mode_t mode, int dirfd) {
    int (*next_openat)(int, const char *, int, ...) = dlsym(RTLD_NEXT, "openat");
    int fd = next_openat(dirfd, path, flags, mode);
    if (fd < 0 && errno == ENOENT && enabled() && !strcmp(path, "/dev/dma_heap/system")) {
        fd = next_openat(AT_FDCWD, "/dev/ion", O_RDONLY | O_CLOEXEC, 0);
        if (fd >= 0) fprintf(stderr, "livecd-ion: opened ION read-only fd=%d\n", fd);
    }
    return fd;
}

static mode_t open_mode(int flags, va_list args) {
    return (flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE ? va_arg(args, unsigned int) : 0;
}

int open(const char *path, int flags, ...) {
    va_list args; va_start(args, flags);
    mode_t mode = open_mode(flags, args); va_end(args);
    return redirected_open(path, flags, mode, AT_FDCWD);
}

int open64(const char *path, int flags, ...) {
    va_list args; va_start(args, flags);
    mode_t mode = open_mode(flags, args); va_end(args);
    return redirected_open(path, flags, mode, AT_FDCWD);
}

int openat(int dirfd, const char *path, int flags, ...) {
    va_list args; va_start(args, flags);
    mode_t mode = open_mode(flags, args); va_end(args);
    return redirected_open(path, flags, mode, dirfd);
}

int ioctl(int fd, unsigned long request, ...) {
    va_list args; va_start(args, request);
    void *argument = va_arg(args, void *); va_end(args);
    int (*next_ioctl)(int, unsigned long, ...) = dlsym(RTLD_NEXT, "ioctl");
    struct stat actual, ion;
    if (request != DMA_HEAP_IOCTL_ALLOC || !enabled() || fstat(fd, &actual) ||
        stat("/dev/ion", &ion) || !S_ISCHR(actual.st_mode) || actual.st_rdev != ion.st_rdev)
        return next_ioctl(fd, request, argument);
    struct dma_heap_allocation_data *heap = argument;
    if (!heap || heap->heap_flags || !heap->len || (heap->fd_flags & ~(O_RDWR | O_CLOEXEC))) {
        errno = EINVAL; return -1;
    }
    struct ion_heap heaps[32] = {0};
    struct ion_query query = {.cnt = 32, .heaps = (uintptr_t)heaps};
    if (next_ioctl(fd, _IOWR('I', 8, struct ion_query), &query)) return -1;
    for (unsigned i = 0; i < query.cnt && i < 32; i++) {
        if (heaps[i].type != 0 || heaps[i].heap_id >= 32) continue;
        struct ion_allocation allocation = {.len = heap->len,
            .heap_id_mask = 1u << heaps[i].heap_id, .flags = 1}; /* ION_FLAG_CACHED */
        if (next_ioctl(fd, _IOWR('I', 0, struct ion_allocation), &allocation)) return -1;
        if (fcntl(allocation.fd, F_SETFD, (heap->fd_flags & O_CLOEXEC) ? FD_CLOEXEC : 0)) {
            int saved = errno; close(allocation.fd); errno = saved; return -1;
        }
        heap->fd = allocation.fd;
        fprintf(stderr, "livecd-ion: allocated size=%llu heap=%u fd=%u\n",
                (unsigned long long)heap->len, heaps[i].heap_id, heap->fd);
        return 0;
    }
    errno = ENODEV; return -1;
}

static VAStatus trace_export(VADisplay display, VASurfaceID surface, uint32_t type,
                             uint32_t flags, void *descriptor) {
    if (!export_function) return VA_STATUS_ERROR_OPERATION_FAILED;
    VAStatus status = export_function(display, surface, type, flags, descriptor);
    if (!status && type == VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2 && getenv("LIVECD_TVA_TRACE_EXPORT")) {
        VADRMPRIMESurfaceDescriptor *d = descriptor;
        fprintf(stderr, "livecd-va-export: surface=%u fourcc=%08x size=%ux%u objects=%u layers=%u\n",
                surface, d->fourcc, d->width, d->height, d->num_objects, d->num_layers);
        for (unsigned i = 0; i < d->num_objects && i < 4; i++) {
            struct stat info = {0}; fstat(d->objects[i].fd, &info);
            fprintf(stderr, "livecd-va-export: object=%u fd=%d inode=%llu size=%u modifier=%llx\n",
                i, d->objects[i].fd, (unsigned long long)info.st_ino, d->objects[i].size,
                (unsigned long long)d->objects[i].drm_format_modifier);
        }
        for (unsigned i = 0; i < d->num_layers && i < 4; i++)
            for (unsigned j = 0; j < d->layers[i].num_planes && j < 4; j++)
                fprintf(stderr, "livecd-va-export: layer=%u plane=%u object=%u offset=%u pitch=%u\n",
                    i, j, d->layers[i].object_index[j], d->layers[i].offset[j], d->layers[i].pitch[j]);
    }
    return status;
}
