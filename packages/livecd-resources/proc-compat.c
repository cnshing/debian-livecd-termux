/* SPDX-License-Identifier: MIT
 * On-demand procfs/sysfs compatibility for dynamically linked native clients.
 * Kernel counters are read by shell, transported as bytes, then exposed through
 * anonymous memfds. A /proc enumeration owns one process snapshot; it is freed
 * when that enumeration closes. No sampler, timer, or disk statistics files.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "livecd-resources.h"

static __thread int inside;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static char legacy_gtop[PATH_MAX], legacy_htop[PATH_MAX];
#define SYMBOL(name) static __typeof__(&name) next_##name
#define EARLY_RESULT(name, arguments, failure) \
    if (!next_##name) { \
        next_##name = dlsym(RTLD_NEXT, #name); \
        if (!next_##name) { errno = ENOSYS; return failure; } \
        return next_##name arguments; \
    }
SYMBOL(openat); SYMBOL(close); SYMBOL(fstat); SYMBOL(fstatat); SYMBOL(lseek);
SYMBOL(opendir); SYMBOL(fdopendir); SYMBOL(readdir); SYMBOL(closedir); SYMBOL(rewinddir);
SYMBOL(fopen); SYMBOL(fclose); SYMBOL(fseek); SYMBOL(fseeko); SYMBOL(rewind);
SYMBOL(readlinkat); SYMBOL(faccessat);
SYMBOL(dup); SYMBOL(dup2); SYMBOL(dup3); SYMBOL(write); SYMBOL(fcntl);

struct row { unsigned pid, uid, gid, owner; char *fields[10]; };
struct snapshot { char *bytes; struct row *rows; size_t count; unsigned refs; struct snapshot *threads; };
struct file {
    int fd, backing;
    dev_t device;
    ino_t inode;
    char *path;
    struct snapshot *snapshot;
    struct file *next;
};
struct directory {
    DIR *dir;
    int fd;
    size_t cursor;
    int exhausted;
    char *names, *name_cursor;
    struct dirent entry;
    struct directory *next;
};
static struct file *files;
static struct directory *directories;

static __thread int fork_locked;
static void before_fork(void) { if (!inside) { pthread_mutex_lock(&mutex); fork_locked = 1; } }
static void after_fork(void) { if (fork_locked) { fork_locked = 0; pthread_mutex_unlock(&mutex); } }

__attribute__((constructor)) static void initialize(void) {
    inside++;
#define LOAD(name) next_##name = dlsym(RTLD_NEXT, #name)
    LOAD(openat); LOAD(close); LOAD(fstat); LOAD(fstatat); LOAD(lseek);
    LOAD(opendir); LOAD(fdopendir); LOAD(readdir); LOAD(closedir); LOAD(rewinddir);
    LOAD(fopen); LOAD(fclose); LOAD(fseek); LOAD(fseeko); LOAD(rewind);
    LOAD(readlinkat); LOAD(faccessat);
    LOAD(dup); LOAD(dup2); LOAD(dup3); LOAD(write); LOAD(fcntl);
    const char *prefix = getenv("PREFIX");
    if (!prefix) prefix = "/data/data/com.termux/files/usr";
    snprintf(legacy_gtop, sizeof legacy_gtop, "%s/var/libgtop/stat", prefix);
    snprintf(legacy_htop, sizeof legacy_htop, "%s/var/htop/stat", prefix);
    pthread_atfork(before_fork, after_fork, after_fork);
    inside--;
}

static int numeric(const char *name) {
    if (!*name) return 0;
    for (; *name; name++) if (*name < '0' || *name > '9') return 0;
    return 1;
}

static int candidate(const char *path) {
    if (!path) return 0;
    return *path != '/' || !strncmp(path, "/proc", 5) ||
        !strncmp(path, "/sys/class/thermal", 18) || !strncmp(path, "/sys/class/kgsl/", 16) ||
        !strcmp(path, legacy_gtop) || !strcmp(path, legacy_htop);
}

static int row_compare(const void *left, const void *right) {
    unsigned a = ((const struct row *)left)->pid, b = ((const struct row *)right)->pid;
    return (a > b) - (a < b);
}

static struct snapshot *collect_kind(int threads) {
    char *bytes = NULL;
    size_t length = 0;
    int error = livecd_resources_snapshot(threads ? "threads" : "processes-v2", &bytes, &length);
    if (error) { errno = error; return NULL; }
    struct snapshot *snapshot = calloc(1, sizeof *snapshot);
    if (!snapshot) { livecd_resources_free(bytes); return NULL; }
    snapshot->bytes = bytes; snapshot->refs = 1;
    for (size_t i = 0; i < length; i++) if (bytes[i] == '\n') snapshot->count++;
    snapshot->rows = calloc(snapshot->count ? snapshot->count : 1, sizeof *snapshot->rows);
    if (!snapshot->rows) { livecd_resources_free(bytes); free(snapshot); return NULL; }
    size_t count = 0;
    char *save, *line = strtok_r(bytes, "\n", &save);
    for (; line; line = strtok_r(NULL, "\n", &save)) {
        struct row row = {0};
        char *field = line;
        size_t n = 0;
        for (; n < (threads ? 6u : 10u); n++) {
            row.fields[n] = field;
            char *tab = strchr(field, '\t');
            if (!tab) { n++; break; }
            *tab = 0; field = tab + 1;
        }
        if (threads) {
            if (n != 6 || strcmp(row.fields[0], "T") || !numeric(row.fields[1]) || !numeric(row.fields[2]) || !numeric(row.fields[3]) || !numeric(row.fields[4])) continue;
            row.owner = (unsigned)strtoul(row.fields[1], NULL, 10);
            row.pid = (unsigned)strtoul(row.fields[2], NULL, 10);
            row.uid = (unsigned)strtoul(row.fields[3], NULL, 10);
            row.gid = (unsigned)strtoul(row.fields[4], NULL, 10);
            row.fields[3] = row.fields[5];
            row.fields[4] = row.fields[5] = row.fields[6] = row.fields[7] = row.fields[8] = "";
            snapshot->rows[count++] = row;
            continue;
        }
        if (n != 10 || strcmp(row.fields[0], "P") || !numeric(row.fields[1]) ||
            !numeric(row.fields[2]) || !numeric(row.fields[9])) continue;
        row.pid = (unsigned)strtoul(row.fields[1], NULL, 10);
        row.uid = (unsigned)strtoul(row.fields[2], NULL, 10);
        row.gid = (unsigned)strtoul(row.fields[9], NULL, 10);
        snapshot->rows[count++] = row;
    }
    snapshot->count = count;
    qsort(snapshot->rows, count, sizeof *snapshot->rows, row_compare);
    return snapshot;
}

static void release(struct snapshot *snapshot) {
    if (snapshot && --snapshot->refs == 0) {
        release(snapshot->threads); free(snapshot->rows); livecd_resources_free(snapshot->bytes); free(snapshot);
    }
}

static struct file *find_file(int fd) {
    for (struct file *file = files; file; file = file->next) {
        if (file->fd != fd) continue;
        struct stat metadata;
        if (next_fstat(fd, &metadata) == 0 && metadata.st_dev == file->device && metadata.st_ino == file->inode)
            return file;
    }
    return NULL;
}

static void forget(int fd) {
    struct file **link = &files;
    while (*link) {
        struct file *file = *link;
        if (file->fd != fd) { link = &file->next; continue; }
        *link = file->next;
        if (file->backing >= 0 && file->backing != file->fd) next_close(file->backing);
        release(file->snapshot); free(file->path); free(file);
    }
}

static int remember(int fd, const char *path, struct snapshot *snapshot) {
    struct file *file = calloc(1, sizeof *file);
    if (!file) return -1;
    file->path = strdup(path);
    struct stat metadata;
    if (!file->path || next_fstat(fd, &metadata)) { free(file->path); free(file); return -1; }
    forget(fd);
    file->fd = fd; file->backing = -1; file->device = metadata.st_dev; file->inode = metadata.st_ino;
    file->snapshot = snapshot;
    if (snapshot) snapshot->refs++;
    file->next = files; files = file;
    return 0;
}

/* Resolve openat paths without resolving symlinks or changing kernel semantics
 * for anything outside the fixed procfs/sysfs read interface. */
