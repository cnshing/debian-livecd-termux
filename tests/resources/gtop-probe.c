/* An ordinary libgtop client: no dependency on the resource backend API. */
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include <glibtop.h>
#include <glibtop/cpu.h>
#include <glibtop/proclist.h>
#include <glibtop/proctime.h>
int main(void) {
    glibtop_cpu first, second;
    glibtop_get_cpu(&first); usleep(250000); glibtop_get_cpu(&second);
    assert(first.flags && second.flags && second.total > first.total);
    assert(glibtop_global_server->ncpu == 7);
    glibtop_proclist list;
    pid_t *pids = glibtop_get_proclist(&list, GLIBTOP_KERN_PROC_ALL, 0);
    assert(pids && list.number > 100);
    g_free(pids);
    glibtop_proc_time process;
    glibtop_get_proc_time(&process, 1);
    assert(process.flags && process.frequency);
    printf("PASS unmodified libgtop API: %d CPUs, %llu tick delta, %llu processes, PID 1 runtime %llu\n",
        glibtop_global_server->ncpu + 1, (unsigned long long)(second.total - first.total),
        (unsigned long long)list.number, (unsigned long long)process.rtime);
}
