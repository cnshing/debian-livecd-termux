// Preload that presents /dev/dma_heap/system and /dev/dma_heap/system-uncached
// on kernels that predate DMA-BUF heaps (Linux < 5.6) but have ION, with ION
// doing the allocating. Programs written for DMA-BUF heaps then work unchanged
// and get real DMA-BUFs; only the allocator interface is emulated.
//   clang -O2 -Wall -shared -fPIC -U_FORTIFY_SOURCE -o libandroid-dma-heap.so dma-heap.c -ldl
//
// Mapping follows Android's libdmabufheap (BufferAllocator::QueryIonHeaps):
//   system          -> ION heap "ion_system_heap", ION_FLAG_CACHED
//   system-uncached -> ION heap "ion_system_heap", no flags
// Vendors rename heaps (Samsung uses other names and IDs), so when no heap has
// that name the first heap of type ION_HEAP_TYPE_SYSTEM is used. Carveout,
// CMA, DMA and secure heaps are never used. Only ION's 4.12+ ABI is spoken.
//
// When /dev/ion is missing, has no system heap, or the kernel has real DMA-BUF
// heaps, nothing is emulated and open() fails or passes through exactly as it
// would without this library. No shared memory ever pretends to be a DMA-BUF.
//
// Like render-node.c, nothing here allocates or formats unless the path or
// descriptor is one of ours, since libc calls these wrappers during start-up.
// Raw syscall() and statically linked programs are not covered.
//
// A library that must not change the whole process (the VA bridge inside the desktop session,
// where Turnip and PanVK would also pick up the emulated heaps) can dlopen this file without
// preloading it and call livecd_dma_heap_alloc(): dlopen'd symbols interpose nothing, so only
// that caller's allocations come from ION.
//
// Environment (read once at load):
//   LIVECD_DMA_HEAP_ION=0            disable emulation
//   LIVECD_DMA_HEAP_ION_DEVICE=path  ION device (default /dev/ion; for tests)
//   LIVECD_DMA_HEAP_DIR=path         where a real heap directory would be
//                                    (default /dev/dma_heap; for tests)
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define EXPORT __attribute__((visibility("default")))
#define MAX_FDS 4096
#define HEAP_DIR "/dev/dma_heap"

// <linux/dma-heap.h>
struct dma_heap_allocation_data {
    uint64_t len;
    uint32_t fd, fd_flags;
    uint64_t heap_flags;
};
#define DMA_HEAP_IOCTL_ALLOC _IOWR('H', 0x0, struct dma_heap_allocation_data)

// <linux/ion.h>, 4.12+ ABI.
struct ion_allocation_data {
    uint64_t len;
    uint32_t heap_id_mask, flags, fd, unused;
};
struct ion_heap_data {
    char name[32];
    uint32_t type, heap_id, reserved0, reserved1, reserved2;
};
struct ion_heap_query {
    uint32_t cnt, reserved0;
    uint64_t heaps;
    uint32_t reserved1, reserved2;
};
#define ION_IOC_ALLOC _IOWR('I', 0, struct ion_allocation_data)
#define ION_IOC_HEAP_QUERY _IOWR('I', 8, struct ion_heap_query)
#define ION_HEAP_TYPE_SYSTEM 0
#define ION_FLAG_CACHED 1

enum { NONE = 0, CACHED = 1, UNCACHED = 2 };

static struct {
    int (*openat)(int, const char *, int, ...);
    int (*close)(int);
    int (*dup)(int);
    int (*dup2)(int, int);
    int (*dup3)(int, int, int);
    int (*ioctl)(int, unsigned long, ...); // called with ION requests only
    int (*fstat)(int, struct stat *);
    int (*fstatat)(int, const char *, struct stat *, int);
    int (*faccessat)(int, const char *, int, int);
} next;

static _Atomic uint8_t kinds[MAX_FDS];
static bool enabled;
static char ion_path[256] = "/dev/ion";
static char heap_dir[256] = HEAP_DIR;
static _Atomic int64_t heap_mask = -1; // -1 unknown, 0 none
static struct stat ion_st;

