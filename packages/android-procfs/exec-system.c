/* SPDX-License-Identifier: MIT
 * Termux's exec shim clears LD_PRELOAD when executing Android system commands.
 * Preserve the explicitly requested compatibility layer for this invocation.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <unistd.h>
extern char **environ;
int main(int argc, char **argv) {
    if (argc < 2 || argv[1][0] != '/') return 2;
    unsetenv("LD_LIBRARY_PATH");
    syscall(SYS_execve, argv[1], argv + 1, environ);
    perror(argv[1]);
    return errno == ENOENT ? 127 : 126;
}
