// Preload that presents the phone's KGSL or Mali GPU as the DRM render node
// /dev/dri/renderD128, so VA-API, GBM and DRM programs find it where Linux
// keeps it, with no per-program device setting. Build in native Termux:
//   clang -O2 -Wall -shared -fPIC -U_FORTIFY_SOURCE -o libandroid-vaapi-render-node.so render-node.c
//
// The phone's own /dev/dri nodes belong to the display controller and SELinux
// denies them to apps, so programs that scan /dev/dri find nothing usable.
// When /dev/kgsl-3d0 or /dev/mali0 can be opened, this library:
//   - lists only renderD128 in /dev/dri, and hides card0;
//   - reports renderD128 as character device 226:128 to stat, fstat, statx
//     and access, before and after it is opened;
//   - opens that GPU device for it;
//   - answers DRM_IOCTL_VERSION with "kgsl", the driver name Termux:VA's Mesa
//     loads for KGSL and libva maps to kgsl_drv_video.so, and the DRM
//     capability queries GBM makes. Mali reports "termuxva" for libva's
//     existing driver alias; its VA driver uses CPU surfaces and MediaCodec.
//     Other ioctls go to the underlying device;
//   - serves /sys/class/drm and /sys/dev/char/226:* from the folder
//     "render-node-sys" beside this library ($ANDROID_VAAPI_RENDER_NODE_SYS), which
//     describes a platform device as libdrm's drmGetDevice2 expects.
// Everything else passes to the next definition unchanged.
//
// The C library calls these wrappers during its own start-up and its futex
// waits go through syscall(), so no path here allocates or formats unless it
// names this device. syscall() hands everything else to the next definition,
// such as another device preload's, found once at load time so that no lookup
// runs inside a futex wait.
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
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define EXPORT __attribute__((visibility("default")))
#define DRM_MAJOR 226
#define RENDER_MINOR 128
#define MAX_FDS 4096
#define MAX_DIRS 16
#define NODE "/dev/dri/renderD128"
#define DRI "/dev/dri"
#define KGSL "/dev/kgsl-3d0"
#define MALI "/dev/mali0"

// From the kernel's drm.h, which Termux does not install.
struct drm_version {
    int version_major, version_minor, version_patchlevel;
    size_t name_len;
    char *name;
    size_t date_len;
    char *date;
    size_t desc_len;
    char *desc;
};
struct drm_get_cap {
    unsigned long long capability, value;
};
#define DRM_IOCTL_VERSION _IOWR('d', 0x00, struct drm_version)
#define DRM_IOCTL_GET_CAP _IOWR('d', 0x0c, struct drm_get_cap)
#define DRM_CAP_PRIME 0x5
#define DRM_CAP_TIMESTAMP_MONOTONIC 0x6
#define DRM_PRIME_CAP_IMPORT 0x1
#define DRM_PRIME_CAP_EXPORT 0x2

static struct {
    int (*openat)(int, const char *, int, ...);
    int (*close)(int);
    int (*dup)(int);
    int (*dup3)(int, int, int);
    int (*fcntl)(int, int, ...);
    int (*ioctl)(int, int, ...);
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
    ssize_t (*readlinkat)(int, const char *, char *, size_t);
} real;