// Preloaded, we are in the global scope and the real definitions come next. Loaded with dlopen
// (livecd_dma_heap_alloc), we are not, and use what the rest of the process calls.
static bool ours(void *f) {
    Dl_info a, b;
    return f && dladdr(f, &a) && dladdr((void *)ours, &b) && a.dli_fbase == b.dli_fbase;
}
static void *sym(const char *name) {
    static void *global; // the program's handle searches only the global scope
    if (!global) global = dlopen(NULL, RTLD_NOW);
    return dlsym(ours(dlsym(global, "livecd_dma_heap_alloc")) ? RTLD_NEXT : global, name);
}
// Bionic runs these wrappers before constructors, so each resolves on first use.
static void *lazy(void **slot, const char *name) {
    if (!*slot) *slot = sym(name);
    return *slot;
}
#define NEXT(f) ((__typeof__(next.f))lazy((void **)&next.f, #f))

__attribute__((constructor)) static void init(void) {
    const char *v = getenv("LIVECD_DMA_HEAP_ION");
    if (v && !strcmp(v, "0")) return;
    if ((v = getenv("LIVECD_DMA_HEAP_ION_DEVICE")) && strlen(v) < sizeof ion_path) strcpy(ion_path, v);
    if ((v = getenv("LIVECD_DMA_HEAP_DIR")) && strlen(v) < sizeof heap_dir) strcpy(heap_dir, v);
    struct stat st;
    // Real heaps present: stay out of the way.
    if (NEXT(fstatat)(AT_FDCWD, heap_dir, &st, 0) == 0) return;
    if (NEXT(fstatat)(AT_FDCWD, ion_path, &ion_st, 0) != 0) return;
    enabled = true;
}

// Which emulated heap a path names, or NONE.
static int heap_of(const char *path) {
    if (!enabled || !path) return NONE;
    size_t n = strlen(heap_dir);
    if (strncmp(path, heap_dir, n) || path[n] != '/') return NONE;
    const char *name = path + n + 1;
    if (!strcmp(name, "system")) return CACHED;
    if (!strcmp(name, "system-uncached")) return UNCACHED;
    return NONE;
}
static bool is_dir(const char *path) { return enabled && path && !strcmp(path, heap_dir); }

static int kind(int fd) { return fd >= 0 && fd < MAX_FDS ? kinds[fd] : NONE; }
static void set_kind(int fd, int k) { if (fd >= 0 && fd < MAX_FDS) kinds[fd] = k; }

// Finds the ION system heap once. Name first, as libdmabufheap does, then type.
static int64_t system_heap(int ion) {
    int64_t mask = heap_mask;
    if (mask >= 0) return mask;
    struct ion_heap_data heaps[32];
    memset(heaps, 0, sizeof heaps);
    struct ion_heap_query q = {.cnt = 32, .heaps = (uintptr_t)heaps};
    mask = 0;
    if (NEXT(ioctl)(ion, ION_IOC_HEAP_QUERY, &q) == 0) {
        unsigned n = q.cnt < 32 ? q.cnt : 32;
        for (unsigned i = 0; i < n && !mask; i++)
            if (heaps[i].type == ION_HEAP_TYPE_SYSTEM && heaps[i].heap_id < 32 &&
                !strncmp(heaps[i].name, "ion_system_heap", sizeof heaps[i].name))
                mask = 1ll << heaps[i].heap_id;
        for (unsigned i = 0; i < n && !mask; i++)
            if (heaps[i].type == ION_HEAP_TYPE_SYSTEM && heaps[i].heap_id < 32)
                mask = 1ll << heaps[i].heap_id;
    }
    heap_mask = mask;
    return mask;
}

static bool system_heap_known_absent(void) { return heap_mask == 0; }

static int open_heap(int k, int flags) {
    int fd = NEXT(openat)(AT_FDCWD, ion_path, O_RDONLY | (flags & O_CLOEXEC));
    if (fd < 0) { errno = ENOENT; return -1; }
    if (system_heap(fd) <= 0) { NEXT(close)(fd); errno = ENOENT; return -1; }
    set_kind(fd, k);
    return fd;
}

