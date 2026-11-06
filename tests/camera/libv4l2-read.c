// Stream from /dev/videoN through libv4l2, which calls syscall() directly
// instead of open, ioctl and mmap. Build and run in native Termux:
//   clang -O2 -Wall -o libv4l2-read libv4l2-read.c -lv4l2
//   ./libv4l2-read /dev/video1 150 [expected-card]
// With camera-node --stamp, reports exposure-start-to-application latency.
#include <errno.h>
#include <fcntl.h>
#include <libv4l2.h>
#include <limits.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>

static int xioctl(int fd, unsigned long req, void *arg, const char *name) {
    if (v4l2_ioctl(fd, req, arg) == 0) return 0;
    printf("FAIL %s: %s\n", name, strerror(errno));
    return -1;
}

static int cmp(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return x < y ? -1 : x > y;
}

int main(int argc, char **argv) {
    const char *dev = argc > 1 ? argv[1] : "/dev/video0";
    int frames = argc > 2 ? atoi(argv[2]) : 150;
    const char *want = argc > 3 ? argv[3] : NULL;
    char resolved[PATH_MAX];
    printf("realpath: %s\n", realpath(dev, resolved) ? resolved : strerror(errno));

    int fd = v4l2_open(dev, O_RDWR);
    if (fd < 0) {
        printf("FAIL v4l2_open: %s\n", strerror(errno));
        return 1;
    }
    struct v4l2_capability cap = {0};
    if (xioctl(fd, VIDIOC_QUERYCAP, &cap, "QUERYCAP")) return 1;
    printf("card %s, driver %s\n", cap.card, cap.driver);

    printf("formats:");
    for (struct v4l2_fmtdesc d = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE}; v4l2_ioctl(fd, VIDIOC_ENUM_FMT, &d) == 0;
         d.index++)
        printf(" %.4s%s", (char *)&d.pixelformat, d.flags & V4L2_FMT_FLAG_EMULATED ? "(emulated)" : "");
    printf("\n");

    struct v4l2_format fmt = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE};
    fmt.fmt.pix.width = 1280, fmt.fmt.pix.height = 720;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV, fmt.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(fd, VIDIOC_S_FMT, &fmt, "S_FMT")) return 1;
    printf("set %.4s %ux%u, size %u\n", (char *)&fmt.fmt.pix.pixelformat, fmt.fmt.pix.width, fmt.fmt.pix.height,
           fmt.fmt.pix.sizeimage);

    struct v4l2_requestbuffers req = {.count = 4, .type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP};
    if (xioctl(fd, VIDIOC_REQBUFS, &req, "REQBUFS")) return 1;
    void *maps[8];
    size_t lens[8];
    for (unsigned i = 0; i < req.count && i < 8; i++) {
        struct v4l2_buffer b = {.index = i, .type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP};
        if (xioctl(fd, VIDIOC_QUERYBUF, &b, "QUERYBUF")) return 1;
        maps[i] = v4l2_mmap(NULL, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, b.m.offset);
        lens[i] = b.length;
        if (maps[i] == MAP_FAILED) {
            printf("FAIL v4l2_mmap: %s\n", strerror(errno));
            return 1;
        }
        if (xioctl(fd, VIDIOC_QBUF, &b, "QBUF")) return 1;
    }
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd, VIDIOC_STREAMON, &type, "STREAMON")) return 1;

    double *lat = calloc(frames, sizeof *lat);
    int got = 0, nlat = 0;
    struct timespec t0, t1, now;
    while (got < frames) {
        struct pollfd p = {.fd = fd, .events = POLLIN};
        if (poll(&p, 1, 5000) <= 0) {
            printf("FAIL timed out waiting for a frame\n");
            break;
        }
        struct v4l2_buffer b = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP};
        if (xioctl(fd, VIDIOC_DQBUF, &b, "DQBUF")) break;
        clock_gettime(CLOCK_BOOTTIME, &now);
        if (got == 0) t0 = now;
        t1 = now;
        int64_t stamp;
        memcpy(&stamp, maps[b.index], sizeof stamp);
        int64_t d = now.tv_sec * 1000000000LL + now.tv_nsec - stamp;
        if (d > 0 && d < 1000000000LL) lat[nlat++] = d / 1e6;
        if (xioctl(fd, VIDIOC_QBUF, &b, "QBUF")) break;
        got++;
    }
    v4l2_ioctl(fd, VIDIOC_STREAMOFF, &type);
    for (unsigned i = 0; i < req.count && i < 8; i++) v4l2_munmap(maps[i], lens[i]);
    v4l2_close(fd);

    double secs = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    printf("frames %d, %.1f fps\n", got, got > 1 ? (got - 1) / secs : 0);
    if (nlat) {
        qsort(lat, nlat, sizeof *lat, cmp);
        printf("exposure start to application: median %.1f ms, min %.1f, max %.1f\n", lat[nlat / 2], lat[0],
               lat[nlat - 1]);
    }
    int ok = got == frames && (!want || !strcmp((char *)cap.card, want));
    printf("%s libv4l2 stream\n", ok ? "PASS" : "FAIL");
    return ok ? 0 : 1;
}
