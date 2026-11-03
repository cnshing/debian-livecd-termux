/* SPDX-License-Identifier: MIT
 * Run through livecd-resources-run on the Android rig with Shizuku authorized.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static unsigned long long ticks(int fd) {
    char buffer[65536];
    ssize_t size = read(fd, buffer, sizeof buffer - 1);
    assert(size > 0); buffer[size] = 0;
    unsigned long long values[8], total = 0;
    assert(sscanf(buffer, "cpu %llu %llu %llu %llu %llu %llu %llu %llu",
        &values[0], &values[1], &values[2], &values[3], &values[4], &values[5], &values[6], &values[7]) == 8);
    for (int i = 0; i < 8; i++) total += values[i];
    return total;
}

static unsigned long long process_ticks(int fd) {
    char buffer[4096]; ssize_t size = read(fd, buffer, sizeof buffer - 1);
    assert(size > 0); buffer[size] = 0;
    char *field = strrchr(buffer, ')'); assert(field); field += 2;
    for (int i = 0; i < 11; i++) { field = strchr(field, ' '); assert(field); field++; }
    char *end; unsigned long long user = strtoull(field, &end, 10);
    return user + strtoull(end, NULL, 10);
}

int main(void) {
    int fd = open("/proc/stat", O_RDONLY | O_CLOEXEC);
    assert(fd >= 0);
    assert((fcntl(fd, F_GETFL) & O_ACCMODE) == O_RDONLY);
    errno = 0; assert(write(fd, "x", 1) == -1 && errno == EBADF);
    unsigned long long first = ticks(fd);
    usleep(250000);
    assert(lseek(fd, 0, SEEK_SET) == 0);
    assert(ticks(fd) > first);
    int copy = dup(fd); assert(copy >= 0);
    assert(lseek(copy, 0, SEEK_SET) == 0); assert(ticks(copy) >= first);
    close(fd); close(copy);
    puts("PASS read-only open, held-fd rewind and dup");

    FILE *stream = fopen("/proc/stat", "re"); assert(stream);
    char line[4096]; assert(fgets(line, sizeof line, stream));
    usleep(250000); rewind(stream);
    char fresh[4096]; assert(fgets(fresh, sizeof fresh, stream));
    assert(strcmp(line, fresh)); fclose(stream);
    puts("PASS held FILE rewind returns fresh counters");

    int root = open("/proc", O_RDONLY | O_DIRECTORY | O_CLOEXEC); assert(root >= 0);
    DIR *dir = fdopendir(dup(root)); assert(dir);
    struct dirent *entry; size_t processes = 0; int init = 0;
    while ((entry = readdir(dir))) {
        if (entry->d_name[0] < '0' || entry->d_name[0] > '9') continue;
        processes++;
        if (strcmp(entry->d_name, "1")) continue;
        struct stat metadata;
        assert(fstatat(root, "1", &metadata, 0) == 0 && metadata.st_uid == 0);
        int process = openat(root, "1", O_RDONLY | O_DIRECTORY | O_CLOEXEC); assert(process >= 0);
        assert(fstat(process, &metadata) == 0 && metadata.st_uid == 0);
        int stat = openat(process, "stat", O_RDONLY); assert(stat >= 0);
        char buffer[4096]; ssize_t size = read(stat, buffer, sizeof buffer - 1); assert(size > 0);
        buffer[size] = 0; assert(strstr(buffer, "1 (init)")); close(stat);
        int tasks = openat(process, "task", O_RDONLY | O_DIRECTORY | O_CLOEXEC); assert(tasks >= 0);
        DIR *taskdir = fdopendir(tasks); assert(taskdir);
        size_t threads = 0;
        while ((entry = readdir(taskdir))) {
            if (entry->d_name[0] < '0' || entry->d_name[0] > '9') continue;
            threads++;
            char path[128]; snprintf(path, sizeof path, "%s/stat", entry->d_name);
            int thread = openat(tasks, path, O_RDONLY); assert(thread >= 0);
            size = read(thread, buffer, sizeof buffer - 1); assert(size > 0);
            buffer[size] = 0; assert(strtoul(buffer, NULL, 10) == strtoul(entry->d_name, NULL, 10));
            close(thread);
        }
        assert(threads >= 1);
        rewinddir(taskdir); size_t again = 0;
        while ((entry = readdir(taskdir))) if (entry->d_name[0] >= '0' && entry->d_name[0] <= '9') again++;
        assert(again >= 1 && again <= threads + 10);
        closedir(taskdir); close(process); init = 1;
    }
    assert(processes > 100 && init);
    rewinddir(dir); init = 0;
    while ((entry = readdir(dir))) if (!strcmp(entry->d_name, "1")) init = 1;
    assert(init); closedir(dir); close(root);
    printf("PASS procfs enumeration, dup+fdopendir, openat, UID and threads (%zu processes)\n", processes);

    struct stat metadata;
    errno = 0; assert(fstatat(-123, "relative", &metadata, 0) == -1 && errno == EBADF);
    assert(stat("/proc/1", &metadata) == 0 && metadata.st_uid == 0);
    assert(stat("/proc/1/stat", &metadata) == 0 && S_ISREG(metadata.st_mode));
    errno = 0; fd = open("/proc/1/environ", O_RDONLY); assert(fd == -1);
    fd = open("/proc/4294967295/stat", O_RDONLY); assert(fd == -1 && errno == ENOENT);
    fd = open("/proc/stat", O_RDONLY); assert(fd >= 0); close(fd);
    puts("PASS standalone metadata and inaccessible-file isolation");

    dir = opendir("/proc"); assert(dir);
    char own[32]; snprintf(own, sizeof own, "%ld", (long)getpid());
    int process = openat(dirfd(dir), own, O_RDONLY | O_DIRECTORY); assert(process >= 0);
    int retained = openat(process, "stat", O_RDONLY); assert(retained >= 0);
    first = process_ticks(retained); closedir(dir);
    struct timespec start, now; clock_gettime(CLOCK_MONOTONIC, &start);
    do { clock_gettime(CLOCK_MONOTONIC, &now); } while ((now.tv_sec - start.tv_sec) * 1000000000LL + now.tv_nsec - start.tv_nsec < 300000000);
    assert(fstat(process, &metadata) == 0 && metadata.st_uid == getuid());
    assert(lseek(retained, 0, SEEK_SET) == 0 && process_ticks(retained) > first);
    close(retained); close(process);
    puts("PASS retained PID descriptors refresh after their enumeration closes");

    pid_t child = fork(); assert(child >= 0);
    if (!child) { int sample = open("/proc/stat", O_RDONLY); _exit(sample >= 0 && ticks(sample) ? 0 : 1); }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    puts("PASS fork after shared-client initialization");

    dir = opendir("/sys/class/thermal"); assert(dir);
    size_t sensors = 0;
    while ((entry = readdir(dir))) {
        if (strncmp(entry->d_name, "thermal_zone", 12)) continue;
        char path[512]; snprintf(path, sizeof path, "/sys/class/thermal/%s/type", entry->d_name);
        fd = open(path, O_RDONLY);
        if (fd >= 0) { char type[256]; assert(read(fd, type, sizeof type) > 0); sensors++; close(fd); }
    }
    assert(sensors > 0); rewinddir(dir);
    entry = readdir(dir); assert(entry && !strncmp(entry->d_name, "thermal_zone", 12));
    closedir(dir);
    printf("PASS thermal sysfs paths (%zu sensors)\n", sensors);
    return 0;
}
