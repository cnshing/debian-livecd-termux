/* SPDX-License-Identifier: MIT
 * Privileged, request-driven reader. Run through rish, never as the GUI.
 * No timer, snapshot files, arbitrary paths, or process-control commands.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <unistd.h>

#define MAX_DATA (8 * 1024 * 1024)
static int direct_transport;

static int write_all(const char *data, size_t size) {
    while (size) {
        ssize_t written = write(STDOUT_FILENO, data, size);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) return -1;
        data += written; size -= (size_t)written;
    }
    return 0;
}

static int atomic_write(const char *data, size_t size) {
    ssize_t written;
    do { written = write(STDOUT_FILENO, data, size); } while (written < 0 && errno == EINTR);
    return written == (ssize_t)size ? 0 : -1;
}

/* This Shizuku+ rish can have two readers draining the same output pipe.
 * Keep only one <= PIPE_BUF write outstanding, acknowledged by the client,
 * so its forwarding threads cannot reorder consecutive output chunks.
 * A checksum rejects corrupted data rather than presenting false counters.
 */
static int send_snapshot(const char *kind, const char *data, size_t length) {
    uint32_t hash = UINT32_C(2166136261);
    for (size_t i = 0; i < length; i++) hash = (hash ^ (unsigned char)data[i]) * UINT32_C(16777619);
    char header[128];
    int header_size = snprintf(header, sizeof header, "MC_DATA_V%d %s %zu %u\n", direct_transport ? 3 : 2, kind, length, (unsigned)hash);
    if (direct_transport) {
        if (header_size < 0 || header_size >= (int)sizeof header) return -1;
        return write_all(header, (size_t)header_size) || write_all(data, length) ? -1 : 0;
    }
    if (header_size < 0 || header_size >= (int)sizeof header || atomic_write(header, (size_t)header_size)) return -1;
    char ack[8];
    if (!fgets(ack, sizeof ack, stdin) || strcmp(ack, "ack\n")) return -1;
    for (size_t offset = 0; offset < length; offset += 2048) {
        size_t size = length - offset < 2048 ? length - offset : 2048;
        // fwrite on Bionic can split even an unbuffered 2 KiB write into 1 KiB
        // syscalls, which revives rish's competing-reader race. Use one write.
        if (atomic_write(data + offset, size)) return -1;
        if (!fgets(ack, sizeof ack, stdin) || strcmp(ack, "ack\n")) return -1;
    }
    return 0;
}

static ssize_t read_file(const char *path, char *buffer, size_t capacity) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    size_t length = 0;
    while (length < capacity) {
        ssize_t n = read(fd, buffer + length, capacity - length);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { int error = errno; close(fd); errno = error; return -1; }
        if (!n) break;
        length += (size_t)n;
    }
    close(fd);
    if (length == capacity) { errno = EOVERFLOW; return -1; }
    buffer[length] = 0;
    return (ssize_t)length;
}

static void hex(FILE *out, const char *bytes, size_t length) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < length; i++) {
        unsigned char c = (unsigned char)bytes[i];
        fputc(digits[c >> 4], out); fputc(digits[c & 15], out);
    }
}

static int processes(FILE *out, int extended) {
    DIR *proc = opendir("/proc");
    if (!proc) return -1;
    struct dirent *entry;
    while ((entry = readdir(proc))) {
        char *end;
        unsigned long pid = strtoul(entry->d_name, &end, 10);
        if (!pid || *end) continue;
        char path[128], stat_buffer[4096], cmd[8192], exe[4096];
        struct stat metadata;
        snprintf(path, sizeof path, "/proc/%lu", pid);
        if (stat(path, &metadata)) continue;
        snprintf(path, sizeof path, "/proc/%lu/stat", pid);
        ssize_t stat_size = read_file(path, stat_buffer, sizeof stat_buffer);
        if (stat_size < 0) continue; // Exited or inaccessible, never an invented row.
        snprintf(path, sizeof path, "/proc/%lu/cmdline", pid);
        ssize_t cmd_size = read_file(path, cmd, sizeof cmd);
        snprintf(path, sizeof path, "/proc/%lu/exe", pid);
        ssize_t exe_size = readlink(path, exe, sizeof exe);
        fprintf(out, "P\t%lu\t%lu\t", pid, (unsigned long)metadata.st_uid);
        hex(out, stat_buffer, (size_t)stat_size); fputc('\t', out);
        if (cmd_size > 0) hex(out, cmd, (size_t)cmd_size);
        fputc('\t', out);
        if (exe_size > 0 && exe_size < (ssize_t)sizeof exe) hex(out, exe, (size_t)exe_size);
        if (extended) {
            const char *names[] = {"status", "statm", "io"};
            for (size_t i = 0; i < sizeof names / sizeof *names; i++) {
                char value[16384];
                snprintf(path, sizeof path, "/proc/%lu/%s", pid, names[i]);
                ssize_t size = read_file(path, value, sizeof value);
                fputc('\t', out);
                if (size > 0) hex(out, value, (size_t)size);
            }
            fprintf(out, "\t%lu", (unsigned long)metadata.st_gid);
        }
        fputc('\n', out);
        if (ftell(out) > MAX_DATA) { closedir(proc); errno = EOVERFLOW; return -1; }
    }
    closedir(proc);
    return 0;
}

