// Loads libandroid-dma-heap.so with dlopen, as the VA bridge does, instead of preloading it.
// Usage: scoped-client <library> <heap name> <bytes>. Prints "ok" or the failing step.
// Checks that livecd_dma_heap_alloc() returns a mappable FD while the process's own open()
// of the heap node still fails: the library must not interpose on anything.
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    int (*alloc)(const char *, uint64_t, uint32_t) = lib ? (void *)dlsym(lib, "livecd_dma_heap_alloc") : NULL;
    if (!alloc) { printf("dlopen %s\n", dlerror()); return 1; }
    size_t len = strtoull(argv[3], 0, 0);
    int fd = alloc(argv[2], len, O_RDWR | O_CLOEXEC);
    if (fd < 0) { printf("alloc %s\n", strerror(errno)); return 1; }
    if (!(fcntl(fd, F_GETFD) & FD_CLOEXEC)) { printf("cloexec\n"); return 1; }
    unsigned char *p = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) { printf("mmap %s\n", strerror(errno)); return 1; }
    memset(p, 0x5a, len);
    if (p[len - 1] != 0x5a) { printf("pattern\n"); return 1; }
    char path[256];
    snprintf(path, sizeof path, "%s/%s", getenv("HEAP_DIR"), argv[2]);
    int node = open(path, O_RDONLY);
    if (node >= 0 || errno != ENOENT) { printf("interposed\n"); return 1; }
    printf("ok\n");
    return 0;
}
