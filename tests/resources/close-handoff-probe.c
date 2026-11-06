/* SPDX-License-Identifier: MIT
 * Closes a file whose close, in a library loaded after the preload, waits for another thread that
 * closes a file too, as pw-v4l2's close does while it tears down its PipeWire stream. Under a preload
 * that holds its lock across the next close, that thread waits for the lock and close never returns.
 * Build the library with -DHANDOFF -shared -fPIC and the program without, then run
 * LD_PRELOAD=libandroid-procfs.so:./close-handoff.so with a timeout: it prints "ok" or never returns.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <unistd.h>

enum { DEVICE = 100, OTHER = 101 };

#ifdef HANDOFF
static void *close_other(void *unused) {
    (void)unused;
    // As from another library: a call within this one would bind to its own close.
    int (*first_close)(int) = (int (*)(int))dlsym(RTLD_DEFAULT, "close");
    first_close(OTHER);
    return NULL;
}

int close(int fd) {
    static int (*next_close)(int);
    if (!next_close) next_close = (int (*)(int))dlsym(RTLD_NEXT, "close");
    if (fd == DEVICE) {
        pthread_t thread;
        pthread_create(&thread, NULL, close_other, NULL);
        pthread_join(thread, NULL);
    }
    return next_close(fd);
}
#else
int main(void) {
    int fds[2];
    if (pipe(fds) || dup2(fds[0], DEVICE) < 0 || dup2(fds[1], OTHER) < 0) return 2;
    close(fds[0]);
    close(fds[1]);
    close(DEVICE);
    printf("ok\n");
    return 0;
}
#endif