static int threads(FILE *out) {
    DIR *proc = opendir("/proc");
    if (!proc) return -1;
    struct dirent *process;
    while ((process = readdir(proc))) {
        char *end;
        unsigned long owner = strtoul(process->d_name, &end, 10);
        if (!owner || *end) continue;
        char path[256];
        snprintf(path, sizeof path, "/proc/%lu/task", owner);
        DIR *tasks = opendir(path);
        if (!tasks) continue;
        struct dirent *task;
        while ((task = readdir(tasks))) {
            unsigned long tid = strtoul(task->d_name, &end, 10);
            if (!tid || *end) continue;
            snprintf(path, sizeof path, "/proc/%lu/task/%lu", owner, tid);
            struct stat metadata;
            if (stat(path, &metadata)) continue;
            snprintf(path, sizeof path, "/proc/%lu/task/%lu/stat", owner, tid);
            char value[4096];
            ssize_t size = read_file(path, value, sizeof value);
            if (size < 0) continue;
            fprintf(out, "T\t%lu\t%lu\t%lu\t%lu\t", owner, tid,
                (unsigned long)metadata.st_uid, (unsigned long)metadata.st_gid);
            hex(out, value, (size_t)size); fputc('\n', out);
            if (ftell(out) > MAX_DATA) { closedir(tasks); closedir(proc); errno = EOVERFLOW; return -1; }
        }
        closedir(tasks);
    }
    closedir(proc);
    return 0;
}

static int telemetry(FILE *out, int include_gpu) {
    DIR *thermal = opendir("/sys/class/thermal");
    struct dirent *entry;
    if (thermal) {
        while ((entry = readdir(thermal))) {
            if (strncmp(entry->d_name, "thermal_zone", 12)) continue;
            char path[512], type[256], value[128];
            snprintf(path, sizeof path, "/sys/class/thermal/%s/type", entry->d_name);
            ssize_t n = read_file(path, type, sizeof type);
            if (n <= 0) continue;
            snprintf(path, sizeof path, "/sys/class/thermal/%s/temp", entry->d_name);
            if (read_file(path, value, sizeof value) <= 0) continue;
            fprintf(out, "thermal\t"); hex(out, type, (size_t)n);
            fprintf(out, "\t%s", value);
            if (value[strlen(value) - 1] != '\n') fputc('\n', out);
        }
        closedir(thermal);
    }
    if (!include_gpu) return 0;
    const char *names[] = {"gpu_model", "gpubusy", "gpuclk", "gpu_available_frequencies"};
    for (size_t i = 0; i < sizeof names / sizeof *names; i++) {
        char path[256], value[4096];
        snprintf(path, sizeof path, "/sys/class/kgsl/kgsl-3d0/%s", names[i]);
        if (read_file(path, value, sizeof value) <= 0) continue;
        fprintf(out, "%s\t%s", names[i], value);
        if (value[strlen(value) - 1] != '\n') fputc('\n', out);
    }
    return 0;
}

