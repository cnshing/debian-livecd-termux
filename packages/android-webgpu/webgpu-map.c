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
static int enabled;

__attribute__((constructor)) static void initialize(void) {
    const char *option = getenv("LIVECD_WEBGPU_MAP");
    enabled = option && option[0] == '1' && option[1] == '\0' &&
              access("/dev/kgsl-3d0", F_OK) == 0 && access("/dev/mali0", F_OK) != 0;
#ifdef WEBGPU_MAP_TEST
    enabled = option && option[0] == '1' && option[1] == '\0';
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

void *mmap(void *hint, size_t size, int protection, int flags, int fd, off_t offset) {
    const uintptr_t limit = UINT64_C(1) << 39;
    uintptr_t end = __atomic_load_n(&reservation_end, __ATOMIC_RELAXED);
    uintptr_t requested = (uintptr_t)hint;
    if (enabled && end && requested >= limit && (flags & MAP_SHARED) &&
        !(flags & (MAP_FIXED | 0x100000 /* MAP_FIXED_NOREPLACE */)) &&
        end < limit && size < limit - end && shared_transfer_fd(fd)) {
        uintptr_t available = limit - end - size;
        uintptr_t revised = end + ((requested - end) % available);
        hint = (void *)(revised & ~UINT64_C(4095));
    }
    void *result = (void *)syscall(SYS_mmap, hint, size, protection, flags, fd, offset);
    if (enabled && result != MAP_FAILED && protection == PROT_NONE &&
        (flags & MAP_NORESERVE) && (flags & MAP_ANONYMOUS) && (flags & MAP_PRIVATE) &&
        !(flags & (MAP_FIXED | 0x100000)) && size >= (UINT64_C(64) << 30) &&
        (uintptr_t)result < limit && size < limit - (uintptr_t)result) {
        __atomic_store_n(&reservation_end, (uintptr_t)result + size, __ATOMIC_RELAXED);
    }
    return result;
}

void *mmap64(void *hint, size_t size, int protection, int flags, int fd, off64_t offset) {
    return mmap(hint, size, protection, flags, fd, (off_t)offset);
}
