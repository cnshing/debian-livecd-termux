/* Route glibc's fortified entry points through Bionilux's ordinary hooks.
 * Debian enables _FORTIFY_SOURCE; upstream portable builds need only readlink.
 * Preserve glibc's bounds check before invoking the interposed function.
 */
#define _GNU_SOURCE
#include <stddef.h>
#include <sys/types.h>
#include <unistd.h>

extern void __chk_fail(void) __attribute__((noreturn));

ssize_t __readlink_chk(const char *path, char *buffer, size_t size, size_t capacity)
{
    if (size > capacity)
        __chk_fail();
    return readlink(path, buffer, size);
}

ssize_t __readlinkat_chk(int dirfd, const char *path, char *buffer,
                       size_t size, size_t capacity)
{
    if (size > capacity)
        __chk_fail();
    return readlinkat(dirfd, path, buffer, size);
}
