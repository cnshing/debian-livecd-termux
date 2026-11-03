/* SPDX-License-Identifier: MIT
 * Disposable CPU/RSS fixture, used only by the native acceptance tests.
 */
#include <stdint.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <unistd.h>

int main(void) {
    prctl(PR_SET_NAME, "mc-native-test", 0, 0, 0);
    volatile unsigned char *memory = malloc(32 * 1024 * 1024);
    if (!memory) return 1;
    for (size_t i = 0; i < 32 * 1024 * 1024; i += 4096) memory[i] = 1;
    volatile uint64_t value = (uint64_t)getpid();
    for (;;) {
        value = value * UINT64_C(6364136223846793005) + 1;
        memory[(value & 8191) * 4096]++;
    }
}