static int heap_alloc(int fd, int k, struct dma_heap_allocation_data *d) {
    if (!d) { errno = EFAULT; return -1; }
    if (d->fd || d->heap_flags || (d->fd_flags & ~(O_RDWR | O_WRONLY | O_CLOEXEC))) {
        errno = EINVAL; // same checks as the kernel's dma-heap.c
        return -1;
    }
    struct ion_allocation_data a = {
        .len = d->len,
        .heap_id_mask = (uint32_t)system_heap(fd),
        .flags = k == CACHED ? ION_FLAG_CACHED : 0,
    };
    if (!a.heap_id_mask) { errno = ENODEV; return -1; }
    if (NEXT(ioctl)(fd, ION_IOC_ALLOC, &a) < 0) return -1;
    int out = (int)a.fd;
    if (fcntl(out, F_SETFD, (d->fd_flags & O_CLOEXEC) ? FD_CLOEXEC : 0) < 0) {
        int e = errno;
        NEXT(close)(out);
        errno = e;
        return -1;
    }
    d->fd = (uint32_t)out;
    return 0;
}

static mode_t mode_arg(int flags, va_list ap) {
    return (flags & O_CREAT) || (flags & __O_TMPFILE) == __O_TMPFILE ? va_arg(ap, int) : 0;
}

static int do_openat(int dirfd, const char *path, int flags, mode_t mode) {
    int k = heap_of(path);
    if (k) return open_heap(k, flags);
    int fd = NEXT(openat)(dirfd, path, flags, mode);
    if (fd >= 0) set_kind(fd, NONE);
    return fd;
}

EXPORT int openat(int dirfd, const char *path, int flags, ...) {
    va_list ap; va_start(ap, flags); mode_t m = mode_arg(flags, ap); va_end(ap);
    return do_openat(dirfd, path, flags, m);
}
EXPORT int open(const char *path, int flags, ...) {
    va_list ap; va_start(ap, flags); mode_t m = mode_arg(flags, ap); va_end(ap);
    return do_openat(AT_FDCWD, path, flags, m);
}
EXPORT int open64(const char *path, int flags, ...) {
    va_list ap; va_start(ap, flags); mode_t m = mode_arg(flags, ap); va_end(ap);
    return do_openat(AT_FDCWD, path, flags, m);
}
EXPORT int openat64(int dirfd, const char *path, int flags, ...) {
    va_list ap; va_start(ap, flags); mode_t m = mode_arg(flags, ap); va_end(ap);
    return do_openat(dirfd, path, flags, m);
}
EXPORT int __open_2(const char *path, int flags) { return do_openat(AT_FDCWD, path, flags, 0); }
EXPORT int __open64_2(const char *path, int flags) { return do_openat(AT_FDCWD, path, flags, 0); }
EXPORT int __openat_2(int dirfd, const char *path, int flags) { return do_openat(dirfd, path, flags, 0); }

EXPORT int close(int fd) {
    set_kind(fd, NONE);
    return NEXT(close)(fd);
}
EXPORT int dup(int fd) {
    int r = NEXT(dup)(fd);
    if (r >= 0) set_kind(r, kind(fd));
    return r;
}
EXPORT int dup2(int fd, int to) {
    int r = NEXT(dup2)(fd, to);
    if (r >= 0 && r != fd) set_kind(r, kind(fd));
    return r;
}
EXPORT int dup3(int fd, int to, int flags) {
    int r = NEXT(dup3)(fd, to, flags);
    if (r >= 0) set_kind(r, kind(fd));
    return r;
}

#ifdef __BIONIC__
typedef int ioctl_req; // Bionic: int ioctl(int, int, ...)
#else
typedef unsigned long ioctl_req;
#endif
EXPORT int ioctl(int fd, ioctl_req request, ...) {
    va_list ap; va_start(ap, request); void *arg = va_arg(ap, void *); va_end(ap);
    int k = kind(fd);
    if (k && (unsigned)request == (unsigned)DMA_HEAP_IOCTL_ALLOC) return heap_alloc(fd, k, arg);
    if (k) { errno = ENOTTY; return -1; } // a heap node speaks only ALLOC
    return NEXT(ioctl)(fd, request, arg);
}

