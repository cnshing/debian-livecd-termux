// Uses only the DMA-BUF heap API: open, stat, DMA_HEAP_IOCTL_ALLOC, mmap.
// Usage: heap-client <heap name> <bytes>. Prints "ok" or the failing step.
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
struct dma_heap_allocation_data { uint64_t len; uint32_t fd, fd_flags; uint64_t heap_flags; };
#define DMA_HEAP_IOCTL_ALLOC _IOWR('H', 0x0, struct dma_heap_allocation_data)
int main(int argc, char **argv) {
    char path[128];
    snprintf(path, sizeof path, "%s/%s", getenv("HEAP_DIR") ? getenv("HEAP_DIR") : "/dev/dma_heap", argv[1]);
    size_t len = strtoull(argv[2], 0, 0);
    struct stat st;
    if (stat(path, &st) || !S_ISCHR(st.st_mode)) { printf("stat %s\n", strerror(errno)); return 1; }
    int heap = open(path, O_RDONLY | O_CLOEXEC);
    if (heap < 0) { printf("open %s\n", strerror(errno)); return 1; }
    struct dma_heap_allocation_data d = {.len = len, .fd_flags = O_RDWR | O_CLOEXEC};
    if (ioctl(heap, DMA_HEAP_IOCTL_ALLOC, &d)) { printf("alloc %s\n", strerror(errno)); return 1; }
    if (!(fcntl(d.fd, F_GETFD) & FD_CLOEXEC)) { printf("cloexec\n"); return 1; }
    struct dma_heap_allocation_data bad = {.len = len, .heap_flags = 1};
    if (!ioctl(heap, DMA_HEAP_IOCTL_ALLOC, &bad) || errno != EINVAL) { printf("badflags\n"); return 1; }
    if (!ioctl(heap, 0x1234, 0) || errno != ENOTTY) { printf("otherioctl\n"); return 1; }
    unsigned char *p = mmap(0, len, PROT_READ | PROT_WRITE, MAP_SHARED, d.fd, 0);
    if (p == MAP_FAILED) { printf("mmap %s\n", strerror(errno)); return 1; }
    memset(p, 0x5a, len);
    if (p[len - 1] != 0x5a) { printf("pattern\n"); return 1; }
    // Hand the buffer to a second process over a Unix socket; it checks the pattern.
    int sv[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv)) { printf("socketpair\n"); return 1; }
    pid_t child = fork();
    if (!child) {
        char b; struct iovec io = {&b, 1}; char ctl[CMSG_SPACE(sizeof(int))];
        struct msghdr m = {.msg_iov = &io, .msg_iovlen = 1, .msg_control = ctl, .msg_controllen = sizeof ctl};
        if (recvmsg(sv[1], &m, 0) != 1) _exit(2);
        int got; memcpy(&got, CMSG_DATA(CMSG_FIRSTHDR(&m)), sizeof got);
        unsigned char *q = mmap(0, len, PROT_READ, MAP_SHARED, got, 0);
        _exit(q != MAP_FAILED && q[0] == 0x5a && q[len - 1] == 0x5a ? 0 : 3);
    }
    {
        char b = 0; struct iovec io = {&b, 1}; char ctl[CMSG_SPACE(sizeof(int))] = {0};
        struct msghdr m = {.msg_iov = &io, .msg_iovlen = 1, .msg_control = ctl, .msg_controllen = sizeof ctl};
        struct cmsghdr *c = CMSG_FIRSTHDR(&m);
        c->cmsg_level = SOL_SOCKET; c->cmsg_type = SCM_RIGHTS; c->cmsg_len = CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(c), &d.fd, sizeof(int));
        int st;
        if (sendmsg(sv[0], &m, 0) != 1 || waitpid(child, &st, 0) != child || !WIFEXITED(st) || WEXITSTATUS(st)) {
            printf("second process\n"); return 1;
        }
    }
    int other = dup(heap);
    if (ioctl(other, DMA_HEAP_IOCTL_ALLOC, &(struct dma_heap_allocation_data){.len = 4096})) { printf("dup\n"); return 1; }
    close(other); close(heap);
    printf("ok\n");
    return 0;
}
