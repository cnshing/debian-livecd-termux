// Imports a buffer from the DMA-BUF heap API into Vulkan, then checks that
// the GPU reads what the CPU wrote and the CPU reads what the GPU wrote.
// Usage: vk-import <heap name> [libvulkan path]
//   1. CPU fills the whole buffer with 0x11.
//   2. GPU fills [0, half) with 0xcafebabe, then copies [half, half+4K) to [0, 4K).
//   3. CPU expects [0,4K)=0x11, [4K,half)=0xcafebabe, [half,end)=0x11.
// The device is whatever the loader offers first (set VK_DRIVER_FILES).
#define VK_NO_PROTOTYPES
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <vulkan/vulkan.h>

struct dma_heap_allocation_data { uint64_t len; uint32_t fd, fd_flags; uint64_t heap_flags; };
#define DMA_HEAP_IOCTL_ALLOC _IOWR('H', 0x0, struct dma_heap_allocation_data)
struct dma_buf_sync { uint64_t flags; };
#define DMA_BUF_IOCTL_SYNC _IOW('b', 0, struct dma_buf_sync)
#define SIZE (1u << 20)
#define HALF (SIZE / 2)

#define FAIL(...) do { printf(__VA_ARGS__); printf("\n"); return 1; } while (0)
#define CHECK(x) do { VkResult r_ = (x); if (r_) FAIL("%s = %d", #x, r_); } while (0)
static PFN_vkGetInstanceProcAddr gipa;
#define I(name) PFN_##name name = (PFN_##name)gipa(inst, #name)