static int resolve(int fd, const char *name, char path[PATH_MAX]) {
    int length;
    if (*name == '/') length = snprintf(path, PATH_MAX, "%s", name);
    else {
        char base[PATH_MAX];
        struct file *file = fd == AT_FDCWD ? NULL : find_file(fd);
        if (file) snprintf(base, sizeof base, "%s", file->path);
        else if (fd == AT_FDCWD) { if (!getcwd(base, sizeof base)) return 0; }
        else {
            char link[64]; snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
            ssize_t n = next_readlinkat(AT_FDCWD, link, base, sizeof base - 1);
            if (n < 0) return 0;
            base[n] = 0;
        }
        length = snprintf(path, PATH_MAX, "%s/%s", base, name);
    }
    if (length < 0 || length >= PATH_MAX || strstr(path, "/../")) return 0;
    while (length > 1 && path[length - 1] == '/') path[--length] = 0;
    while (length > 2 && !strcmp(path + length - 2, "/.")) path[length -= 2] = 0;
    // Termux libgtop ships a frozen procstat at this private path.
    if (!strcmp(path, legacy_gtop) || !strcmp(path, legacy_htop)) strcpy(path, "/proc/stat");
    return !strncmp(path, "/proc", 5) || !strncmp(path, "/sys/class/thermal", 18) || !strncmp(path, "/sys/class/kgsl/", 16);
}

