// Lists the ION heaps and tries system-heap allocations (cached and uncached)
// of 4 KiB, 1 MiB and 64 MiB, each with mmap and a DMA_BUF_IOCTL_SYNC round
// trip. Run without any preload. Usage: ion-probe [/dev/ion]
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
struct ion_allocation_data { uint64_t len; uint32_t heap_id_mask, flags, fd, unused; };
struct ion_heap_data { char name[32]; uint32_t type, heap_id, r0, r1, r2; };
struct ion_heap_query { uint32_t cnt, r0; uint64_t heaps; uint32_t r1, r2; };
struct dma_buf_sync { uint64_t flags; };
#define ION_IOC_ALLOC _IOWR('I', 0, struct ion_allocation_data)
#define ION_IOC_HEAP_QUERY _IOWR('I', 8, struct ion_heap_query)
#define DMA_BUF_IOCTL_SYNC _IOW('b', 0, struct dma_buf_sync)
int main(int argc, char **argv) {
    int ion = open(argc > 1 ? argv[1] : "/dev/ion", O_RDONLY | O_CLOEXEC);
    if (ion < 0) { perror("open"); return 1; }
    struct ion_heap_data h[32] = {0};
    struct ion_heap_query q = {.cnt = 32, .heaps = (uintptr_t)h};
    if (ioctl(ion, ION_IOC_HEAP_QUERY, &q)) { perror("HEAP_QUERY"); return 1; }
    int sys = -1;
    for (unsigned i = 0; i < q.cnt; i++) {
        printf("heap id=%u type=%u name=%s\n", h[i].heap_id, h[i].type, h[i].name);
        if (h[i].type == 0 && sys < 0) sys = h[i].heap_id;
    }
    if (sys < 0) { printf("no system heap\n"); return 1; }
    size_t sizes[] = {4096, 1 << 20, 64 << 20};
    int bad = 0;
    for (int c = 1; c >= 0; c--) for (int s = 0; s < 3; s++) {
        struct ion_allocation_data a = {.len = sizes[s], .heap_id_mask = 1u << sys, .flags = c};
        printf("alloc %zu %s: ", sizes[s], c ? "cached" : "uncached");
        if (ioctl(ion, ION_IOC_ALLOC, &a)) { printf("FAIL %s\n", strerror(errno)); bad = 1; continue; }
        unsigned char *p = mmap(0, sizes[s], PROT_READ | PROT_WRITE, MAP_SHARED, a.fd, 0);
        if (p == MAP_FAILED) { printf("mmap FAIL %s\n", strerror(errno)); bad = 1; close(a.fd); continue; }
        struct dma_buf_sync st = {.flags = 3 | 0}, en = {.flags = 3 | 4}; // RW start / end
        int r1 = ioctl(a.fd, DMA_BUF_IOCTL_SYNC, &st);
        memset(p, 0xa5, sizes[s]);
        int r2 = ioctl(a.fd, DMA_BUF_IOCTL_SYNC, &en);
        printf("ok mmap sync=%s\n", !r1 && !r2 ? "ok" : strerror(errno));
        bad |= r1 || r2 || p[sizes[s] - 1] != 0xa5;
        munmap(p, sizes[s]); close(a.fd);
    }
    return bad;
}