// Looking a function up twice is harmless, so concurrent first calls need no lock.
static void *resolve(void **slot, const char *name) {
    void *p = dlsym(RTLD_NEXT, name);
    __atomic_store_n(slot, p, __ATOMIC_RELEASE);
    return p;
}
#define REAL(name)                                                                                 \
    ((__typeof__(real.name))(__atomic_load_n((void **)&real.name, __ATOMIC_ACQUIRE)                \
                                 ?: resolve((void **)&real.name, #name)))

static _Atomic bool node_fd[MAX_FDS];
static struct { DIR *dir; bool listed; struct dirent ent; } dirs[MAX_DIRS];
static atomic_int n_dirs;
static pthread_mutex_t dirs_lock = PTHREAD_MUTEX_INITIALIZER;

#if defined(__aarch64__)
static long raw_syscall(long n, long a, long b, long c, long d, long e, long f) {
    register long x8 __asm__("x8") = n, x0 __asm__("x0") = a, x1 __asm__("x1") = b, x2 __asm__("x2") = c,
                  x3 __asm__("x3") = d, x4 __asm__("x4") = e, x5 __asm__("x5") = f;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory", "cc");
    return x0;
}
#else
#error "raw system calls are implemented for aarch64 only"
#endif

static long (*next_syscall)(long, ...);

__attribute__((constructor)) static void find_next_syscall(void) { next_syscall = dlsym(RTLD_NEXT, "syscall"); }

static long pass_syscall(long n, const long *a) {
    if (next_syscall) return next_syscall(n, a[0], a[1], a[2], a[3], a[4], a[5]);
    long r = raw_syscall(n, a[0], a[1], a[2], a[3], a[4], a[5]);
    if ((unsigned long)r > -4096UL) {
        errno = (int)-r;
        return -1;
    }
    return r;
}

// Only inspect the GPU for paths naming the emulated device. Prefer the
// established KGSL route when both nodes are present.
static const char *gpu_device(void) {
    if (REAL(faccessat)(AT_FDCWD, KGSL, R_OK | W_OK, 0) == 0) return KGSL;
    if (REAL(faccessat)(AT_FDCWD, MALI, R_OK | W_OK, 0) == 0) return MALI;
    return NULL;
}

static bool available(void) {
    int saved = errno;
    bool ok = gpu_device() != NULL;
    errno = saved;
    return ok;
}

static bool same(const char *path, const char *want) {
    // Accept a trailing slash on directories, as shells and Python produce.
    size_t len = strlen(want);
    return path && !strncmp(path, want, len) && (!path[len] || (path[len] == '/' && !path[len + 1]));
}

static bool is_node(const char *path) { return path && !strcmp(path, NODE) && available(); }

// Other entries of /dev/dri: the display controller's nodes, which apps cannot use.
static bool is_hidden(const char *path) {
    return path && !strncmp(path, DRI "/", sizeof DRI) && strcmp(path, NODE) && path[sizeof DRI] &&
           available();
}

static bool is_tracked(int fd) {
    return fd >= 0 && fd < MAX_FDS && atomic_load_explicit(&node_fd[fd], memory_order_relaxed);
}

static int track(int fd, bool on) {
    if (fd >= 0 && fd < MAX_FDS) atomic_store(&node_fd[fd], on);
    return fd;
}

static void sys_dir(char *buf) {
    const char *dir = getenv("ANDROID_VAAPI_RENDER_NODE_SYS");
    Dl_info info;
    if (dir && *dir) {
        strlcpy(buf, dir, PATH_MAX);
    } else if (dladdr((void *)sys_dir, &info) && info.dli_fname) {
        strlcpy(buf, info.dli_fname, PATH_MAX);
        char *slash = strrchr(buf, '/');
        if (slash) slash[1] = 0;
        const char *gpu = gpu_device();
        strlcat(buf, gpu && !strcmp(gpu, MALI) ? "render-node-sys/mali" : "render-node-sys", PATH_MAX);
    } else {
        buf[0] = 0;
    }
}

// /sys/class/drm, and /sys/dev/char entries for major 226, come from the folder.
static const char *redirect(const char *path, char *buf) {
    static const char *const roots[] = {"/sys/class/drm", "/sys/dev/char/226:"};
    if (!path || strncmp(path, "/sys/", 5)) return path;
    for (size_t i = 0; i < sizeof roots / sizeof *roots; i++) {
        size_t len = strlen(roots[i]);
        if (strncmp(path, roots[i], len) || (i == 0 && path[len] && path[len] != '/')) continue;
        if (!available()) return path;
        sys_dir(buf);
        if (!buf[0]) return path;
        strlcat(buf, path + 4, PATH_MAX);  // keeps the leading "/class/..." or "/dev/..."
        return buf;
    }
    return path;
}

static int fake_stat(struct stat *st) {
    const char *gpu = gpu_device();
    if (!gpu) { errno = ENOENT; return -1; }
    if (REAL(fstatat)(AT_FDCWD, gpu, st, 0) < 0) return -1;
    st->st_mode = S_IFCHR | 0666;
    st->st_rdev = makedev(DRM_MAJOR, RENDER_MINOR);
    st->st_ino = 0x44524d80;
    return 0;
}

static int fake_statx(struct statx *stx) {
    struct stat st;
    if (fake_stat(&st) < 0) return -1;
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
    stx->stx_rdev_major = DRM_MAJOR;
    stx->stx_rdev_minor = RENDER_MINOR;
    stx->stx_dev_major = major(st.st_dev);
    stx->stx_dev_minor = minor(st.st_dev);
    return 0;
}

static int do_openat(int dirfd, const char *path, int flags, mode_t mode) {
    char buf[PATH_MAX];
    if (is_node(path) && !(flags & O_PATH)) {
        const char *gpu = gpu_device();
        if (!gpu) { errno = ENOENT; return -1; }
        return track(REAL(openat)(AT_FDCWD, gpu, flags, mode), true);
    }
    if (is_hidden(path)) {
        errno = ENOENT;
        return -1;
    }
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

EXPORT int __open_2(const char *path, int flags) { return do_openat(AT_FDCWD, path, flags, 0); }
EXPORT int __openat_2(int dirfd, const char *path, int flags) { return do_openat(dirfd, path, flags, 0); }

EXPORT int close(int fd) {
    if (is_tracked(fd)) track(fd, false);
    return REAL(close)(fd);
}

EXPORT int dup(int fd) {
    int r = REAL(dup)(fd);
    return is_tracked(fd) ? track(r, true) : r;
}

EXPORT int dup3(int fd, int to, int flags) {
    int r = REAL(dup3)(fd, to, flags);
    return r >= 0 ? track(r, is_tracked(fd)) : r;
}

EXPORT int dup2(int fd, int to) {
    if (fd == to) return fcntl(fd, F_GETFD) < 0 ? -1 : to;
    return dup3(fd, to, 0);
}

// Mesa and libva duplicate the device with F_DUPFD_CLOEXEC.
EXPORT int fcntl(int fd, int cmd, ...) {
    va_list ap;
    va_start(ap, cmd);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    int r = REAL(fcntl)(fd, cmd, arg);
    if ((cmd == F_DUPFD || cmd == F_DUPFD_CLOEXEC) && r >= 0 && is_tracked(fd)) track(r, true);
    return r;
}

static int node_ioctl(int fd, unsigned long request, void *arg) {
    if (request == DRM_IOCTL_VERSION) {
        struct drm_version *v = arg;
        const char *gpu = gpu_device();
        const char *name = gpu && !strcmp(gpu, MALI) ? "termuxva" : "kgsl";
        size_t len = strlen(name);
        size_t room = v->name_len;
        v->version_major = 1, v->version_minor = 0, v->version_patchlevel = 0;
        v->name_len = len, v->date_len = 0, v->desc_len = 0;
        if (v->name && room) memcpy(v->name, name, room < len ? room : len);
        return 0;
    }
    if (request == DRM_IOCTL_GET_CAP) {
        // Answer only what GBM probes; claim no modifiers or dumb buffers.
        struct drm_get_cap *cap = arg;
        cap->value = cap->capability == DRM_CAP_PRIME ? DRM_PRIME_CAP_IMPORT | DRM_PRIME_CAP_EXPORT
                     : cap->capability == DRM_CAP_TIMESTAMP_MONOTONIC ? 1
                                                                       : 0;
        return 0;
    }
    return REAL(ioctl)(fd, (int)request, arg);
}

EXPORT int ioctl(int fd, int request, ...) {
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    if (is_tracked(fd)) return node_ioctl(fd, (unsigned long)(unsigned int)request, arg);
    return REAL(ioctl)(fd, request, arg);
}

EXPORT int fstatat(int dirfd, const char *path, struct stat *st, int flags) {
    char buf[PATH_MAX];
    if ((flags & AT_EMPTY_PATH) && path && !*path && is_tracked(dirfd)) return fake_stat(st);
    if (is_node(path)) return fake_stat(st);
    if (is_hidden(path)) {
        errno = ENOENT;
        return -1;
    }
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

EXPORT int fstat(int fd, struct stat *st) { return is_tracked(fd) ? fake_stat(st) : REAL(fstat)(fd, st); }
EXPORT int fstat64(int fd, struct stat64 *st) { return fstat(fd, (struct stat *)st); }

EXPORT int statx(int dirfd, const char *path, int flags, unsigned mask, struct statx *stx) {
    char buf[PATH_MAX];
    if (((flags & AT_EMPTY_PATH) && path && !*path && is_tracked(dirfd)) || is_node(path)) return fake_statx(stx);
    if (is_hidden(path)) {
        errno = ENOENT;
        return -1;
    }
    if (!REAL(statx)) {
        long a[6] = {dirfd, (long)redirect(path, buf), flags, mask, (long)stx, 0};
        return (int)pass_syscall(SYS_statx, a);
    }
    return REAL(statx)(dirfd, redirect(path, buf), flags, mask, stx);
}

EXPORT int faccessat(int dirfd, const char *path, int mode, int flags) {
    char buf[PATH_MAX];
    if (is_node(path)) return 0;
    if (is_hidden(path)) {
        errno = ENOENT;
        return -1;
    }
    return REAL(faccessat)(dirfd, redirect(path, buf), mode, flags);
}
EXPORT int access(const char *path, int mode) { return faccessat(AT_FDCWD, path, mode, 0); }

EXPORT char *realpath(const char *path, char *resolved) {
    char buf[PATH_MAX];
    if (is_node(path)) {
        if (!resolved && !(resolved = malloc(PATH_MAX))) return NULL;
        strlcpy(resolved, path, PATH_MAX);
        return resolved;
    }
    return REAL(realpath)(redirect(path, buf), resolved);
}

EXPORT ssize_t readlinkat(int dirfd, const char *path, char *out, size_t size) {
    char buf[PATH_MAX];
    return REAL(readlinkat)(dirfd, redirect(path, buf), out, size);
}
EXPORT ssize_t readlink(const char *path, char *out, size_t size) { return readlinkat(AT_FDCWD, path, out, size); }

// /dev/dri lists only renderD128; /sys/class/drm is listed from the folder.
EXPORT DIR *opendir(const char *path) {
    char buf[PATH_MAX];
    DIR *dir = REAL(opendir)(redirect(path, buf));
    if (dir && same(path, DRI) && available()) {
        pthread_mutex_lock(&dirs_lock);
        for (int i = 0; i < MAX_DIRS; i++)
            if (!dirs[i].dir) {
                dirs[i].dir = dir, dirs[i].listed = false;
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

static struct dirent *dri_readdir(DIR *dir, struct dirent *(*next)(DIR *)) {
    int slot = dir_slot(dir);
    struct dirent *e;
    if (slot < 0) return next(dir);
    while ((e = next(dir)) && strcmp(e->d_name, ".") && strcmp(e->d_name, "..")) {
    }
    if (e) return e;
    if (dirs[slot].listed) return NULL;
    struct dirent *ent = &dirs[slot].ent;
    memset(ent, 0, sizeof *ent);
    ent->d_ino = 0x44524d80;
    ent->d_reclen = sizeof *ent;
    ent->d_type = DT_CHR;
    strlcpy(ent->d_name, "renderD128", sizeof ent->d_name);
    dirs[slot].listed = true;
    return ent;
}

EXPORT struct dirent *readdir(DIR *dir) { return dri_readdir(dir, REAL(readdir)); }

// struct dirent64 has the same layout as struct dirent on Bionic.
EXPORT struct dirent64 *readdir64(DIR *dir) {
    struct dirent *(*next)(DIR *) = REAL(readdir64) ? (struct dirent *(*)(DIR *))REAL(readdir64) : REAL(readdir);
    return (struct dirent64 *)dri_readdir(dir, next);
}

EXPORT void rewinddir(DIR *dir) {
    int slot = dir_slot(dir);
    if (slot >= 0) dirs[slot].listed = false;
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

// Calls made through syscall() that name this device, its descriptors or its
// sysfs folder are answered as above; everything else, including the C
// library's futex calls, goes straight to the kernel.
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
        if (is_node(path) || is_hidden(path) || redirect(path, buf) != path)
            return do_openat((int)a[0], path, (int)a[2], (mode_t)a[3]);
        break;
    case SYS_close:
        if (is_tracked((int)a[0])) return close((int)a[0]);
        break;
    case SYS_ioctl:
        if (is_tracked((int)a[0])) return node_ioctl((int)a[0], (unsigned long)a[1], (void *)a[2]);
        break;
    case SYS_dup:
        if (is_tracked((int)a[0])) return dup((int)a[0]);
        break;
    case SYS_dup3:
        if (is_tracked((int)a[0]) || is_tracked((int)a[1])) return dup3((int)a[0], (int)a[1], (int)a[2]);
        break;
    case SYS_fcntl:
        if (is_tracked((int)a[0])) return fcntl((int)a[0], (int)a[1], a[2]);
        break;
    case SYS_newfstatat:
        if (is_node(path) || is_hidden(path) || redirect(path, buf) != path ||
            (((int)a[3] & AT_EMPTY_PATH) && path && !*path && is_tracked((int)a[0])))
            return fstatat((int)a[0], path, (struct stat *)a[2], (int)a[3]);
        break;
    case SYS_fstat:
        if (is_tracked((int)a[0])) return fstat((int)a[0], (struct stat *)a[1]);
        break;
    case SYS_faccessat:
        if (is_node(path) || is_hidden(path) || redirect(path, buf) != path)
            return faccessat((int)a[0], path, (int)a[2], 0);
        break;
    case SYS_statx:
        if (is_node(path) || is_hidden(path) || redirect(path, buf) != path ||
            (((int)a[2] & AT_EMPTY_PATH) && path && !*path && is_tracked((int)a[0])))
            return statx((int)a[0], path, (int)a[2], (unsigned)a[3], (struct statx *)a[4]);
        break;
    }
    return pass_syscall(number, a);
}