static struct snapshot *root_snapshot(void) {
    for (struct directory *directory = directories; directory; directory = directory->next) {
        struct file *file = find_file(directory->fd);
        if (file && file->snapshot && !strcmp(file->path, "/proc")) return file->snapshot;
    }
    return NULL;
}

static struct row *lookup(const char *path, const char **leaf) {
    if (strncmp(path, "/proc/", 6)) return NULL;
    char *end;
    unsigned pid = (unsigned)strtoul(path + 6, &end, 10), owner = 0;
    if (!pid || (*end && *end != '/')) return NULL;
    *leaf = *end ? end + 1 : end;
    if (!strncmp(*leaf, "task/", 5)) {
        owner = pid;
        pid = (unsigned)strtoul(*leaf + 5, &end, 10);
        if (!pid || (*end && *end != '/')) return NULL;
        *leaf = *end ? end + 1 : end;
    }
    struct row key = {.pid = pid};
    for (struct directory *directory = directories; directory; directory = directory->next) {
        struct file *file = find_file(directory->fd);
        if (!file) continue;
        struct snapshot *snapshot = file->snapshot;
        if (owner && snapshot && snapshot->threads) snapshot = snapshot->threads;
        if (!snapshot) continue;
        struct row *row = bsearch(&key, snapshot->rows, snapshot->count, sizeof *snapshot->rows, row_compare);
        if (row && row->owner == owner) return row;
    }
    return NULL;
}

static int supported(const char *path) {
    const char *leaf = path;
    if (!strncmp(path, "/proc/", 6)) {
        leaf += 6;
        if (*leaf >= '0' && *leaf <= '9') {
            while (*leaf >= '0' && *leaf <= '9') leaf++;
            if (*leaf++ != '/') return 0;
            if (!strncmp(leaf, "task/", 5)) {
                leaf += 5;
                while (*leaf >= '0' && *leaf <= '9') leaf++;
                if (*leaf++ != '/') return 0;
            }
            const char *names[] = {"stat", "status", "statm", "cmdline", "io", "comm", "wchan", "oom_score", "oom_score_adj", "smaps_rollup", "exe"};
            for (size_t i = 0; i < sizeof names / sizeof *names; i++) if (!strcmp(leaf, names[i])) return 1;
            return 0;
        }
        const char *names[] = {"stat", "meminfo", "uptime", "loadavg", "net/dev", "diskstats", "vmstat", "pressure/cpu", "pressure/memory", "pressure/io"};
        for (size_t i = 0; i < sizeof names / sizeof *names; i++) if (!strcmp(leaf, names[i])) return 1;
        return 0;
    }
    if (!strncmp(path, "/sys/class/thermal/thermal_zone", 31)) {
        leaf = path + 31;
        const char *start = leaf;
        while (*leaf >= '0' && *leaf <= '9') leaf++;
        return leaf != start && *leaf++ == '/' && (!strcmp(leaf, "type") || !strcmp(leaf, "temp"));
    }
    if (!strncmp(path, "/sys/class/kgsl/kgsl-3d0/", 25)) {
        leaf = path + 25;
        return !strcmp(leaf, "gpu_model") || !strcmp(leaf, "gpubusy") || !strcmp(leaf, "gpuclk") || !strcmp(leaf, "gpu_available_frequencies");
    }
    return 0;
}

static int unhex(const char *hex, char **data, size_t *length) {
    size_t size = strlen(hex);
    if (size % 2) { errno = EIO; return -1; }
    char *bytes = malloc(size / 2 + 1);
    if (!bytes) return -1;
    for (size_t i = 0; i < size; i += 2) {
        unsigned a = (unsigned char)hex[i], b = (unsigned char)hex[i + 1];
        a = a >= '0' && a <= '9' ? a - '0' : a >= 'a' && a <= 'f' ? a - 'a' + 10 : 16;
        b = b >= '0' && b <= '9' ? b - '0' : b >= 'a' && b <= 'f' ? b - 'a' + 10 : 16;
        if (a > 15 || b > 15) { free(bytes); errno = EIO; return -1; }
        bytes[i / 2] = (char)(a * 16 + b);
    }
    bytes[size / 2] = 0; *data = bytes; *length = size / 2;
    return 0;
}

