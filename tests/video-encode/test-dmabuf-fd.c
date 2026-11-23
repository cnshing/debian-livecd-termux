/* SPDX-License-Identifier: GPL-3.0-or-later
 * cc -D_GNU_SOURCE -I /path/to/patched/common test-dmabuf-fd.c -o test-fd
 * Tests the actual shared helper used by both transport endpoints. */
#include "tva_fd.h"
#include <assert.h>
#include <dirent.h>
#include <stdio.h>
#include <sys/stat.h>

static int fd_count(void)
{
    DIR *dir=opendir("/proc/self/fd");
    assert(dir);
    int count=0;
    while (readdir(dir)) count++;
    closedir(dir);
    return count;
}
static void malformed(int count, unsigned char marker)
{
    int sockets[2], source=open("/dev/null", O_RDONLY | O_CLOEXEC);
    assert(source >= 0 && socketpair(AF_UNIX, SOCK_STREAM, 0, sockets)==0);
    int before=fd_count();
    struct iovec io={.iov_base=&marker, .iov_len=1};
    union {struct cmsghdr align; unsigned char bytes[CMSG_SPACE(32*sizeof(int))];} control={0};
    struct msghdr message={.msg_iov=&io, .msg_iovlen=1};
    if (count) {
        message.msg_control=control.bytes; message.msg_controllen=CMSG_SPACE(count*sizeof(int));
        struct cmsghdr *c=CMSG_FIRSTHDR(&message);
        c->cmsg_level=SOL_SOCKET; c->cmsg_type=SCM_RIGHTS; c->cmsg_len=CMSG_LEN(count*sizeof(int));
        for (int i=0; i<count; i++) memcpy((char *)CMSG_DATA(c)+i*sizeof(int), &source, sizeof(int));
    }
    assert(sendmsg(sockets[0], &message, MSG_NOSIGNAL)==1);
    int received=-1;
    assert(tva_transfer_fd(sockets[1], 0, &received)==-1);
    assert(received==-1 && fd_count()==before);
    close(source); close(sockets[0]); close(sockets[1]);
}
int main(void)
{
    int sockets[2], source=open("/dev/null", O_RDONLY | O_CLOEXEC), received=-1;
    assert(source >= 0 && socketpair(AF_UNIX, SOCK_STREAM, 0, sockets)==0);
    assert(!tva_transfer_fd(sockets[0], 1, &source));
    assert(!tva_transfer_fd(sockets[1], 0, &received));
    assert(received>=0 && (fcntl(received, F_GETFD)&FD_CLOEXEC));
    struct stat a,b;
    assert(!fstat(source,&a) && !fstat(received,&b));
    assert(a.st_dev==b.st_dev && a.st_ino==b.st_ino);
    close(received); close(source); close(sockets[0]); close(sockets[1]);
    malformed(0, 'F'); malformed(1, 'X'); malformed(2, 'F'); malformed(32, 'F');
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets)==0);
    close(sockets[0]); received=-1;
    assert(tva_transfer_fd(sockets[1], 0, &received)==-1 && received==-1);
    close(sockets[1]);
    puts("PASS fd identity, CLOEXEC, missing/extra/truncated rights, marker, EOF, no leaks");
}
