/* SPDX-License-Identifier: MIT
 * Forks while signals whose handler writes keep arriving, as GLib's child watch does when VTE respawns a
 * shell. Under a preload that locks inside write, a signal during fork used to wait on its own thread.
 * Run with LD_PRELOAD naming liblivecd-proc.so and a timeout: it prints "ok" or never returns.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int wakeup[2];
static pthread_t main_thread;
static volatile int done;

static void handler(int signum) {
    (void)signum;
    char byte = 0;
    // GLib's unix signal handler wakes its main loop the same way.
    if (write(wakeup[1], &byte, 1) < 0) {}
}

static void *signaller(void *unused) {
    (void)unused;
    struct timespec pause = {0, 20000};
    while (!done) {
        pthread_kill(main_thread, SIGUSR1);
        nanosleep(&pause, NULL);
    }
    return NULL;
}

int main(int argc, char **argv) {
    int forks = argc > 1 ? atoi(argv[1]) : 2000;
    if (pipe(wakeup)) return 2;
    // Never block the writer: the probe only cares whether write returns.
    for (int i = 0; i < 2; i++) { int flags = fcntl(wakeup[i], F_GETFL); fcntl(wakeup[i], F_SETFL, flags | O_NONBLOCK); }
    struct sigaction action = {.sa_handler = handler, .sa_flags = SA_RESTART};
    sigaction(SIGUSR1, &action, NULL);
    main_thread = pthread_self();
    pthread_t thread;
    pthread_create(&thread, NULL, signaller, NULL);
    char drain[4096];
    for (int i = 0; i < forks; i++) {
        pid_t child = fork();
        if (child == 0) _exit(0);
        if (child < 0) return 3;
        while (waitpid(child, NULL, 0) < 0) {}
        while (read(wakeup[0], drain, sizeof drain) > 0) {}
    }
    done = 1;
    pthread_join(thread, NULL);
    printf("ok %d forks\n", forks);
    return 0;
}