static int contents(const char *path, int link, char **data, size_t *length) {
    const char *leaf = "";
    struct row *row = lookup(path, &leaf);
    if (row) {
        int column = link && !strcmp(leaf, "exe") ? 5 :
            !link && !strcmp(leaf, "stat") ? 3 : !link && !strcmp(leaf, "cmdline") ? 4 :
            !link && !strcmp(leaf, "status") ? 6 : !link && !strcmp(leaf, "statm") ? 7 :
            !link && !strcmp(leaf, "io") ? 8 : -1;
        if (column >= 0) {
            if (*row->fields[column] || (column == 4 && !row->owner)) return unhex(row->fields[column], data, length);
            if (!row->owner) { errno = EACCES; return -1; }
        }
        if (!link && !strcmp(leaf, "comm")) {
            char *stat; size_t size;
            if (unhex(row->fields[3], &stat, &size)) return -1;
            char *first = strchr(stat, '('), *last = strrchr(stat, ')');
            if (!first || !last || first >= last) { free(stat); errno = EIO; return -1; }
            *length = (size_t)(last - first); *data = malloc(*length + 1);
            if (*data) { memcpy(*data, first + 1, *length - 1); (*data)[*length - 1] = '\n'; (*data)[*length] = 0; }
            free(stat); return *data ? 0 : -1;
        }
    }
    char command[PATH_MAX + 8]; snprintf(command, sizeof command, "%s %s", link ? "link" : "read", path);
    int error = livecd_resources_snapshot(command, data, length);
    if (error) { errno = error; return -1; }
    return 0;
}

static int fill_fd(int fd, const char *path) {
    char *data; size_t length;
    if (contents(path, 0, &data, &length)) { ftruncate(fd, 0); return -1; }
    int result = 0;
    if (ftruncate(fd, 0) || next_lseek(fd, 0, SEEK_SET) < 0) result = -1;
    size_t offset = 0;
    while (!result && offset < length) {
        ssize_t written = write(fd, data + offset, length - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) { result = -1; break; }
        offset += (size_t)written;
    }
    livecd_resources_free(data);
    if (next_lseek(fd, 0, SEEK_SET) < 0) result = -1;
    return result;
}

static int process_directory(const char *path) {
    if (strncmp(path, "/proc/", 6)) return 0;
    const char *p = path + 6;
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') p++;
    if (!*p) return 1;
    if (!strcmp(p, "/task")) return 1;
    if (!strncmp(p, "/task/", 6)) return numeric(p + 6);
    return 0;
}

static int open_common(int dirfd, const char *name, int flags, mode_t mode) {
    if (!next_openat) return (int)syscall(SYS_openat, dirfd, name, flags, mode);
    if (inside || !candidate(name) || (flags & O_ACCMODE) != O_RDONLY || flags & (O_CREAT | O_TRUNC | O_APPEND | O_PATH))
        return next_openat(dirfd, name, flags, mode);
    inside++; pthread_mutex_lock(&mutex);
    char path[PATH_MAX];
    int result;
    if (!resolve(dirfd, name, path)) result = next_openat(dirfd, name, flags, mode);
    else if (!strcmp(path, "/proc") || !strcmp(path, "/sys/class/thermal") || process_directory(path)) {
        const char *leaf = "";
        struct row *row = lookup(path, &leaf);
        struct snapshot *root = root_snapshot();
        int tasks = strstr(path, "/task") && !strcmp(strstr(path, "/task"), "/task");
        if (tasks && root && !root->threads) root->threads = collect_kind(1);
        result = next_openat(dirfd, name, flags, mode);
        if (result < 0 && (row || !strcmp(path, "/sys/class/thermal") || (tasks && root && root->threads))) result = next_openat(AT_FDCWD, "/proc", flags, mode);
        if (result >= 0) {
            struct snapshot *snapshot = NULL;
            snapshot = tasks && root ? root->threads : root;
            if (remember(result, path, snapshot)) { next_close(result); result = -1; }
        }
    } else {
        // Accessible native files keep their real semantics. Protected CPU and
        // cached process snapshots always use the shared reader consistently.
        const char *leaf = "";
        struct row *row = lookup(path, &leaf);
        result = row || !strcmp(path, "/proc/stat") ? -1 : next_openat(dirfd, name, flags, mode);
        if (result < 0 && !(flags & O_DIRECTORY) && supported(path)) {
            result = (int)syscall(SYS_memfd_create, "livecd-proc", MFD_CLOEXEC);
            if (result >= 0) {
                if (fill_fd(result, path) || remember(result, path, NULL)) { int error = errno; next_close(result); result = -1; errno = error; }
                else {
                    // Android denies reopening a memfd via /proc/self/fd even
                    // for its creator. Enforce the virtual read-only view at
                    // the same libc boundary used by this compatibility layer.
                    find_file(result)->backing = result;
                    if (!(flags & O_CLOEXEC)) next_fcntl(result, F_SETFD, 0);
                }
            }
        }
    }
    int error = errno;
    pthread_mutex_unlock(&mutex); inside--; errno = error;
    return result;
}

