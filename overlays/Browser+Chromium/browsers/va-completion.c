/* SPDX-License-Identifier: MIT
 * Complete Termux:VA's CPU writes before Chromium consumes an exported surface.
 * Chromium's GPU decode path relies on implicit DRM synchronization. KGSL and
 * a MediaCodec/CPU producer need an explicit VA wait at the submission boundary.
 * This glibc-only preload is selected only for the browser hardware-video path.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* Stable public libva ABI: opaque display and 32-bit IDs/status. Keep this
 * adapter independent of a development libva installation in the Bionic prefix.
 * These declarations correspond to libva 2.22 va/va.h. No libva is linked here. */
typedef void *VADisplay;
typedef uint32_t VAContextID;
typedef uint32_t VASurfaceID;
typedef int32_t VAStatus;
enum {
    VA_STATUS_SUCCESS = 0,
    VA_STATUS_ERROR_ALLOCATION_FAILED = 2,
    VA_STATUS_ERROR_INVALID_CONTEXT = 5,
};
#define VA_INVALID_SURFACE UINT32_MAX

#if defined(__aarch64__)
#define DLSYM_VERSION "GLIBC_2.17"
#elif defined(__x86_64__)
#define DLSYM_VERSION "GLIBC_2.2.5"
#else
#error Unsupported glibc ABI
#endif

static VAStatus (*real_begin)(VADisplay, VAContextID, VASurfaceID);
static VAStatus (*real_end)(VADisplay, VAContextID);
static VAStatus (*real_destroy)(VADisplay, VAContextID);
static VAStatus (*real_sync)(VADisplay, VASurfaceID, uint64_t);

struct binding {
    VADisplay display;
    VAContextID context;
    VASurfaceID surface;
    bool submitted;
    struct binding *next;
};
static struct binding *bindings;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

static struct binding *find_binding(VADisplay display, VAContextID context)
{
    for (struct binding *b = bindings; b; b = b->next)
        if (b->display == display && b->context == context)
            return b;
    return NULL;
}

static VAStatus begin_picture(VADisplay display, VAContextID context, VASurfaceID surface)
{
    pthread_mutex_lock(&mutex);
    struct binding *b = find_binding(display, context);
    if (!b) {
        b = calloc(1, sizeof(*b));
        if (b) {
            b->display = display;
            b->context = context;
            b->next = bindings;
            bindings = b;
        }
    }
    pthread_mutex_unlock(&mutex);
    if (!b)
        return VA_STATUS_ERROR_ALLOCATION_FAILED;

    VAStatus status = real_begin(display, context, surface);
    if (status == VA_STATUS_SUCCESS) {
        pthread_mutex_lock(&mutex);
        b->surface = surface;
        b->submitted = true;
        pthread_mutex_unlock(&mutex);
    }
    return status;
}

static VAStatus end_picture(VADisplay display, VAContextID context)
{
    VAStatus status = real_end(display, context);
    const char *disabled = getenv("LIVECD_VA_DISABLE_COMPLETION");
    if (status != VA_STATUS_SUCCESS || (disabled && !strcmp(disabled, "1")))
        return status;

    pthread_mutex_lock(&mutex);
    struct binding *b = find_binding(display, context);
    const bool found = b && b->submitted;
    const VASurfaceID surface = found ? b->surface : VA_INVALID_SURFACE;
    if (found)
        b->submitted = false;
    pthread_mutex_unlock(&mutex);
    if (!found)
        return VA_STATUS_ERROR_INVALID_CONTEXT;

    struct timespec start, finish;
    clock_gettime(CLOCK_MONOTONIC, &start);
    /* A failed producer must not leave the GPU thread waiting indefinitely or
     * report a successful picture whose exported memory contains an old frame. */
    status = real_sync(display, surface, 500000000ull);
    clock_gettime(CLOCK_MONOTONIC, &finish);
    if (status != VA_STATUS_SUCCESS || getenv("LIVECD_VA_COMPLETION_LOG")) {
        double ms = (finish.tv_sec - start.tv_sec) * 1000.0 +
                    (finish.tv_nsec - start.tv_nsec) / 1000000.0;
        fprintf(stderr, "livecd-va-completion: context=%u surface=%u status=%d wait_ms=%.3f\n",
                context, surface, status, ms);
    }
    return status;
}

static VAStatus destroy_context(VADisplay display, VAContextID context)
{
    VAStatus status = real_destroy(display, context);
    if (status != VA_STATUS_SUCCESS)
        return status;
    pthread_mutex_lock(&mutex);
    for (struct binding **link = &bindings; *link; link = &(*link)->next) {
        struct binding *b = *link;
        if (b->display == display && b->context == context) {
            *link = b->next;
            free(b);
            break;
        }
    }
    pthread_mutex_unlock(&mutex);
    return status;
}

void *dlsym(void *handle, const char *name)
{
    void *(*lookup)(void *, const char *) = dlvsym(RTLD_NEXT, "dlsym", DLSYM_VERSION);
    if (!lookup)
        return NULL;
    if (!strcmp(name, "vaBeginPicture")) {
        real_begin = lookup(handle, name);
        return real_begin ? (void *)begin_picture : NULL;
    }
    if (!strcmp(name, "vaEndPicture")) {
        real_end = lookup(handle, name);
        real_sync = lookup(handle, "vaSyncSurface2");
        return real_end && real_sync ? (void *)end_picture : NULL;
    }
    if (!strcmp(name, "vaDestroyContext")) {
        real_destroy = lookup(handle, name);
        return real_destroy ? (void *)destroy_context : NULL;
    }
    /* Preserve RTLD_NEXT's original caller, including the ION/DRM hooks.
     * Production uses Clang; the portable branch supports host ABI tests. */
#ifdef __clang__
    __attribute__((musttail)) return lookup(handle, name);
#else
    return lookup(handle, name);
#endif
}
