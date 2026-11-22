/* glibc NSS client for Android's existing per-UID DNS service.
 * Wire format: AOSP DnsResolver/DnsProxyListener.cpp (getaddrinfo/gethostbyaddr).
 * No daemon, resolver-file synchronization, or public-DNS fallback is needed.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <nss.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#ifndef ANDROID_DNS_SOCKET
#define ANDROID_DNS_SOCKET "/dev/socket/dnsproxyd"
#endif
#define MAX_ADDRS 128
#define MAX_NAME 1025
struct address { int family; uint32_t scope; unsigned char bytes[16]; };
struct answer { char name[MAX_NAME]; size_t count; struct address addr[MAX_ADDRS]; };

static int read_all(int fd, void *data, size_t len) {
    char *p = data;
    while (len) {
        ssize_t n = recv(fd, p, len, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { if (!n) errno = EPROTO; return -1; }
        p += n; len -= (size_t)n;
    }
    return 0;
}

static int read_u32(int fd, uint32_t *out) {
    uint32_t value;
    if (read_all(fd, &value, sizeof value)) return -1;
    *out = ntohl(value);
    return 0;
}

static int read_string(int fd, char *out, size_t size) {
    uint32_t len;
    if (read_u32(fd, &len)) return -1;
    if (len > size) { errno = EOVERFLOW; return -1; }
    if (!len) { out[0] = 0; return 0; }
    if (read_all(fd, out, len)) return -1;
    if (out[len - 1] || memchr(out, 0, len - 1)) { errno = EPROTO; return -1; }
    return 0;
}

static enum nss_status failure(int *err, int *herr) {
    *err = errno ? errno : EIO;
    *herr = TRY_AGAIN;
    return NSS_STATUS_TRYAGAIN;
}

/* Returns the connected fd, or a negative fd and the NSS result. */
static int request(const char *command, enum nss_status *status, int *err, int *herr) {
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) { *status = failure(err, herr); return -1; }
    struct timeval timeout = { .tv_sec = 15 };
    struct sockaddr_un sa = { .sun_family = AF_UNIX, .sun_path = ANDROID_DNS_SOCKET };
    if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout) ||
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout) ||
        connect(fd, (struct sockaddr *)&sa, sizeof sa)) goto failed;
    size_t len = strlen(command) + 1;
    const char *p = command;
    while (len) {
        ssize_t n = send(fd, p, len, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) goto failed;
        p += n; len -= (size_t)n;
    }
    char code[4];
    if (read_all(fd, code, sizeof code)) goto failed;
    if (memcmp(code, "222\0", 4)) {
        /* Android's EAI values differ from glibc's. Only definitive negative
         * answers become NOTFOUND; timeouts/service failures remain retryable. */
        int32_t eai;
        uint32_t payload_size;
        if (memcmp(code, "401\0", 4) || read_u32(fd, &payload_size)) goto failed;
        /* SocketClient::sendBinaryMsg prefixes its native-endian EAI payload
         * with a network-endian byte count. */
        if (payload_size != sizeof eai) { errno = EPROTO; goto failed; }
        if (read_all(fd, &eai, sizeof eai)) goto failed;
        if (eai == 7 || eai == 8) {
            close(fd); *err = 0; *herr = HOST_NOT_FOUND;
            *status = NSS_STATUS_NOTFOUND; return -1;
        }
        errno = eai == 6 ? ENOMEM : EAGAIN;
        goto failed;
    }
    return fd;
failed:
    { int saved = errno; close(fd); errno = saved; }
    *status = failure(err, herr);
    return -1;
}