int openat(int fd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) { va_list args; va_start(args, flags); mode = va_arg(args, int); va_end(args); }
    return open_common(fd, path, flags, mode);
}
int open(const char *path, int flags, ...) {
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) { va_list args; va_start(args, flags); mode = va_arg(args, int); va_end(args); }
    return open_common(AT_FDCWD, path, flags, mode);
}
int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) { va_list args; va_start(args, flags); mode = va_arg(args, int); va_end(args); }
    return open_common(AT_FDCWD, path, flags, mode);
}
int openat64(int fd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) { va_list args; va_start(args, flags); mode = va_arg(args, int); va_end(args); }
    return open_common(fd, path, flags, mode);
}
int __open_2(const char *path, int flags) { return open_common(AT_FDCWD, path, flags, 0); }
int __openat_2(int fd, const char *path, int flags) { return open_common(fd, path, flags, 0); }

int close(int fd) {
    if (!next_close) return (int)syscall(SYS_close, fd);
    if (inside) return next_close(fd);
    inside++; pthread_mutex_lock(&mutex); forget(fd);
    int result = next_close(fd), error = errno;
    pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}

static int duplicate(int fd, int target, int flags, int kind) {
    if (!next_dup) return kind == 0 ? (int)syscall(SYS_dup, fd) : (int)syscall(SYS_dup3, fd, target, flags);
    if (inside) return kind == 0 ? next_dup(fd) : kind == 1 ? next_dup2(fd, target) : next_dup3(fd, target, flags);
    inside++; pthread_mutex_lock(&mutex);
    struct file *original = find_file(fd);
    int result = kind == 0 ? next_dup(fd) : kind == 1 ? next_dup2(fd, target) : next_dup3(fd, target, flags);
    if (result >= 0 && result != fd) {
        if (original) {
            if (remember(result, original->path, original->snapshot)) { next_close(result); result = -1; }
            else if (original->backing >= 0) {
                struct file *copy = find_file(result);
                copy->backing = original->backing == original->fd ? result : next_fcntl(original->backing, F_DUPFD_CLOEXEC, 0);
                if (copy->backing < 0) { forget(result); next_close(result); result = -1; }
            }
        } else forget(result);
    }
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}
int dup(int fd) { return duplicate(fd, -1, 0, 0); }
int dup2(int fd, int target) { return duplicate(fd, target, 0, 1); }
int dup3(int fd, int target, int flags) { return duplicate(fd, target, flags, 2); }

ssize_t write(int fd, const void *buffer, size_t size) {
    if (!next_write) return (ssize_t)syscall(SYS_write, fd, buffer, size);
    if (inside) return next_write(fd, buffer, size);
    inside++; pthread_mutex_lock(&mutex);
    struct file *file = find_file(fd);
    int readonly = file && file->backing >= 0;
    pthread_mutex_unlock(&mutex); inside--;
    if (readonly) { errno = EBADF; return -1; }
    return next_write(fd, buffer, size);
}

int fcntl(int fd, int command, ...) {
    uintptr_t argument = 0;
    if (command != F_GETFD && command != F_GETFL && command != F_GETOWN && command != F_GETSIG &&
        command != F_GETLEASE && command != F_GETPIPE_SZ && command != F_GET_SEALS) {
        va_list args; va_start(args, command); argument = va_arg(args, uintptr_t); va_end(args);
    }
    if (!next_fcntl) return (int)syscall(SYS_fcntl, fd, command, argument);
    if (inside) return next_fcntl(fd, command, argument);
    inside++; pthread_mutex_lock(&mutex);
    struct file *file = find_file(fd);
    int result = next_fcntl(fd, command, argument);
    if (result >= 0 && file && command == F_GETFL && file->backing >= 0) result &= ~O_ACCMODE;
    if (result >= 0 && (command == F_DUPFD || command == F_DUPFD_CLOEXEC)) {
        if (file) {
            int backed = file->backing >= 0;
            if (remember(result, file->path, file->snapshot)) { next_close(result); result = -1; }
            else if (backed) find_file(result)->backing = result;
        } else forget(result);
    }
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}

