/* SPDX-License-Identifier: MIT */
#ifndef ANDROID_PROCFS_H
#define ANDROID_PROCFS_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Fixed read-only categories: stat, processes, processes-v2, threads, thermals,
 * telemetry. Path requests: "read PATH", "meta PATH", "link PATH", "list PATH";
 * the shell reader enforces a fixed procfs/sysfs allowlist.
 * Returns 0 or errno. On failure *data is NULL and *length is 0. On success the
 * result has a trailing NUL, excluded from *length. No cached failure fallback.
 * All clients share one broker and reader. The reader ends with its last client.
 */
int android_procfs_snapshot(const char *category, char **data, size_t *length);
void android_procfs_free(char *data);
#ifdef __cplusplus
}
#endif
#endif
