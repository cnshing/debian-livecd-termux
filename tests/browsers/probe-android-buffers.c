/* Device-open checks and small, unprotected allocations. No settings changes.
 * clang --target=aarch64-linux-android29 probe-android-buffers.c -landroid -o probe-android-buffers
 */
#include <android/hardware_buffer.h>
#include <android/sharedmem.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/dma-buf.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>

/* Linux ION 4.12+ UAPI; allocation uses the FD-returning ABI, not legacy handles. */
struct ion_allocation { uint64_t len; uint32_t heap_id_mask, flags, fd, unused; };
struct ion_heap { char name[32]; uint32_t type, heap_id, reserved[3]; };
struct ion_query { uint32_t cnt, reserved0; uint64_t heaps; uint32_t reserved[2]; };

static void fd_info(const char *kind, int fd) {
    char path[64], link[256] = {0};
    snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
    ssize_t n = readlink(path, link, sizeof(link) - 1);
    if (n >= 0) link[n] = 0;
    struct dma_buf_sync sync = {.flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_RW};
    errno = 0;
    int result = ioctl(fd, DMA_BUF_IOCTL_SYNC, &sync), saved = errno;
    printf("{\"kind\":\"%s\",\"fd\":%d,\"target\":\"%s\",\"dmabuf_sync\":%d,\"errno\":%d}\n",
           kind, fd, link, result, saved);
    if (!result) {
        sync.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_RW;
        ioctl(fd, DMA_BUF_IOCTL_SYNC, &sync);
    }
}

int main(void) {
    char context[256] = {0};
    int c = open("/proc/self/attr/current", O_RDONLY);
    if (c >= 0) { read(c, context, sizeof(context) - 1); close(c); }
    printf("{\"uid\":%d,\"selinux\":\"%s\"}\n", getuid(), context);
    const char *nodes[] = {"/dev/dma_heap/system", "/dev/ion", "/dev/ashmem"};
    for (unsigned i = 0; i < sizeof(nodes) / sizeof(nodes[0]); i++) {
        for (int mode = 0; mode < 2; mode++) {
            errno = 0;
            int fd = open(nodes[i], (mode ? O_RDWR : O_RDONLY) | O_CLOEXEC);
            int saved = errno;
            printf("{\"node\":\"%s\",\"mode\":\"%s\",\"opened\":%s,\"errno\":%d}\n",
                   nodes[i], mode ? "rw" : "r", fd >= 0 ? "true" : "false", saved);
            if (fd >= 0 && i == 1 && mode == 0) {
                struct ion_heap heaps[32] = {0};
                struct ion_query query = {.cnt = 32, .heaps = (uintptr_t)heaps};
                int result = ioctl(fd, _IOWR('I', 8, struct ion_query), &query);
                printf("{\"ion_query\":%d,\"errno\":%d,\"count\":%u}\n", result, result ? errno : 0, query.cnt);
                for (unsigned h = 0; !result && h < query.cnt && h < 32; h++) {
                    printf("{\"heap\":\"%.32s\",\"type\":%u,\"id\":%u}\n", heaps[h].name, heaps[h].type, heaps[h].heap_id);
                    /* Only the unprotected system heap; never probe secure/video heaps. */
                    if (heaps[h].type != 0 || heaps[h].heap_id >= 32) continue;
                    struct ion_allocation alloc = {.len = 1048576, .heap_id_mask = 1u << heaps[h].heap_id};
                    int allocated = ioctl(fd, _IOWR('I', 0, struct ion_allocation), &alloc);
                    printf("{\"ion_allocate\":%d,\"errno\":%d,\"heap_id\":%u}\n", allocated,
                           allocated ? errno : 0, heaps[h].heap_id);
                    if (!allocated) {
                        fd_info("ION", alloc.fd);
                        void *map = mmap(NULL, 1048576, PROT_READ | PROT_WRITE, MAP_SHARED, alloc.fd, 0);
                        printf("{\"ion_mmap\":%s,\"errno\":%d}\n", map != MAP_FAILED ? "true" : "false",
                               map == MAP_FAILED ? errno : 0);
                        if (map != MAP_FAILED) munmap(map, 1048576);
                        close(alloc.fd);
                    }
                }
            }
            if (fd >= 0) close(fd);
        }
    }
    int shared = ASharedMemory_create("native-video-probe", 1048576);
    printf("{\"allocation\":\"ASharedMemory\",\"ok\":%s,\"errno\":%d}\n",
           shared >= 0 ? "true" : "false", shared < 0 ? errno : 0);
    if (shared >= 0) { fd_info("ASharedMemory", shared); close(shared); }
    const uint32_t formats[] = {AHARDWAREBUFFER_FORMAT_BLOB, AHARDWAREBUFFER_FORMAT_Y8Cb8Cr8_420};
    for (unsigned i = 0; i < 2; i++) {
        AHardwareBuffer_Desc desc = {.width = i ? 640 : 1048576, .height = i ? 360 : 1,
            .layers = 1, .format = formats[i],
            .usage = AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN | AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN |
                     (i ? AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE : AHARDWAREBUFFER_USAGE_GPU_DATA_BUFFER)};
        AHardwareBuffer *buffer = NULL;
        int result = AHardwareBuffer_allocate(&desc, &buffer);
        printf("{\"allocation\":\"AHardwareBuffer\",\"format\":%u,\"result\":%d}\n", formats[i], result);
        if (!result && buffer) {
            AHardwareBuffer_describe(buffer, &desc);
            printf("{\"format\":%u,\"stride\":%u}\n", desc.format, desc.stride);
            /* Inspect duplicated transport FDs, without relying on a private handle ABI.
             * This does NOT establish a portable raw NV12 layout for these FDs. */
            int sockets[2];
            if (!socketpair(AF_UNIX, SOCK_STREAM, 0, sockets)) {
                int sent = AHardwareBuffer_sendHandleToUnixSocket(buffer, sockets[0]);
                if (!sent) {
                    char payload[4096], control[CMSG_SPACE(64 * sizeof(int))];
                    struct iovec iov = {.iov_base = payload, .iov_len = sizeof(payload)};
                    struct msghdr message = {.msg_iov = &iov, .msg_iovlen = 1,
                        .msg_control = control, .msg_controllen = sizeof(control)};
                    if (recvmsg(sockets[1], &message, MSG_DONTWAIT) > 0) {
                        for (struct cmsghdr *item = CMSG_FIRSTHDR(&message); item;
                             item = CMSG_NXTHDR(&message, item)) {
                            if (item->cmsg_level != SOL_SOCKET || item->cmsg_type != SCM_RIGHTS) continue;
                            int *fds = (int *)CMSG_DATA(item);
                            size_t count = (item->cmsg_len - CMSG_LEN(0)) / sizeof(int);
                            for (size_t j = 0; j < count; j++) { fd_info("AHardwareBuffer", fds[j]); close(fds[j]); }
                        }
                    }
                }
                close(sockets[0]); close(sockets[1]);
            }
            void *address = NULL;
            int locked = AHardwareBuffer_lock(buffer, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN |
                AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN, -1, NULL, &address);
            printf("{\"format\":%u,\"cpu_lock\":%d}\n", desc.format, locked);
            if (!locked) AHardwareBuffer_unlock(buffer, NULL);
            AHardwareBuffer_release(buffer);
        }
    }
    return 0;
}