static int data_request(const char *kind) {
    char *data = NULL;
    size_t length = 0;
    FILE *out = open_memstream(&data, &length);
    if (!out) return -1;
    int result = !strcmp(kind, "threads") ? threads(out) : !strncmp(kind, "processes", 9) ? processes(out, !strcmp(kind, "processes-v2")) : telemetry(out, strcmp(kind, "thermals") != 0);
    int error = result ? errno : 0;
    if (fclose(out)) error = errno;
    if (length > MAX_DATA) error = EOVERFLOW;
    if (error) printf("MC_STAT_ERROR_V1 errno=%d\n", error);
    else result = send_snapshot(kind, data, length);
    free(data);
    return result;
}

/* Fixed procfs/sysfs ABI paths only. Never accept traversal or an arbitrary
 * shell command, file path, writable descriptor or process-control operation. */
static int digits(const char **path) {
    const char *start = *path;
    while (**path >= '0' && **path <= '9') (*path)++;
    return *path != start;
}

static int allowed(const char *path, int listing, int link) {
    if (strstr(path, "..") || strchr(path, '\n') || strchr(path, '\r')) return 0;
    if (listing) return !strcmp(path, "/proc") || !strcmp(path, "/sys/class/thermal");
    if (!strncmp(path, "/proc/", 6)) {
        const char *name = path + 6;
        if (digits(&name) && *name++ == '/') {
            if (!strncmp(name, "task/", 5)) { name += 5; if (!digits(&name) || *name++ != '/') return 0; }
            if (link) return !strcmp(name, "exe");
            const char *files[] = {"stat", "status", "statm", "cmdline", "io", "comm", "wchan", "oom_score", "oom_score_adj", "smaps_rollup"};
            for (size_t i = 0; i < sizeof files / sizeof *files; i++) if (!strcmp(name, files[i])) return 1;
            return 0;
        }
        if (link) return 0;
        const char *files[] = {"stat", "meminfo", "loadavg", "uptime", "net/dev", "diskstats", "vmstat", "pressure/cpu", "pressure/memory", "pressure/io"};
        for (size_t i = 0; i < sizeof files / sizeof *files; i++) if (!strcmp(path + 6, files[i])) return 1;
    }
    if (link) return 0;
    const char *thermal = "/sys/class/thermal/thermal_zone";
    if (!strncmp(path, thermal, strlen(thermal))) {
        const char *name = path + strlen(thermal);
        return digits(&name) && *name++ == '/' && (!strcmp(name, "type") || !strcmp(name, "temp"));
    }
    const char *kgsl = "/sys/class/kgsl/kgsl-3d0/";
    if (!strncmp(path, kgsl, strlen(kgsl))) {
        const char *name = path + strlen(kgsl);
        return !strcmp(name, "gpu_model") || !strcmp(name, "gpubusy") || !strcmp(name, "gpuclk") || !strcmp(name, "gpu_available_frequencies");
    }
    return 0;
}

static int path_request(const char *request) {
    int listing = !strncmp(request, "list ", 5), link = !strncmp(request, "link ", 5), meta = !strncmp(request, "meta ", 5);
    const char *path = request + 5;
    int error = 0, result = 0;
    char *data = NULL;
    size_t length = 0;
    char check[4096];
    size_t path_length = strlen(path);
    snprintf(check, sizeof check, "%s%s", path, meta && path_length && path[path_length - 1] >= '0' && path[path_length - 1] <= '9' ? "/stat" : "");
    if (!allowed(meta ? check : path, listing, link)) error = EACCES;
    else if (meta) {
        struct stat metadata;
        if (stat(path, &metadata)) error = errno;
        else {
            char value[256];
            int size = snprintf(value, sizeof value, "%lu %lu %lu %lu %llu %lld %lld %lld %lld", (unsigned long)metadata.st_uid,
                (unsigned long)metadata.st_gid, (unsigned long)metadata.st_mode, (unsigned long)metadata.st_nlink,
                (unsigned long long)metadata.st_ino, (long long)metadata.st_size, (long long)metadata.st_atime,
                (long long)metadata.st_mtime, (long long)metadata.st_ctime);
            data = strdup(value);
            if (!data) error = ENOMEM;
            else length = (size_t)size;
        }
    }
    else if (listing) {
        FILE *out = open_memstream(&data, &length);
        if (!out) error = errno;
        else {
            DIR *dir = opendir(path);
            if (!dir) error = errno;
            else {
                struct dirent *entry;
                while ((entry = readdir(dir))) {
                    const char *name = entry->d_name;
                    if (!strcmp(path, "/proc")) { if (!digits(&name) || *name) continue; }
                    else if (strncmp(name, "thermal_zone", 12)) continue;
                    fprintf(out, "%s\n", entry->d_name);
                }
                closedir(dir);
            }
            if (fclose(out)) error = errno;
        }
    } else {
        data = malloc(MAX_DATA);
        if (!data) error = ENOMEM;
        else {
            ssize_t size = link ? readlink(path, data, MAX_DATA) : read_file(path, data, MAX_DATA);
            if (size < 0) error = errno;
            else length = (size_t)size;
        }
    }
    if (error) {
        char message[64];
        length = (size_t)snprintf(message, sizeof message, "%d", error);
        result = send_snapshot("error", message, length);
    } else result = send_snapshot(meta ? "meta" : listing ? "list" : link ? "link" : "read", data, length);
    free(data);
    return result;
}