// The heaps look like character devices in a directory, as on Linux 5.6+.
static void fake_stat(struct stat *st, int k) {
    *st = ion_st;
    st->st_mode = k ? (S_IFCHR | 0444) : (S_IFDIR | 0755);
    st->st_rdev = k ? makedev(major(ion_st.st_rdev), k) : 0;
    st->st_ino = 0x6865617000ull + (unsigned)k;
}
static int do_fstatat(int dirfd, const char *path, struct stat *st, int flags) {
    int k = heap_of(path);
    if (k || is_dir(path)) {
        if (k && system_heap_known_absent()) { errno = ENOENT; return -1; }
        fake_stat(st, k);
        return 0;
    }
    return NEXT(fstatat)(dirfd, path, st, flags);
}
EXPORT int fstatat(int dirfd, const char *path, struct stat *st, int flags) { return do_fstatat(dirfd, path, st, flags); }
EXPORT int lfs_fstatat64(int dirfd, const char *path, struct stat *st, int flags) __asm__("fstatat64");
int lfs_fstatat64(int dirfd, const char *path, struct stat *st, int flags) { return do_fstatat(dirfd, path, st, flags); }
EXPORT int stat(const char *path, struct stat *st) { return do_fstatat(AT_FDCWD, path, st, 0); }
EXPORT int lfs_stat64(const char *path, struct stat *st) __asm__("stat64");
int lfs_stat64(const char *path, struct stat *st) { return do_fstatat(AT_FDCWD, path, st, 0); }
EXPORT int lstat(const char *path, struct stat *st) { return do_fstatat(AT_FDCWD, path, st, AT_SYMLINK_NOFOLLOW); }
EXPORT int lfs_lstat64(const char *path, struct stat *st) __asm__("lstat64");
int lfs_lstat64(const char *path, struct stat *st) { return do_fstatat(AT_FDCWD, path, st, AT_SYMLINK_NOFOLLOW); }
EXPORT int fstat(int fd, struct stat *st) {
    int k = kind(fd);
    if (k) { fake_stat(st, k); return 0; }
    return NEXT(fstat)(fd, st);
}
EXPORT int lfs_fstat64(int fd, struct stat *st) __asm__("fstat64");
int lfs_fstat64(int fd, struct stat *st) { return fstat(fd, st); }

static int do_access(int dirfd, const char *path, int mode, int flags) {
    int k = heap_of(path);
    if (k || is_dir(path)) {
        if (k && system_heap_known_absent()) { errno = ENOENT; return -1; }
        if (mode & (W_OK | X_OK) && k) { errno = EACCES; return -1; }
        return 0;
    }
    return NEXT(faccessat)(dirfd, path, mode, flags);
}
EXPORT int access(const char *path, int mode) { return do_access(AT_FDCWD, path, mode, 0); }
EXPORT int faccessat(int dirfd, const char *path, int mode, int flags) { return do_access(dirfd, path, mode, flags); }

// Allocates from heap "system" or "system-uncached" exactly as open() + DMA_HEAP_IOCTL_ALLOC
// on the emulated node would, for a caller that was not preloaded. Returns the dma-buf FD, or
// -1 with errno ENOENT when nothing is emulated (real heaps exist, no ION system heap, no
// /dev/ion, or LIVECD_DMA_HEAP_ION=0).
EXPORT int livecd_dma_heap_alloc(const char *heap, uint64_t len, uint32_t fd_flags) {
    char path[sizeof heap_dir + 32];
    snprintf(path, sizeof path, "%s/%s", heap_dir, heap ? heap : "");
    int k = heap_of(path);
    if (!k) { errno = ENOENT; return -1; }
    int fd = open_heap(k, O_CLOEXEC);
    if (fd < 0) return -1;
    struct dma_heap_allocation_data d = {.len = len, .fd_flags = fd_flags};
    int r = heap_alloc(fd, k, &d), e = errno;
    set_kind(fd, NONE);
    NEXT(close)(fd);
    errno = e;
    return r ? -1 : (int)d.fd;
}
