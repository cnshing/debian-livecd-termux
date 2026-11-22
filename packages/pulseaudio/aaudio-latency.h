/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef LIVECD_AAUDIO_LATENCY_H
#define LIVECD_AAUDIO_LATENCY_H

#include <stdint.h>

/* Android's frame position is anchored to CLOCK_MONOTONIC. Account for
 * presentation since that timestamp, including data in the callback which
 * AAudio has not yet added to getFramesWritten(). */
static inline uint64_t livecd_aaudio_latency_usec(int64_t written,
                                                 int64_t submitted,
                                                 int64_t position,
                                                 int64_t timestamp_ns,
                                                 int64_t now_ns,
                                                 uint32_t rate) {
    int64_t end = written > submitted ? written : submitted;
    int64_t elapsed, advanced, remaining;

    if (!rate || end <= 0)
        return 0;

    elapsed = now_ns - timestamp_ns;
    advanced = (elapsed / 1000000000) * rate
             + ((elapsed % 1000000000) * rate) / 1000000000;
    position += advanced;
    if (position < 0)
        position = 0;
    if (position >= end)
        return 0;

    remaining = end - position;
    return (uint64_t)(remaining / rate) * 1000000
         + (uint64_t)(remaining % rate) * 1000000 / rate;
}
#endif
