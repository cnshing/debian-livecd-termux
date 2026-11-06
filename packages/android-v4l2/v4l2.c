// Preload that presents PipeWire cameras as V4L2 character devices.
//   LD_PRELOAD="$LD_PRELOAD:$PREFIX/lib/android-v4l2/libandroid-v4l2.so" program
// The desktop session preloads it for every program it starts.
//
// Without root there is no kernel device, so the device exists only in the C
// library calls a program makes. A camera producer (camera-node) publishes each
// camera as files in a generated folder, $ANDROID_V4L2_DIR, by default
// $XDG_RUNTIME_DIR/android-v4l2:
//   dev/videoN                              marker: /dev/videoN exists
//   sys/class/video4linux/videoN/{name,...} served for /sys/class/video4linux
// For a published /dev/videoN this library
//   - sends open, ioctl, mmap, munmap, dup and close to PipeWire's pw-v4l2,
//     loaded privately as a back end ($ANDROID_V4L2_BACKEND, or the patched
//     libpw-v4l2.so beside this library), so other calls never reach it;
//   - reports a character device, major 81, to stat, fstat, statx and access;
//   - lists it in /dev, and hides the phone's own video nodes, which SELinux
//     blocks for apps;
//   - answers libv4l2, which calls syscall() directly instead of open/ioctl.
// Other paths and descriptors pass to the next definition unchanged.
//
// The C library calls these wrappers during its own start-up, and its futex
// waits go through syscall(). So the wrappers use no one-time initialization,
// no formatted output and no allocation on any path that is not a camera.
#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/stat.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define EXPORT __attribute__((visibility("default")))
#define V4L2_MAJOR 81
#define MAX_DEVS 32
#define MAX_FDS 4096
#define MAX_MAPS 64
#define MAX_DIRS 16
#define SYS_V4L "/sys/class/video4linux"

static struct {
    int (*openat)(int, const char *, int, ...);
    int (*close)(int);
    int (*dup)(int);
    int (*ioctl)(int, int, ...);
    void *(*mmap)(void *, size_t, int, int, int, off_t);
    int (*munmap)(void *, size_t);
    int (*fstatat)(int, const char *, struct stat *, int);
    int (*fstat)(int, struct stat *);
    int (*faccessat)(int, const char *, int, int);
    int (*statx)(int, const char *, int, unsigned, struct statx *);
    DIR *(*opendir)(const char *);
    struct dirent *(*readdir)(DIR *);
    struct dirent64 *(*readdir64)(DIR *);
    int (*closedir)(DIR *);
    void (*rewinddir)(DIR *);
    char *(*realpath)(const char *, char *);
} real;

