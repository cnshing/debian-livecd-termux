/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <assert.h>
#include <stdio.h>
#include "../../packages/pulseaudio/aaudio-latency.h"

int main(void) {
    /* A 100 ms written buffer with 50 ms already presented. */
    assert(livecd_aaudio_latency_usec(4800, 4800, 2400, 1000000000, 1000000000, 48000) == 50000);
    /* Ten milliseconds of playback after the hardware timestamp. */
    assert(livecd_aaudio_latency_usec(4800, 4800, 2400, 1000000000, 1010000000, 48000) == 40000);
    /* The callback's 240 frames are rendered but not yet in FramesWritten. */
    assert(livecd_aaudio_latency_usec(4800, 5040, 2400, 1000000000, 1010000000, 48000) == 45000);
    /* Publishing the just-rendered callback must not jump the clock. */
    assert(livecd_aaudio_latency_usec(5040, 5040, 2400, 1000000000, 1010000000, 48000) == 45000);
    /* A timestamp may name a frame that will be presented in the future. */
    assert(livecd_aaudio_latency_usec(4800, 4800, 480, 1010000000, 1000000000, 48000) == 100000);
    /* Underruns and service timestamps advancing past queued data never wrap. */
    assert(livecd_aaudio_latency_usec(4800, 4800, 4800, 1000000000, 1050000000, 48000) == 0);
    assert(livecd_aaudio_latency_usec(0, 0, 0, 0, 0, 48000) == 0);
    assert(livecd_aaudio_latency_usec(4800, 4800, 0, 0, 0, 0) == 0);
    /* Real Android routes also use 44.1 kHz; retain frame precision. */
    assert(livecd_aaudio_latency_usec(4410, 4410, 0, 0, 1000000, 44100) == 99002);
    puts("AAudio presentation latency arithmetic: PASS");
    return 0;
}
