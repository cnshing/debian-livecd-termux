/* SPDX-License-Identifier: MIT
 * Keep V8's advisory shared-memory hints usable on 39-bit Adreno Android.
 *
 * Linux V8 assumes a larger address space than this Android kernel provides.
 * Its partial sandbox reserves an accessible prefix, but shared ArrayBuffers
 * must live AFTER that reservation. Random hints in the remaining logical 1 TiB
 * sandbox often exceed the kernel's 512 GiB limit. The kernel then puts the map
 * below the reservation; V8 unmaps it and exhausts its ten attempts.
 *
 * Remember the large no-access reservation and fold only out-of-range shared
 * memfd hints into its accessible tail. These remain advisory mappings: never
 * replace existing memory, change permissions or bypass V8's range checks.
 * Loaded only by the Chromium-family launchers on KGSL, with an opt-out.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

static uintptr_t reservation_end;
static size_t page_size = 4096;
static int enabled;

__attribute__((constructor)) static void initialize(void) {
    int page = getpagesize();
    if (page >= 4096 && page <= 65536 && !(page & (page - 1))) page_size = (size_t)page;
    enabled = access("/dev/kgsl-3d0", F_OK) == 0 && access("/dev/mali0", F_OK) != 0;
    if (enabled) {
        // Newer Adreno kernels may expose more virtual address bits. Keep
        // their normal mapping behavior: probe with an advisory, temporary
        // page instead of inferring the address limit from the GPU alone.
        const uintptr_t limit = UINT64_C(1) << 39;
        void *probe = (void *)syscall(SYS_mmap, (void *)limit, page_size, PROT_NONE,
                                     MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
        enabled = probe != MAP_FAILED && (uintptr_t)probe < limit;
        if (probe != MAP_FAILED) syscall(SYS_munmap, probe, page_size);
    }
#ifdef WEBGPU_MAP_TEST
    enabled = 1;
#endif
}

static int shared_transfer_fd(int fd) {
    if (fd < 0) return 0;
    char path[64] = "/proc/self/fd/", digits[16], target[96];
    size_t length = sizeof("/proc/self/fd/") - 1, n = 0;
    unsigned number = (unsigned)fd;
    do { digits[n++] = (char)('0' + number % 10); number /= 10; } while (number);
    while (n) path[length++] = digits[--n];
    path[length] = '\0';
    long count = syscall(SYS_readlinkat, AT_FDCWD, path, target, sizeof(target));
    static const char name[] = "/memfd:shared-memory-region (deleted)";
    if (count != sizeof(name) - 1) return 0;
    for (size_t i = 0; i < sizeof(name) - 1; i++) if (target[i] != name[i]) return 0;
    return 1;
}

// The accessible tail can be fragmented by the loader, WebGL and other heaps.
// If a hint lands in an occupied area, the kernel may ignore it and return an
// address below the sandbox. Find a real hole before retrying, without malloc,
// stdio, or fixed mappings inside this allocation hook.
static uintptr_t gap_hint(uintptr_t start, uintptr_t end, size_t size, uintptr_t entropy) {
    if (end <= start || size > end - start) return 0;
    uintptr_t slots = (end - start - size) / page_size + 1;
    return start + (entropy % slots) * page_size;
}

static uintptr_t free_hint(uintptr_t minimum, uintptr_t limit, size_t size, uintptr_t entropy) {
    int fd = (int)syscall(SYS_openat, AT_FDCWD, "/proc/self/maps", O_RDONLY | O_CLOEXEC, 0);
    if (fd < 0) return 0;
    char buffer[4096];
    uintptr_t cursor = minimum, start = 0, end = 0, found = 0;
    int field = 0;
    long count;
    while (!found && (count = syscall(SYS_read, fd, buffer, sizeof(buffer))) > 0) {
        for (long i = 0; i < count && !found; i++) {
            unsigned char c = (unsigned char)buffer[i];
            if (c == '\n') {
                if (start >= limit) { found = gap_hint(cursor, limit, size, entropy); break; }
                if (start > cursor) found = gap_hint(cursor, start, size, entropy);
                if (end > cursor) cursor = end;
                start = end = 0; field = 0;
            } else if (field < 2) {
                int digit = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;
                if (digit >= 0) {
                    if (!field) start = (start << 4) | (unsigned)digit;
                    else end = (end << 4) | (unsigned)digit;
                } else if (c == '-' && !field) field = 1;
                else field = 2;
            }
        }
    }
    syscall(SYS_close, fd);
    return found ? found : gap_hint(cursor, limit, size, entropy);
}

void *mmap(void *hint, size_t size, int protection, int flags, int fd, off_t offset) {
    const uintptr_t limit = UINT64_C(1) << 39;
    uintptr_t end = __atomic_load_n(&reservation_end, __ATOMIC_RELAXED);
    uintptr_t requested = (uintptr_t)hint;
    // Bionic does not expose environ to preload constructors yet. Read this
    // at call time, once the browser has entered libc initialization/main.
    const char *option = enabled ? getenv("LIVECD_WEBGPU_MAP") : NULL;
    int active = option && option[0] == '1' && option[1] == '\0';
    int adapt = active && end && requested >= end && (flags & MAP_SHARED) &&
        !(flags & (MAP_FIXED | 0x100000 /* MAP_FIXED_NOREPLACE */)) &&
        end < limit && size < limit - end && shared_transfer_fd(fd);
    if (adapt && requested >= limit) {
        uintptr_t available = limit - end - size;
        uintptr_t revised = end + ((requested - end) % available);
        hint = (void *)(revised & ~(uintptr_t)(page_size - 1));
    }
    void *result = (void *)syscall(SYS_mmap, hint, size, protection, flags, fd, offset);
    if (adapt) {
        for (int attempt = 0; attempt < 3 && result != MAP_FAILED &&
             ((uintptr_t)result < end || (uintptr_t)result > limit - size); attempt++) {
            uintptr_t next = free_hint(end, limit, size, requested >> 12);
            if (!next) break;
            // This is our just-created mapping, not a pre-existing reservation.
            syscall(SYS_munmap, result, size);
            result = (void *)syscall(SYS_mmap, (void *)next, size, protection, flags, fd, offset);
        }
    }
    if (enabled && result != MAP_FAILED && protection == PROT_NONE &&
        (flags & MAP_NORESERVE) && (flags & MAP_ANONYMOUS) && (flags & MAP_PRIVATE) &&
        !(flags & (MAP_FIXED | 0x100000)) && fd == -1 && offset == 0 &&
        size >= (UINT64_C(12) << 30) - page_size &&
        (uintptr_t)result < limit && size < limit - (uintptr_t)result) {
        // V8 requests a power-of-two prefix (8 GiB minimum), plus the space
        // needed to align it to 4 GiB. Avoid mistaking other large heaps for it.
        uintptr_t prefix = size + page_size - (UINT64_C(4) << 30);
        if (!(prefix & (prefix - 1)))
            __atomic_store_n(&reservation_end, (uintptr_t)result + size, __ATOMIC_RELAXED);
    }
    return result;
}

void *mmap64(void *hint, size_t size, int protection, int flags, int fd, off64_t offset) {
    return mmap(hint, size, protection, flags, fd, (off_t)offset);
}