static off_t seek_common(int fd, off_t offset, int whence) {
    if (inside || !next_lseek) return (off_t)syscall(SYS_lseek, fd, offset, whence);
    inside++; pthread_mutex_lock(&mutex);
    struct file *file = find_file(fd);
    off_t result;
    if (file && file->backing >= 0 && !offset && whence == SEEK_SET && fill_fd(file->backing, file->path)) result = -1;
    else result = next_lseek(fd, offset, whence);
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}
off_t lseek(int fd, off_t offset, int whence) { return seek_common(fd, offset, whence); }
off64_t lseek64(int fd, off64_t offset, int whence) { return seek_common(fd, offset, whence); }

FILE *fopen(const char *path, const char *mode) {
    EARLY_RESULT(fopen, (path, mode), NULL)
    if (inside || !candidate(path) || mode[0] != 'r' || strchr(mode, '+')) return next_fopen(path, mode);
    int flags = O_RDONLY | (strchr(mode, 'e') ? O_CLOEXEC : 0);
    int fd = open_common(AT_FDCWD, path, flags, 0);
    if (fd < 0) return NULL;
    FILE *stream = fdopen(fd, mode);
    if (!stream) close(fd);
    return stream;
}
FILE *fopen64(const char *path, const char *mode) { return fopen(path, mode); }
int fclose(FILE *stream) {
    EARLY_RESULT(fclose, (stream), EOF)
    if (inside) return next_fclose(stream);
    inside++; pthread_mutex_lock(&mutex); forget(fileno(stream));
    int result = next_fclose(stream), error = errno;
    pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}
static int refresh_stream(FILE *stream, off_t offset, int whence) {
    if (offset || whence != SEEK_SET) return 0;
    inside++; pthread_mutex_lock(&mutex);
    struct file *file = find_file(fileno(stream));
    int result = file && file->backing >= 0 ? fill_fd(file->backing, file->path) : 0;
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}
int fseek(FILE *stream, long offset, int whence) {
    EARLY_RESULT(fseek, (stream, offset, whence), -1)
    if (!inside && refresh_stream(stream, offset, whence)) return -1;
    return next_fseek(stream, offset, whence);
}
int fseeko(FILE *stream, off_t offset, int whence) {
    EARLY_RESULT(fseeko, (stream, offset, whence), -1)
    if (!inside && refresh_stream(stream, offset, whence)) return -1;
    return next_fseeko(stream, offset, whence);
}
int fseeko64(FILE *stream, off64_t offset, int whence) { return fseeko(stream, offset, whence); }
void rewind(FILE *stream) {
    if (!next_rewind) {
        next_rewind = dlsym(RTLD_NEXT, "rewind");
        if (next_rewind) next_rewind(stream);
        return;
    }
    if (!inside && refresh_stream(stream, 0, SEEK_SET)) {
        // Discard stdio's previously buffered bytes even after a failed read.
        next_rewind(stream); return;
    }
    next_rewind(stream);
}