int main(int argc, char **argv) {
    char path[128];
    snprintf(path, sizeof path, "/dev/dma_heap/%s", argc > 1 ? argv[1] : "system");
    int heap = open(path, O_RDONLY | O_CLOEXEC);
    if (heap < 0) FAIL("open %s: %s", path, strerror(errno));
    struct dma_heap_allocation_data d = {.len = SIZE, .fd_flags = O_RDWR | O_CLOEXEC};
    if (ioctl(heap, DMA_HEAP_IOCTL_ALLOC, &d)) FAIL("alloc: %s", strerror(errno));
    close(heap);
    int fd = (int)d.fd;
    uint8_t *cpu = mmap(0, SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (cpu == MAP_FAILED) FAIL("mmap: %s", strerror(errno));
    struct dma_buf_sync s = {.flags = 2 | 0}; // WRITE, START
    ioctl(fd, DMA_BUF_IOCTL_SYNC, &s);
    memset(cpu, 0x11, SIZE);
    s.flags = 2 | 4; // WRITE, END
    ioctl(fd, DMA_BUF_IOCTL_SYNC, &s);

    const char *lib = argc > 2 ? argv[2] : "libvulkan.so.1";
    void *vk = dlopen(lib, RTLD_NOW);
    if (!vk) FAIL("dlopen %s: %s", lib, dlerror());
    gipa = (PFN_vkGetInstanceProcAddr)dlsym(vk, "vkGetInstanceProcAddr");
    VkInstance inst = VK_NULL_HANDLE;
    PFN_vkCreateInstance vkCreateInstance = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    CHECK(vkCreateInstance(&(VkInstanceCreateInfo){VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
                                                   .pApplicationInfo = &app}, NULL, &inst));
    I(vkEnumeratePhysicalDevices); I(vkGetPhysicalDeviceProperties); I(vkGetPhysicalDeviceQueueFamilyProperties);
    I(vkCreateDevice); I(vkGetDeviceProcAddr);
    uint32_t n = 1; VkPhysicalDevice pd;
    vkEnumeratePhysicalDevices(inst, &n, &pd);
    if (!n) FAIL("no Vulkan device");
    VkPhysicalDeviceProperties props; vkGetPhysicalDeviceProperties(pd, &props);
    printf("device: %s\n", props.deviceName);
    uint32_t qn = 8; VkQueueFamilyProperties qf[8];
    vkGetPhysicalDeviceQueueFamilyProperties(pd, &qn, qf);
    uint32_t q = 0; while (q < qn && !(qf[q].queueFlags & (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT))) q++;
    const char *exts[] = {"VK_KHR_external_memory_fd", "VK_EXT_external_memory_dma_buf"};
    float prio = 1;
    VkDevice dev;
    CHECK(vkCreateDevice(pd, &(VkDeviceCreateInfo){VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1,
        .pQueueCreateInfos = &(VkDeviceQueueCreateInfo){VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                                         .queueFamilyIndex = q, .queueCount = 1, .pQueuePriorities = &prio},
        .enabledExtensionCount = 2, .ppEnabledExtensionNames = exts}, NULL, &dev));
#define D(name) PFN_##name name = (PFN_##name)vkGetDeviceProcAddr(dev, #name)
    D(vkGetDeviceQueue); D(vkCreateBuffer); D(vkGetBufferMemoryRequirements); D(vkGetMemoryFdPropertiesKHR);
    D(vkAllocateMemory); D(vkBindBufferMemory); D(vkCreateCommandPool); D(vkAllocateCommandBuffers);
    D(vkBeginCommandBuffer); D(vkCmdFillBuffer); D(vkCmdPipelineBarrier); D(vkCmdCopyBuffer);
    D(vkEndCommandBuffer); D(vkQueueSubmit); D(vkQueueWaitIdle);
    VkQueue queue; vkGetDeviceQueue(dev, q, 0, &queue);

    VkBuffer buf;
    CHECK(vkCreateBuffer(dev, &(VkBufferCreateInfo){VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .pNext = &(VkExternalMemoryBufferCreateInfo){VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,
            .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT},
        .size = SIZE, .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT}, NULL, &buf));
    VkMemoryRequirements req; vkGetBufferMemoryRequirements(dev, buf, &req);
    VkMemoryFdPropertiesKHR fdp = {VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR};
    CHECK(vkGetMemoryFdPropertiesKHR(dev, VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, fd, &fdp));
    uint32_t bits = req.memoryTypeBits & fdp.memoryTypeBits, type = 0;
    if (!bits) FAIL("no memory type for the dma-buf (req %#x, fd %#x)", req.memoryTypeBits, fdp.memoryTypeBits);
    while (!(bits & (1u << type))) type++;
    VkDeviceMemory mem;
    int import_fd = dup(fd); // Vulkan owns the imported descriptor
    CHECK(vkAllocateMemory(dev, &(VkMemoryAllocateInfo){VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .pNext = &(VkImportMemoryFdInfoKHR){VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR,
            .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, .fd = import_fd},
        .allocationSize = req.size > SIZE ? req.size : SIZE, .memoryTypeIndex = type}, NULL, &mem));
    CHECK(vkBindBufferMemory(dev, buf, mem, 0));

    VkCommandPool pool;
    CHECK(vkCreateCommandPool(dev, &(VkCommandPoolCreateInfo){VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .queueFamilyIndex = q}, NULL, &pool));
    VkCommandBuffer cb;
    CHECK(vkAllocateCommandBuffers(dev, &(VkCommandBufferAllocateInfo){VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1}, &cb));
    CHECK(vkBeginCommandBuffer(cb, &(VkCommandBufferBeginInfo){VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}));
    vkCmdFillBuffer(cb, buf, 0, HALF, 0xcafebabe);
    VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
                          .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT | VK_ACCESS_TRANSFER_WRITE_BIT};
    vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &mb, 0, 0, 0, 0);
    vkCmdCopyBuffer(cb, buf, buf, 1, &(VkBufferCopy){.srcOffset = HALF, .dstOffset = 0, .size = 4096});
    mb.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &mb, 0, 0, 0, 0);
    CHECK(vkEndCommandBuffer(cb));
    CHECK(vkQueueSubmit(queue, 1, &(VkSubmitInfo){VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .commandBufferCount = 1, .pCommandBuffers = &cb}, VK_NULL_HANDLE));
    CHECK(vkQueueWaitIdle(queue));

    s.flags = 1 | 0; // READ, START
    ioctl(fd, DMA_BUF_IOCTL_SYNC, &s);
    unsigned bad = 0;
    for (uint32_t i = 0; i < SIZE; i += 4) {
        uint32_t v; memcpy(&v, cpu + i, 4);
        uint32_t want = i < 4096 || i >= HALF ? 0x11111111u : 0xcafebabeu;
        if (v != want && bad++ < 4) printf("offset %#x: %#x, want %#x\n", i, v, want);
    }
    s.flags = 1 | 4;
    ioctl(fd, DMA_BUF_IOCTL_SYNC, &s);
    if (bad) FAIL("%u words wrong", bad);
    printf("ok: memory type %u, GPU read CPU data and CPU read GPU data\n", type);
    return 0;
}
