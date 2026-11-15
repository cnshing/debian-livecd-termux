#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/dma-buf.h>
#include <linux/memfd.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <unistd.h>

struct ion_alloc {
   uint64_t len;
   uint32_t heap_id_mask, flags, fd, unused;
};
struct ion_heap {
   char name[32];
   uint32_t type, id, reserved[3];
};
struct ion_query {
   uint32_t count, reserved0;
   uint64_t heaps;
   uint32_t reserved1, reserved2;
};
#define ION_ALLOC _IOWR('I', 0, struct ion_alloc)
#define ION_QUERY _IOWR('I', 8, struct ion_query)

struct observation {
   int stage, signal, code, error;
   uintptr_t address;
};
static volatile sig_atomic_t stage;
static int result_fd;

static void report_signal(int number, siginfo_t *info, void *context)
{
   (void)context;
   struct observation result = {stage, number, info->si_code, 0,
                                (uintptr_t)info->si_addr};
   ssize_t written = write(result_fd, &result, sizeof(result));
   (void)written;
   _exit(0);
}

static void fail(void)
{
   struct observation result = {stage, 0, 0, errno, 0};
   ssize_t written = write(result_fd, &result, sizeof(result));
   (void)written;
   _exit(1);
}

static void child(int ion, uint32_t heap, size_t size, uint32_t flags,
                  int entire_reservation, int output)
{
   result_fd = output;
   struct sigaction action = {.sa_sigaction = report_signal,
                              .sa_flags = SA_SIGINFO};
   sigemptyset(&action.sa_mask);
   if (sigaction(SIGBUS, &action, NULL) || sigaction(SIGSEGV, &action, NULL))
      fail();
   stage = 1;
   struct ion_alloc allocation = {.len = size, .heap_id_mask = heap,
                                  .flags = flags};
   if (ioctl(ion, ION_ALLOC, &allocation))
      fail();
   size_t page = (size_t)sysconf(_SC_PAGESIZE);
   size_t file_size = size + 3 * page;
   int file = (int)syscall(SYS_memfd_create, "ion-map-boundary", MFD_CLOEXEC);
   if (file < 0 || ftruncate(file, (off_t)file_size))
      fail();
   unsigned char *reservation = mmap(NULL, file_size, PROT_READ | PROT_WRITE,
                                     MAP_SHARED, file, 0);
   void *alias = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED,
                      (int)allocation.fd, 0);
   if (reservation == MAP_FAILED || alias == MAP_FAILED)
      fail();
   stage = 2;
   for (size_t i = 0; i < file_size; i++)
      ((volatile unsigned char *)reservation)[i] = 0x5a;
   unsigned char *placed = reservation + page;
   void *mapped = mmap(placed, size, PROT_READ | PROT_WRITE,
                       MAP_SHARED | MAP_FIXED, (int)allocation.fd, 0);
   if (mapped != placed)
      fail();
   stage = 3;
   struct dma_buf_sync sync = {.flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_RW};
   if (ioctl((int)allocation.fd, DMA_BUF_IOCTL_SYNC, &sync))
      fail();
   for (size_t i = 0; i < file_size; i++)
      ((volatile unsigned char *)reservation)[i] = 0x6b;
   stage = 4;
   void *(*libc_memset)(void *, int, size_t) = dlsym(RTLD_DEFAULT, "memset");
   if (!libc_memset) {
      errno = ENOSYS;
      fail();
   }
   libc_memset(entire_reservation ? reservation : placed, 0xab,
               entire_reservation ? file_size : size);
   stage = 5;
   volatile unsigned char *bytes = entire_reservation ? reservation : placed;
   size_t length = entire_reservation ? file_size : size;
   for (size_t i = 0; i < length; i++) {
      if (bytes[i] != 0xab) {
         errno = EIO;
         fail();
      }
   }
   stage = 6;
   sync.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_RW;
   if (ioctl((int)allocation.fd, DMA_BUF_IOCTL_SYNC, &sync))
      fail();
   struct observation result = {stage, 0, 0, 0, 0};
   ssize_t written = write(result_fd, &result, sizeof(result));
   _exit(written == (ssize_t)sizeof(result) ? 0 : 1);
}

int main(int argc, char **argv)
{
   int pinned_cpu = -1;
   if (argc != 1) {
      char *end = NULL;
      long cpu = argc == 3 ? strtol(argv[2], &end, 10) : -1;
      if (argc != 3 || strcmp(argv[1], "--cpu") || !end || *end ||
          cpu < 0 || cpu >= CPU_SETSIZE) {
         fprintf(stderr, "usage: %s [--cpu N]\n", argv[0]);
         return 2;
      }
      cpu_set_t cpus;
      CPU_ZERO(&cpus);
      CPU_SET(cpu, &cpus);
      if (sched_setaffinity(0, sizeof(cpus), &cpus)) {
         perror("CPU affinity");
         return 2;
      }
      pinned_cpu = (int)cpu;
   }
   int ion = open("/dev/ion", O_RDONLY | O_CLOEXEC);
   struct ion_heap heaps[64] = {0};
   struct ion_query query = {.count = 64, .heaps = (uintptr_t)heaps};
   if (ion < 0 || ioctl(ion, ION_QUERY, &query)) {
      perror("ION heap query");
      return 2;
   }
   uint32_t heap = 0;
   for (uint32_t i = 0; i < query.count && i < 64; i++) {
      if (heaps[i].type == 0 && heaps[i].id < 32) {
         heap = 1u << heaps[i].id;
         break;
      }
   }
   if (!heap)
      return 2;
   int failed = 0;
   const size_t sizes[] = {4096, 65536, 1048576};
   for (uint32_t cached = 0; cached <= 1; cached++) {
      for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); i++) {
         for (int entire = 0; entire <= 1; entire++) {
            int pipefd[2];
            if (pipe(pipefd))
               return 2;
            pid_t pid = fork();
            if (pid < 0)
               return 2;
            if (pid == 0) {
               close(pipefd[0]);
               child(ion, heap, sizes[i], cached, entire, pipefd[1]);
               _exit(2);
            }
            close(pipefd[1]);
            struct observation result = {0};
            ssize_t count = read(pipefd[0], &result, sizeof(result));
            close(pipefd[0]);
            int status;
            if (waitpid(pid, &status, 0) != pid || count != (ssize_t)sizeof(result) ||
                !WIFEXITED(status))
               return 2;
            const char *outcome = result.signal ? "caught_signal" :
                                  result.error ? "error" : "Pass";
            printf("{\"cpu_only\":true,\"pinned_cpu\":%d,\"ion_flags\":%u,\"bytes\":%zu,"
                   "\"whole_reservation\":%s,\"outcome\":\"%s\","
                   "\"stage\":%d,\"signal\":%d,\"si_code\":%d,"
                   "\"errno\":%d,\"fault_address\":\"0x%" PRIxPTR "\"}\n",
                   pinned_cpu, cached, sizes[i], entire ? "true" : "false", outcome,
                   result.stage, result.signal, result.code, result.error,
                   result.address);
            fflush(stdout);
            failed |= result.signal || result.error || WEXITSTATUS(status);
         }
      }
   }
   close(ion);
   return failed ? 1 : 0;
}