static DIR *directory_common(int fd) {
    DIR *dir = next_fdopendir(fd);
    if (!dir) return NULL;
    struct file *file = find_file(fd);
    if (file && (!strcmp(file->path, "/proc") || (strstr(file->path, "/task") && !strcmp(strstr(file->path, "/task"), "/task")))) {
        struct snapshot *snapshot = !strcmp(file->path, "/proc") ? collect_kind(0) : file->snapshot;
        if (snapshot && snapshot == file->snapshot) snapshot->refs++;
        if (!snapshot) { int error = errno; forget(fd); next_closedir(dir); errno = error; return NULL; }
        release(file->snapshot); file->snapshot = snapshot;
        struct directory *directory = calloc(1, sizeof *directory);
        if (!directory) { forget(fd); next_closedir(dir); return NULL; }
        directory->dir = dir; directory->fd = fd;
        directory->next = directories; directories = directory;
    }
    if (file && !strcmp(file->path, "/sys/class/thermal")) {
        char *names; size_t length;
        int error = livecd_resources_snapshot("list /sys/class/thermal", &names, &length);
        if (error) { forget(fd); next_closedir(dir); errno = error; return NULL; }
        struct directory *directory = calloc(1, sizeof *directory);
        if (!directory) { livecd_resources_free(names); forget(fd); next_closedir(dir); return NULL; }
        directory->dir = dir; directory->fd = fd; directory->exhausted = 1;
        directory->names = directory->name_cursor = names;
        directory->next = directories; directories = directory;
    }
    return dir;
}
DIR *fdopendir(int fd) {
    EARLY_RESULT(fdopendir, (fd), NULL)
    if (inside) return next_fdopendir(fd);
    inside++; pthread_mutex_lock(&mutex);
    DIR *dir = directory_common(fd); int error = errno;
    pthread_mutex_unlock(&mutex); inside--; errno = error; return dir;
}
DIR *opendir(const char *path) {
    EARLY_RESULT(opendir, (path), NULL)
    if (inside || !candidate(path)) return next_opendir(path);
    int fd = open_common(AT_FDCWD, path, O_RDONLY | O_DIRECTORY | O_CLOEXEC, 0);
    if (fd < 0) return NULL;
    DIR *dir = fdopendir(fd);
    if (!dir) { int error = errno; close(fd); errno = error; }
    return dir;
}
struct dirent *readdir(DIR *dir) {
    EARLY_RESULT(readdir, (dir), NULL)
    if (inside) return next_readdir(dir);
    inside++; pthread_mutex_lock(&mutex);
    struct directory *directory = directories;
    while (directory && directory->dir != dir) directory = directory->next;
    struct dirent *result = NULL;
    if (!directory) result = next_readdir(dir);
    else {
        while (!directory->exhausted && (result = next_readdir(dir))) {
            if (!numeric(result->d_name)) break;
        }
        if (!result && directory->names) {
            char *name = directory->name_cursor;
            if (*name) {
                char *end = strchr(name, '\n');
                if (end) { *end = 0; directory->name_cursor = end + 1; }
                else directory->name_cursor += strlen(name);
                memset(&directory->entry, 0, sizeof directory->entry);
                directory->entry.d_ino = ++directory->cursor; directory->entry.d_type = DT_LNK;
                directory->entry.d_reclen = sizeof directory->entry;
                snprintf(directory->entry.d_name, sizeof directory->entry.d_name, "%s", name);
                result = &directory->entry;
            }
        }
        if (!result && !directory->names) {
            directory->exhausted = 1;
            struct file *file = find_file(directory->fd);
            if (file && file->snapshot && directory->cursor < file->snapshot->count) {
                struct row *row = &file->snapshot->rows[directory->cursor++];
                unsigned owner = !strcmp(file->path, "/proc") ? 0 : (unsigned)strtoul(file->path + 6, NULL, 10);
                while (row->owner != owner && directory->cursor < file->snapshot->count) row = &file->snapshot->rows[directory->cursor++];
                if (row->owner != owner) goto done;
                memset(&directory->entry, 0, sizeof directory->entry);
                directory->entry.d_ino = row->pid; directory->entry.d_type = DT_DIR;
                directory->entry.d_reclen = sizeof directory->entry;
                snprintf(directory->entry.d_name, sizeof directory->entry.d_name, "%u", row->pid);
                result = &directory->entry;
            }
        }
    }
done:;
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}
int closedir(DIR *dir) {
    EARLY_RESULT(closedir, (dir), -1)
    if (inside) return next_closedir(dir);
    inside++; pthread_mutex_lock(&mutex);
    struct directory **link = &directories;
    while (*link) {
        if ((*link)->dir != dir) { link = &(*link)->next; continue; }
        struct directory *old = *link; *link = old->next; livecd_resources_free(old->names); free(old); break;
    }
    forget(dirfd(dir)); int result = next_closedir(dir), error = errno;
    pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}
void rewinddir(DIR *dir) {
    if (!next_rewinddir) {
        next_rewinddir = dlsym(RTLD_NEXT, "rewinddir");
        if (next_rewinddir) next_rewinddir(dir);
        return;
    }
    if (inside) { next_rewinddir(dir); return; }
    inside++; pthread_mutex_lock(&mutex);
    for (struct directory *directory = directories; directory; directory = directory->next) {
        if (directory->dir != dir) continue;
        struct file *file = find_file(directory->fd);
        if (directory->names) {
            char *names = NULL; size_t length = 0;
            int error = livecd_resources_snapshot("list /sys/class/thermal", &names, &length);
            livecd_resources_free(directory->names);
            if (!names) names = calloc(1, 1);
            directory->names = directory->name_cursor = names;
            directory->exhausted = 1;
            directory->cursor = 0;
            if (error) errno = error;
            next_rewinddir(dir);
            pthread_mutex_unlock(&mutex); inside--; return;
        }
        if (file) { release(file->snapshot); file->snapshot = collect_kind(strcmp(file->path, "/proc") != 0); }
        directory->cursor = 0; directory->exhausted = 0;
    }
    next_rewinddir(dir); pthread_mutex_unlock(&mutex); inside--;
}