static enum nss_status lookup(const char *name, int family, struct answer *out,
                             int *err, int *herr) {
    memset(out, 0, sizeof *out);
    size_t len = strnlen(name, MAX_NAME);
    if (!len || len == MAX_NAME) goto invalid;
    for (size_t i = 0; i < len; ++i)
        if ((unsigned char)name[i] <= ' ' || strchr("\"\\^", name[i])) goto invalid;
    memcpy(out->name, name, len + 1);
    char command[MAX_NAME + 80];
    /* Android AI_CANONNAME=2; netId=0 asks for the calling UID's default
     * network, including its VPN and Private DNS policy, on every lookup. */
    snprintf(command, sizeof command, "getaddrinfo %s ^ 2 %d 1 6 0", name, family);
    enum nss_status status;
    int fd = request(command, &status, err, herr);
    if (fd < 0) return status;
    for (;;) {
        uint32_t present, flags, af, socktype, protocol, addrlen;
        struct sockaddr_storage sa;
        char canonical[MAX_NAME];
        if (read_u32(fd, &present)) goto failed;
        if (!present) break;
        if (present != 1) { errno = EPROTO; goto failed; }
        if (read_u32(fd, &flags) || read_u32(fd, &af) ||
            read_u32(fd, &socktype) || read_u32(fd, &protocol) || read_u32(fd, &addrlen)) goto failed;
        if (addrlen > sizeof sa) { errno = EOVERFLOW; goto failed; }
        memset(&sa, 0, sizeof sa);
        if (read_all(fd, &sa, addrlen) || read_string(fd, canonical, sizeof canonical)) goto failed;
        if (out->count == MAX_ADDRS) { errno = EOVERFLOW; goto failed; }
        struct address *a = &out->addr[out->count];
        if (af == AF_INET && addrlen == sizeof(struct sockaddr_in) && sa.ss_family == AF_INET) {
            memcpy(a->bytes, &((struct sockaddr_in *)&sa)->sin_addr, 4);
        } else if (af == AF_INET6 && addrlen == sizeof(struct sockaddr_in6) && sa.ss_family == AF_INET6) {
            memcpy(a->bytes, &((struct sockaddr_in6 *)&sa)->sin6_addr, 16);
            a->scope = ((struct sockaddr_in6 *)&sa)->sin6_scope_id;
        } else { errno = EPROTO; goto failed; }
        if (family != AF_UNSPEC && (int)af != family) { errno = EPROTO; goto failed; }
        a->family = (int)af;
        out->count++;
        if (canonical[0]) strcpy(out->name, canonical);
    }
    close(fd);
    if (!out->count) { *err = 0; *herr = NO_DATA; return NSS_STATUS_NOTFOUND; }
    *err = 0; *herr = NETDB_SUCCESS;
    return NSS_STATUS_SUCCESS;
failed:
    { int saved = errno; close(fd); errno = saved; }
    return failure(err, herr);
invalid:
    *err = EINVAL; *herr = HOST_NOT_FOUND;
    return NSS_STATUS_NOTFOUND;
}

/* NSS buffers can start at an arbitrary alignment. Keep every stored pointer
 * and tuple aligned, and never return pointers into our stack or heap. */
struct buffer { char *ptr; size_t left; };
static void *take(struct buffer *b, size_t size, size_t align) {
    size_t skip = (-(uintptr_t)b->ptr) & (align - 1);
    if (skip > b->left || size > b->left - skip) return NULL;
    void *p = b->ptr + skip;
    b->ptr += skip + size; b->left -= skip + size;
    return p;
}

static enum nss_status range_error(int *err, int *herr) {
    *err = ERANGE; *herr = NETDB_INTERNAL;
    return NSS_STATUS_TRYAGAIN;
}

static enum nss_status pack_host(const struct answer *a, int family, struct hostent *result,
                                char *buffer, size_t size, int *err, int *herr) {
    struct buffer b = {buffer, size};
    char *name = take(&b, strlen(a->name) + 1, 1);
    char **aliases = take(&b, sizeof(char *), _Alignof(char *));
    char **addresses = take(&b, (a->count + 1) * sizeof(char *), _Alignof(char *));
    size_t width = family == AF_INET ? 4 : 16;
    char *bytes = take(&b, a->count * width, _Alignof(uint32_t));
    if (!name || !aliases || !addresses || !bytes) return range_error(err, herr);
    strcpy(name, a->name); aliases[0] = NULL;
    for (size_t i = 0; i < a->count; ++i) {
        addresses[i] = bytes + i * width;
        memcpy(addresses[i], a->addr[i].bytes, width);
    }
    addresses[a->count] = NULL;
    *result = (struct hostent){name, aliases, family, (int)width, addresses};
    return NSS_STATUS_SUCCESS;
}

enum nss_status _nss_android_gethostbyname3_r(const char *name, int family,
        struct hostent *result, char *buffer, size_t size, int *err, int *herr,
        int32_t *ttl, char **canonical) {
    if (family != AF_INET && family != AF_INET6) {
        *err = EAFNOSUPPORT; *herr = NO_DATA; return NSS_STATUS_UNAVAIL;
    }
    struct answer answer;
    enum nss_status status = lookup(name, family, &answer, err, herr);
    if (status != NSS_STATUS_SUCCESS) return status;
    status = pack_host(&answer, family, result, buffer, size, err, herr);
    if (status == NSS_STATUS_SUCCESS) {
        if (ttl) *ttl = 0; /* Android owns the DNS cache and TTLs. */
        if (canonical) *canonical = result->h_name;
    }
    return status;
}