// Looking a function up twice is harmless, so concurrent or re-entrant first
// calls need no lock.
static void *resolve(void **slot, const char *name) {
    void *p = dlsym(RTLD_NEXT, name);
    __atomic_store_n(slot, p, __ATOMIC_RELEASE);
    return p;
}
#define REAL(name)                                                                                 \
    ((__typeof__(real.name))(__atomic_load_n((void **)&real.name, __ATOMIC_ACQUIRE)                \
                                 ?: resolve((void **)&real.name, #name)))

static struct {
    int (*openat)(int, const char *, int, ...);
    int (*close)(int);
    int (*dup)(int);
    int (*ioctl)(int, unsigned long, ...);
    void *(*mmap)(void *, size_t, int, int, int, off_t);
    int (*munmap)(void *, size_t);
} pw;

static pthread_once_t backend_once = PTHREAD_ONCE_INIT;
static _Atomic unsigned char fd_dev[MAX_FDS];  // camera number + 1 for each device descriptor
static struct { void *addr; size_t len; } maps[MAX_MAPS];
static atomic_int n_maps;
static pthread_mutex_t maps_lock = PTHREAD_MUTEX_INITIALIZER;
static struct { DIR *dir; int next; struct dirent ent; } dirs[MAX_DIRS];
static atomic_int n_dirs;
static pthread_mutex_t dirs_lock = PTHREAD_MUTEX_INITIALIZER;

// Bionic's own futex waits call syscall(), so passing a call through must not
// touch locks or the C library: it goes straight to the kernel.
#if defined(__aarch64__)
static long raw_syscall(long n, long a, long b, long c, long d, long e, long f) {
    register long x8 __asm__("x8") = n, x0 __asm__("x0") = a, x1 __asm__("x1") = b, x2 __asm__("x2") = c,
                  x3 __asm__("x3") = d, x4 __asm__("x4") = e, x5 __asm__("x5") = f;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory", "cc");
    return x0;
}
#elif defined(__x86_64__)
static long raw_syscall(long n, long a, long b, long c, long d, long e, long f) {
    register long r10 __asm__("r10") = d, r8 __asm__("r8") = e, r9 __asm__("r9") = f;
    long ret;
    __asm__ volatile("syscall"
                     : "=a"(ret)
                     : "a"(n), "D"(a), "S"(b), "d"(c), "r"(r10), "r"(r8), "r"(r9)
                     : "rcx", "r11", "memory");
    return ret;
}
#else
#error "raw system calls are implemented for aarch64 and x86_64 only"
#endif

static long pass_syscall(long n, const long *a) {
    long r = raw_syscall(n, a[0], a[1], a[2], a[3], a[4], a[5]);
    if ((unsigned long)r > -4096UL) {
        errno = (int)-r;
        return -1;
    }
    return r;
}

static void append_number(char *buf, int n) {
    char digits[12];
    int i = sizeof digits - 1;
    digits[i] = 0;
    do digits[--i] = '0' + n % 10;
    while ((n /= 10) && i > 0);
    strlcat(buf, digits + i, PATH_MAX);
}

static void base_dir(char *buf) {
    const char *dir = getenv("ANDROID_V4L2_DIR");
    if (dir && *dir) {
        strlcpy(buf, dir, PATH_MAX);
        return;
    }
    if (!(dir = getenv("XDG_RUNTIME_DIR")) || !*dir)
        if (!(dir = getenv("TMPDIR")) || !*dir) dir = "/data/data/com.termux/files/usr/tmp";
    strlcpy(buf, dir, PATH_MAX);
    strlcat(buf, "/android-v4l2", PATH_MAX);
}

static void marker_path(int n, char *buf) {
    base_dir(buf);
    strlcat(buf, "/dev/video", PATH_MAX);
    append_number(buf, n);
}

// Callers such as readdir() must leave errno as they found it.
static bool marker_exists(int n) {
    char marker[PATH_MAX];
    int saved = errno;
    marker_path(n, marker);
    bool found = REAL(faccessat)(AT_FDCWD, marker, F_OK, 0) == 0;
    errno = saved;
    return found;
}

// The camera number if path is a published /dev/videoN, else -1.
static int published(const char *path) {
    if (!path || strncmp(path, "/dev/video", 10) != 0) return -1;
    int n = 0, digits = 0;
    for (const char *p = path + 10; *p; p++, digits++) {
        if (*p < '0' || *p > '9' || digits > 2) return -1;
        n = n * 10 + (*p - '0');
    }
    return digits && n < MAX_DEVS && marker_exists(n) ? n : -1;
}

// /sys/class/video4linux and everything below it come from the generated folder.
static const char *redirect(const char *path, char *buf) {
    size_t len = sizeof SYS_V4L - 1;
    if (!path || strncmp(path, SYS_V4L, len) != 0 || (path[len] && path[len] != '/')) return path;
    base_dir(buf);
    strlcat(buf, "/sys/class/video4linux", PATH_MAX);
    strlcat(buf, path + len, PATH_MAX);
    return buf;
}

static int dev_of_fd(int fd) {
    return fd >= 0 && fd < MAX_FDS ? (int)atomic_load_explicit(&fd_dev[fd], memory_order_relaxed) - 1 : -1;
}

static void track(int fd, int n) {
    if (fd >= 0 && fd < MAX_FDS) atomic_store(&fd_dev[fd], (unsigned char)(n + 1));
}

static void load_backend(void) {
    char path[PATH_MAX];
    const char *lib = getenv("ANDROID_V4L2_BACKEND");
    Dl_info info;
    if ((!lib || !*lib) && dladdr((void *)load_backend, &info) && info.dli_fname) {
        strlcpy(path, info.dli_fname, sizeof path);
        char *slash = strrchr(path, '/');
        if (slash) {
            slash[1] = 0;
            strlcat(path, "libpw-v4l2.so", sizeof path);
            if (REAL(faccessat)(AT_FDCWD, path, F_OK, 0) == 0) lib = path;
        }
    }
    // Termux's own unpatched copy would recurse through Bionic's realpath().
    if (!lib || !*lib) return;
    // RTLD_LOCAL keeps pw-v4l2's own wrappers out of the global lookup; its
    // RTLD_NEXT lookups then resolve to the C library, not to this library.
    void *h = dlopen(lib, RTLD_NOW | RTLD_LOCAL);
    if (!h) return;
    pw.close = dlsym(h, "close"), pw.dup = dlsym(h, "dup"), pw.ioctl = dlsym(h, "ioctl");
    pw.mmap = dlsym(h, "mmap"), pw.munmap = dlsym(h, "munmap");
    if (pw.close && pw.dup && pw.ioctl && pw.mmap && pw.munmap) pw.openat = dlsym(h, "openat");
}

static int fake_stat(int n, struct stat *st) {
    char marker[PATH_MAX];
    marker_path(n, marker);
    if (REAL(fstatat)(AT_FDCWD, marker, st, 0) < 0) return -1;
    st->st_mode = S_IFCHR | 0660;
    st->st_rdev = makedev(V4L2_MAJOR, n);
    st->st_nlink = 1;
    st->st_size = 0;
    st->st_blocks = 0;
    return 0;
}

static int fake_statx(int n, struct statx *stx) {
    struct stat st;
    if (fake_stat(n, &st) < 0) return -1;
    memset(stx, 0, sizeof *stx);
    stx->stx_mask = STATX_BASIC_STATS;
    stx->stx_blksize = st.st_blksize;
    stx->stx_nlink = st.st_nlink;
    stx->stx_uid = st.st_uid;
    stx->stx_gid = st.st_gid;
    stx->stx_mode = st.st_mode;
    stx->stx_ino = st.st_ino;
    stx->stx_atime.tv_sec = st.st_atim.tv_sec, stx->stx_atime.tv_nsec = st.st_atim.tv_nsec;
    stx->stx_mtime.tv_sec = st.st_mtim.tv_sec, stx->stx_mtime.tv_nsec = st.st_mtim.tv_nsec;
    stx->stx_ctime.tv_sec = st.st_ctim.tv_sec, stx->stx_ctime.tv_nsec = st.st_ctim.tv_nsec;
    stx->stx_rdev_major = V4L2_MAJOR;
    stx->stx_rdev_minor = n;
    stx->stx_dev_major = major(st.st_dev);
    stx->stx_dev_minor = minor(st.st_dev);
    return 0;
}

static int device_open(int dirfd, const char *path, int flags, mode_t mode, int n) {
    pthread_once(&backend_once, load_backend);
    if (!pw.openat) {
        errno = ENODEV;
        return -1;
    }
    int fd = pw.openat(dirfd, path, flags, mode);
    track(fd, n);
    return fd;
}

// O_PATH opens, as realpath() makes, go to the real node like any other path.
static int do_openat(int dirfd, const char *path, int flags, mode_t mode) {
    char buf[PATH_MAX];
    int n = published(path);
    if (n >= 0 && !(flags & O_PATH)) return device_open(dirfd, path, flags, mode, n);
    return REAL(openat)(dirfd, redirect(path, buf), flags, mode);
}


static mode_t open_mode(int flags, va_list ap) {
    return (flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE ? (mode_t)va_arg(ap, int) : 0;
}

EXPORT int openat(int dirfd, const char *path, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    mode_t mode = open_mode(flags, ap);
    va_end(ap);
    return do_openat(dirfd, path, flags, mode);
}

EXPORT int openat64(int dirfd, const char *path, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    mode_t mode = open_mode(flags, ap);
    va_end(ap);
    return do_openat(dirfd, path, flags, mode);
}

EXPORT int open(const char *path, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    mode_t mode = open_mode(flags, ap);
    va_end(ap);
    return do_openat(AT_FDCWD, path, flags, mode);
}

EXPORT int open64(const char *path, int flags, ...) {
    va_list ap;
    va_start(ap, flags);
    mode_t mode = open_mode(flags, ap);
    va_end(ap);
    return do_openat(AT_FDCWD, path, flags, mode);
}

// Fortified callers reach these when the mode argument is known to be absent.
EXPORT int __open_2(const char *path, int flags) { return do_openat(AT_FDCWD, path, flags, 0); }
EXPORT int __openat_2(int dirfd, const char *path, int flags) { return do_openat(dirfd, path, flags, 0); }

EXPORT int close(int fd) {
    if (dev_of_fd(fd) >= 0) {
        atomic_store(&fd_dev[fd], 0);
        return pw.close(fd);
    }
    return REAL(close)(fd);
}

EXPORT int dup(int fd) {
    int n = dev_of_fd(fd);
    if (n < 0) return REAL(dup)(fd);
    int r = pw.dup(fd);
    track(r, n);
    return r;
}

EXPORT int ioctl(int fd, int request, ...) {
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    if (dev_of_fd(fd) >= 0) return pw.ioctl(fd, (unsigned long)(unsigned int)request, arg);
    return REAL(ioctl)(fd, request, arg);
}

static void *device_mmap(void *addr, size_t len, int prot, int flags, int fd, off_t off) {
    void *p = pw.mmap(addr, len, prot, flags, fd, off);
    if (p == MAP_FAILED) return p;
    pthread_mutex_lock(&maps_lock);
    for (int i = 0; i < MAX_MAPS; i++)
        if (!maps[i].addr) {
            maps[i].addr = p, maps[i].len = len;
            atomic_fetch_add(&n_maps, 1);
            break;
        }
    pthread_mutex_unlock(&maps_lock);
    return p;
}

EXPORT void *mmap(void *addr, size_t len, int prot, int flags, int fd, off_t off) {
    if (dev_of_fd(fd) >= 0) return device_mmap(addr, len, prot, flags, fd, off);
    return REAL(mmap)(addr, len, prot, flags, fd, off);
}

EXPORT void *mmap64(void *addr, size_t len, int prot, int flags, int fd, off64_t off) {
    return mmap(addr, len, prot, flags, fd, (off_t)off);
}

static bool forget_map(void *addr) {
    bool found = false;
    pthread_mutex_lock(&maps_lock);
    for (int i = 0; i < MAX_MAPS; i++)
        if (maps[i].addr == addr) {
            maps[i].addr = NULL;
            atomic_fetch_sub(&n_maps, 1);
            found = true;
            break;
        }
    pthread_mutex_unlock(&maps_lock);
    return found;
}

EXPORT int munmap(void *addr, size_t len) {
    if (atomic_load_explicit(&n_maps, memory_order_relaxed) && forget_map(addr)) return pw.munmap(addr, len);
    return REAL(munmap)(addr, len);
}

EXPORT int fstatat(int dirfd, const char *path, struct stat *st, int flags) {
    char buf[PATH_MAX];
    int n = (flags & AT_EMPTY_PATH) && path && !*path ? dev_of_fd(dirfd) : published(path);
    if (n >= 0) return fake_stat(n, st);
    return REAL(fstatat)(dirfd, redirect(path, buf), st, flags);
}

EXPORT int fstatat64(int dirfd, const char *path, struct stat64 *st, int flags) {
    return fstatat(dirfd, path, (struct stat *)st, flags);
}
EXPORT int stat(const char *path, struct stat *st) { return fstatat(AT_FDCWD, path, st, 0); }
EXPORT int stat64(const char *path, struct stat64 *st) { return fstatat(AT_FDCWD, path, (struct stat *)st, 0); }
EXPORT int lstat(const char *path, struct stat *st) { return fstatat(AT_FDCWD, path, st, AT_SYMLINK_NOFOLLOW); }
EXPORT int lstat64(const char *path, struct stat64 *st) {
    return fstatat(AT_FDCWD, path, (struct stat *)st, AT_SYMLINK_NOFOLLOW);
}

EXPORT int fstat(int fd, struct stat *st) {
    int n = dev_of_fd(fd);
    return n >= 0 ? fake_stat(n, st) : REAL(fstat)(fd, st);
}
EXPORT int fstat64(int fd, struct stat64 *st) { return fstat(fd, (struct stat *)st); }

EXPORT int statx(int dirfd, const char *path, int flags, unsigned mask, struct statx *stx) {
    char buf[PATH_MAX];
    int n = (flags & AT_EMPTY_PATH) && path && !*path ? dev_of_fd(dirfd) : published(path);
    if (n >= 0) return fake_statx(n, stx);
    if (!REAL(statx)) {
        long a[6] = {dirfd, (long)redirect(path, buf), flags, mask, (long)stx, 0};
        return (int)pass_syscall(SYS_statx, a);
    }
    return REAL(statx)(dirfd, redirect(path, buf), flags, mask, stx);
}

EXPORT int faccessat(int dirfd, const char *path, int mode, int flags) {
    char buf[PATH_MAX];
    if (published(path) >= 0) return 0;
    return REAL(faccessat)(dirfd, redirect(path, buf), mode, flags);
}
EXPORT int access(const char *path, int mode) { return faccessat(AT_FDCWD, path, mode, 0); }

EXPORT char *realpath(const char *path, char *resolved) {
    if (published(path) < 0) return REAL(realpath)(path, resolved);
    if (!resolved && !(resolved = malloc(PATH_MAX))) return NULL;
    strlcpy(resolved, path, PATH_MAX);
    return resolved;
}

// Directory listings: /dev gains the published cameras and loses the phone's
// own video nodes; /sys/class/video4linux is listed from the generated folder.
static bool hidden_dev_entry(const char *name) {
    static const char *const prefixes[] = {"video", "v4l-subdev", "media"};
    for (size_t i = 0; i < sizeof prefixes / sizeof *prefixes; i++) {
        size_t len = strlen(prefixes[i]);
        if (!strncmp(name, prefixes[i], len) && name[len] >= '0' && name[len] <= '9') return true;
    }
    return false;
}

EXPORT DIR *opendir(const char *path) {
    char buf[PATH_MAX];
    DIR *dir = REAL(opendir)(redirect(path, buf));
    if (dir && path && (!strcmp(path, "/dev") || !strcmp(path, "/dev/"))) {
        pthread_mutex_lock(&dirs_lock);
        for (int i = 0; i < MAX_DIRS; i++)
            if (!dirs[i].dir) {
                dirs[i].dir = dir, dirs[i].next = 0;
                atomic_fetch_add(&n_dirs, 1);
                break;
            }
        pthread_mutex_unlock(&dirs_lock);
    }
    return dir;
}

static int dir_slot(DIR *dir) {
    if (!atomic_load_explicit(&n_dirs, memory_order_relaxed)) return -1;
    for (int i = 0; i < MAX_DIRS; i++)
        if (dirs[i].dir == dir) return i;
    return -1;
}

static struct dirent *dev_readdir(DIR *dir, struct dirent *(*next)(DIR *)) {
    int slot = dir_slot(dir);
    struct dirent *e;
    if (slot < 0) return next(dir);
    while ((e = next(dir)) && hidden_dev_entry(e->d_name)) {
    }
    if (e) return e;
    struct dirent *ent = &dirs[slot].ent;
    for (int n = dirs[slot].next; n < MAX_DEVS; n++) {
        if (!marker_exists(n)) continue;
        memset(ent, 0, sizeof *ent);
        ent->d_ino = 0x7634000 + n;
        ent->d_reclen = sizeof *ent;
        ent->d_type = DT_CHR;
        strlcpy(ent->d_name, "video", sizeof ent->d_name);
        append_number(ent->d_name, n);
        dirs[slot].next = n + 1;
        return ent;
    }
    dirs[slot].next = MAX_DEVS;
    return NULL;
}

EXPORT struct dirent *readdir(DIR *dir) { return dev_readdir(dir, REAL(readdir)); }

// struct dirent64 has the same layout as struct dirent on Bionic.
EXPORT struct dirent64 *readdir64(DIR *dir) {
    struct dirent *(*next)(DIR *) = REAL(readdir64) ? (struct dirent *(*)(DIR *))REAL(readdir64) : REAL(readdir);
    return (struct dirent64 *)dev_readdir(dir, next);
}

EXPORT void rewinddir(DIR *dir) {
    int slot = dir_slot(dir);
    if (slot >= 0) dirs[slot].next = 0;
    REAL(rewinddir)(dir);
}

EXPORT int closedir(DIR *dir) {
    int slot = dir_slot(dir);
    if (slot >= 0) {
        pthread_mutex_lock(&dirs_lock);
        dirs[slot].dir = NULL;
        atomic_fetch_sub(&n_dirs, 1);
        pthread_mutex_unlock(&dirs_lock);
    }
    return REAL(closedir)(dir);
}

// libv4l2 and some runtimes call syscall() directly. Calls that name a
// published device, one of its descriptors, or the sysfs folder are answered
// as above. Everything else, including the C library's own futex calls, goes
// straight to the kernel.
EXPORT long syscall(long number, ...) {
    va_list ap;
    va_start(ap, number);
    long a[6];
    for (int i = 0; i < 6; i++) a[i] = va_arg(ap, long);
    va_end(ap);
    const char *path = (const char *)a[1];
    char buf[PATH_MAX];
    switch (number) {
    case SYS_openat:
        if (published(path) >= 0 || redirect(path, buf) != path)
            return do_openat((int)a[0], path, (int)a[2], (mode_t)a[3]);
        break;
    case SYS_close:
        if (dev_of_fd((int)a[0]) >= 0) return close((int)a[0]);
        break;
    case SYS_ioctl:
        if (dev_of_fd((int)a[0]) >= 0) return pw.ioctl((int)a[0], (unsigned long)a[1], (void *)a[2]);
        break;
    case SYS_mmap:
        if (dev_of_fd((int)a[4]) >= 0)
            return (long)device_mmap((void *)a[0], (size_t)a[1], (int)a[2], (int)a[3], (int)a[4], (off_t)a[5]);
        break;
    case SYS_munmap:
        if (atomic_load_explicit(&n_maps, memory_order_relaxed) && forget_map((void *)a[0]))
            return pw.munmap((void *)a[0], (size_t)a[1]);
        break;
    case SYS_newfstatat:
        if (published(path) >= 0 || redirect(path, buf) != path ||
            (((int)a[3] & AT_EMPTY_PATH) && path && !*path && dev_of_fd((int)a[0]) >= 0))
            return fstatat((int)a[0], path, (struct stat *)a[2], (int)a[3]);
        break;
    case SYS_fstat:
        if (dev_of_fd((int)a[0]) >= 0) return fstat((int)a[0], (struct stat *)a[1]);
        break;
    case SYS_faccessat:
        if (published(path) >= 0 || redirect(path, buf) != path) return faccessat((int)a[0], path, (int)a[2], 0);
        break;
    case SYS_statx:
        if (published(path) >= 0 || redirect(path, buf) != path ||
            (((int)a[2] & AT_EMPTY_PATH) && path && !*path && dev_of_fd((int)a[0]) >= 0))
            return statx((int)a[0], path, (int)a[2], (unsigned)a[3], (struct statx *)a[4]);
        break;
    }
    return pass_syscall(number, a);
}