static int metadata(int fd, const char *name, struct stat *result, int flags) {
    if (!next_fstatat) return (int)syscall(SYS_newfstatat, fd, name, result, flags);
    if (inside || !candidate(name)) return next_fstatat(fd, name, result, flags);
    inside++; pthread_mutex_lock(&mutex);
    char path[PATH_MAX]; const char *leaf = "";
    int resolved = resolve(fd, name, path);
    struct row *row = resolved ? lookup(path, &leaf) : NULL;
    int value = next_fstatat(fd, name, result, flags);
    if (value < 0 && resolved && !row && (process_directory(path) || supported(path))) {
        char command[PATH_MAX + 8]; snprintf(command, sizeof command, "meta %s", path);
        char *data; size_t length;
        int error = livecd_resources_snapshot(command, &data, &length);
        if (!error) {
            unsigned long uid, gid, mode, links; unsigned long long inode;
            long long size, atime, mtime, ctime;
            if (sscanf(data, "%lu %lu %lu %lu %llu %lld %lld %lld %lld", &uid, &gid, &mode, &links, &inode, &size, &atime, &mtime, &ctime) == 9) {
                memset(result, 0, sizeof *result); result->st_uid = uid; result->st_gid = gid; result->st_mode = mode;
                result->st_nlink = links; result->st_ino = inode; result->st_size = size;
                result->st_atim.tv_sec = atime; result->st_mtim.tv_sec = mtime; result->st_ctim.tv_sec = ctime; value = 0;
            }
            livecd_resources_free(data);
        } else errno = error;
    }
    if (row && !*leaf) {
        memset(result, 0, sizeof *result); result->st_mode = S_IFDIR | 0555;
        result->st_uid = row->uid; result->st_gid = row->gid;
        result->st_ino = row->pid; result->st_nlink = 2; value = 0;
    }
    else if (row && supported(path) && strcmp(leaf, "exe")) {
        memset(result, 0, sizeof *result); result->st_mode = S_IFREG | 0444;
        result->st_uid = row->uid; result->st_gid = row->gid; result->st_nlink = 1; value = 0;
    }
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return value;
}
int stat(const char *path, struct stat *result) { return metadata(AT_FDCWD, path, result, 0); }
int lstat(const char *path, struct stat *result) { return metadata(AT_FDCWD, path, result, AT_SYMLINK_NOFOLLOW); }
int fstatat(int fd, const char *path, struct stat *result, int flags) { return metadata(fd, path, result, flags); }
int fstat(int fd, struct stat *result) {
    if (inside || !next_fstat) return (int)syscall(SYS_fstat, fd, result);
    inside++; pthread_mutex_lock(&mutex);
    struct file *file = find_file(fd); const char *leaf = "";
    struct row *row = file ? lookup(file->path, &leaf) : NULL;
    if (!row && file && file->snapshot && process_directory(file->path)) {
        const char *name = strrchr(file->path, '/');
        struct row key = {.pid = name ? (unsigned)strtoul(name + 1, NULL, 10) : 0};
        row = bsearch(&key, file->snapshot->rows, file->snapshot->count, sizeof *file->snapshot->rows, row_compare);
        leaf = "";
    }
    int value = next_fstat(fd, result);
    if (row && !*leaf) { result->st_uid = row->uid; result->st_gid = row->gid; result->st_ino = row->pid; }
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return value;
}
ssize_t readlinkat(int fd, const char *path, char *buffer, size_t capacity) {
    if (!next_readlinkat) return (ssize_t)syscall(SYS_readlinkat, fd, path, buffer, capacity);
    if (inside || !candidate(path)) return next_readlinkat(fd, path, buffer, capacity);
    inside++; pthread_mutex_lock(&mutex);
    char full[PATH_MAX]; ssize_t result;
    if (!resolve(fd, path, full)) result = next_readlinkat(fd, path, buffer, capacity);
    else {
        const char *leaf = ""; struct row *row = lookup(full, &leaf);
        result = row && !strcmp(leaf, "exe") ? -1 : next_readlinkat(fd, path, buffer, capacity);
        if (result < 0 && supported(full)) {
            char *data; size_t length;
            if (!contents(full, 1, &data, &length)) {
                if (length > capacity) length = capacity;
                memcpy(buffer, data, length); livecd_resources_free(data); result = (ssize_t)length;
            }
        }
    }
    int error = errno; pthread_mutex_unlock(&mutex); inside--; errno = error; return result;
}
ssize_t readlink(const char *path, char *buffer, size_t capacity) { return readlinkat(AT_FDCWD, path, buffer, capacity); }

/* Android and 64-bit glibc expose both spellings with identical layouts. */
#if defined(__LP64__)
struct dirent64 *readdir64(DIR *dir) { return (struct dirent64 *)readdir(dir); }
int stat64(const char *path, struct stat64 *result) { return stat(path, (struct stat *)result); }
int lstat64(const char *path, struct stat64 *result) { return lstat(path, (struct stat *)result); }
int fstat64(int fd, struct stat64 *result) { return fstat(fd, (struct stat *)result); }
int fstatat64(int fd, const char *path, struct stat64 *result, int flags) { return fstatat(fd, path, (struct stat *)result, flags); }
#endif