static int connect_broker(const char *port_text, const char *token) {
    char *end;
    unsigned long port = strtoul(port_text, &end, 10);
    if (*end || !port || port > 65535 || strlen(token) != 64) return -1;
    for (size_t i = 0; i < 64; i++) if (!strchr("0123456789abcdef", token[i])) return -1;
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    int no_delay = 1;
    if (setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &no_delay, sizeof no_delay)) { close(fd); return -1; }
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port), .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    if (connect(fd, (struct sockaddr *)&address, sizeof address)) { close(fd); return -1; }
    pid_t child = fork();
    if (child < 0) { close(fd); return -1; }
    if (child) { close(fd); return 1; }
    if (setsid() < 0 || dup2(fd, STDIN_FILENO) < 0 || dup2(fd, STDOUT_FILENO) < 0) _exit(1);
    if (fd > STDERR_FILENO) close(fd);
    int null = open("/dev/null", O_WRONLY | O_CLOEXEC);
    if (null < 0 || dup2(null, STDERR_FILENO) < 0) _exit(1);
    if (null > STDERR_FILENO) close(null);
    direct_transport = 1;
    if (write_all(token, 64) || write_all("\n", 1)) _exit(1);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 1) {
        if (argc != 4 || strcmp(argv[1], "--connect")) return 2;
        int result = connect_broker(argv[2], argv[3]);
        if (result) return result > 0 ? 0 : 1;
        memset(argv[3], 0, strlen(argv[3]));
    }
    char snapshot[65536], request[4096];
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("MC_STAT_READY_V1 pid=%ld uid=%ld\n", (long)getpid(), (long)getuid());
    if (fflush(stdout)) return 1;
    while (fgets(request, sizeof request, stdin)) {
        if (!strcmp(request, "quit\n")) break;
        if (!strcmp(request, "threads\n") || !strcmp(request, "processes-v2\n") || !strcmp(request, "processes\n") || !strcmp(request, "telemetry\n") || !strcmp(request, "thermals\n")) {
            request[strlen(request) - 1] = 0;
            if (data_request(request) || fflush(stdout)) return 1;
            continue;
        }
        if (!strncmp(request, "meta ", 5) || !strncmp(request, "read ", 5) || !strncmp(request, "list ", 5) || !strncmp(request, "link ", 5)) {
            size_t size = strlen(request);
            if (!size || request[size - 1] != '\n') return 2;
            request[size - 1] = 0;
            if (path_request(request)) return 1;
            continue;
        }
        /* Bound input, including a peer sending a line without a newline. */
        if (strcmp(request, "stat\n")) return 2;
        int fd = open("/proc/stat", O_RDONLY | O_CLOEXEC);
        int error = fd < 0 ? errno : 0;
        size_t length = 0;
        while (!error && length < sizeof snapshot) {
            ssize_t n = read(fd, snapshot + length, sizeof snapshot - length);
            if (n < 0) {
                if (errno == EINTR) continue;
                error = errno;
                break;
            }
            if (!n) break;
            length += (size_t)n;
        }
        if (fd >= 0) close(fd);
        if (length == sizeof snapshot) error = EOVERFLOW;
        if (error) printf("MC_STAT_ERROR_V1 errno=%d\n", error);
        else {
            if (send_snapshot("stat", snapshot, length)) break;
        }
        if (fflush(stdout)) break;
    }
    return ferror(stdin) || ferror(stdout) ? 1 : 0;
}
