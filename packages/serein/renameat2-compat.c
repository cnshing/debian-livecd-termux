/* Android's libc exports renameat2 only from API 30. Keep the kernel operation
 * available at Termux's API 24 baseline, including RENAME_NOREPLACE semantics.
 */
#include <sys/syscall.h>
#include <unistd.h>

int renameat2(int from_fd, const char *from, int to_fd, const char *to,
              unsigned int flags) {
    return (int)syscall(SYS_renameat2, from_fd, from, to_fd, to, flags);
}