enum nss_status _nss_android_gethostbyname2_r(const char *name, int family,
        struct hostent *result, char *buffer, size_t size, int *err, int *herr) {
    return _nss_android_gethostbyname3_r(name, family, result, buffer, size, err, herr, NULL, NULL);
}

enum nss_status _nss_android_gethostbyname_r(const char *name, struct hostent *result,
        char *buffer, size_t size, int *err, int *herr) {
    return _nss_android_gethostbyname2_r(name, AF_INET, result, buffer, size, err, herr);
}

enum nss_status _nss_android_gethostbyname4_r(const char *name, struct gaih_addrtuple **result,
        char *buffer, size_t size, int *err, int *herr, int32_t *ttl) {
    struct answer answer;
    enum nss_status status = lookup(name, AF_UNSPEC, &answer, err, herr);
    if (status != NSS_STATUS_SUCCESS) return status;
    struct buffer b = {buffer, size};
    char *canonical = take(&b, strlen(answer.name) + 1, 1);
    struct gaih_addrtuple *tuples = take(&b, answer.count * sizeof *tuples, _Alignof(struct gaih_addrtuple));
    if (!canonical || !tuples) return range_error(err, herr);
    strcpy(canonical, answer.name);
    memset(tuples, 0, answer.count * sizeof *tuples);
    for (size_t i = 0; i < answer.count; ++i) {
        tuples[i].name = canonical;
        tuples[i].family = answer.addr[i].family;
        tuples[i].scopeid = answer.addr[i].scope;
        memcpy(tuples[i].addr, answer.addr[i].bytes, answer.addr[i].family == AF_INET ? 4 : 16);
        if (i + 1 < answer.count) tuples[i].next = &tuples[i + 1];
    }
    /* glibc may supply an existing first tuple. */
    if (*result) **result = tuples[0];
    else *result = tuples;
    if (ttl) *ttl = 0;
    return NSS_STATUS_SUCCESS;
}

enum nss_status _nss_android_gethostbyaddr2_r(const void *address, socklen_t length, int family,
        struct hostent *result, char *buffer, size_t size, int *err, int *herr, int32_t *ttl) {
    if ((family != AF_INET && family != AF_INET6) ||
        length != (family == AF_INET ? 4u : 16u)) {
        *err = EAFNOSUPPORT; *herr = NO_DATA; return NSS_STATUS_UNAVAIL;
    }
    char numeric[INET6_ADDRSTRLEN], command[128];
    if (!inet_ntop(family, address, numeric, sizeof numeric)) return failure(err, herr);
    snprintf(command, sizeof command, "gethostbyaddr %s %u %d 0", numeric, (unsigned)length, family);
    enum nss_status status;
    int fd = request(command, &status, err, herr);
    if (fd < 0) return status;
    struct answer answer = {0};
    if (read_string(fd, answer.name, sizeof answer.name)) goto failed;
    char alias[MAX_NAME];
    /* Read aliases but expose the canonical name only, as for forward lookup. */
    for (size_t i = 0;; ++i) {
        if (i == MAX_ADDRS) { errno = EOVERFLOW; goto failed; }
        if (read_string(fd, alias, sizeof alias)) goto failed;
        if (!alias[0]) break;
    }
    uint32_t af, width;
    if (read_u32(fd, &af) || read_u32(fd, &width)) goto failed;
    if ((int)af != family || width != length) { errno = EPROTO; goto failed; }
    for (size_t i = 0;; ++i) {
        uint32_t len;
        unsigned char bytes[16];
        if (read_u32(fd, &len)) goto failed;
        if (!len) break;
        if (i == MAX_ADDRS) { errno = EOVERFLOW; goto failed; }
        /* Android serializes every hostent address in a 16-byte slot. */
        if (len != 16 || read_all(fd, bytes, len)) { errno = EPROTO; goto failed; }
    }
    close(fd);
    if (!answer.name[0]) { *err = 0; *herr = HOST_NOT_FOUND; return NSS_STATUS_NOTFOUND; }
    answer.count = 1; answer.addr[0].family = family;
    memcpy(answer.addr[0].bytes, address, length);
    status = pack_host(&answer, family, result, buffer, size, err, herr);
    if (status == NSS_STATUS_SUCCESS) {
        *err = 0; *herr = NETDB_SUCCESS;
        if (ttl) *ttl = 0;
    }
    return status;
failed:
    { int saved = errno; close(fd); errno = saved; }
    return failure(err, herr);
}

enum nss_status _nss_android_gethostbyaddr_r(const void *address, socklen_t length, int family,
        struct hostent *result, char *buffer, size_t size, int *err, int *herr) {
    return _nss_android_gethostbyaddr2_r(address, length, family, result, buffer, size, err, herr, NULL);
}
