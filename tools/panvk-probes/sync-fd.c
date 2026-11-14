/* Separate extension presence from actual SYNC_FD import/export support. */
#include <dlfcn.h>
#include <dirent.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <vulkan/vulkan.h>

#define CHECK(call) do { \
   VkResult r_ = (call); \
   if (r_ != VK_SUCCESS) { fprintf(stderr, "FAIL %s: %d\n", #call, r_); return 1; } \
} while (0)

static int fd_count(void)
{
   DIR *dir = opendir("/proc/self/fd");
   if (!dir) return -1;
   int count = 0;
   struct dirent *entry;
   while ((entry = readdir(dir)))
      if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) count++;
   closedir(dir);
   return count;
}

static int wait_fd(int fd)
{
   if (fd == -1) return 0;
   struct pollfd p = {.fd=fd, .events=POLLIN};
   int r;
   do { r = poll(&p, 1, 5000); } while (r < 0 && errno == EINTR);
   if (r != 1 || p.revents != POLLIN) {
      fprintf(stderr, "FAIL sync file poll: result=%d revents=%x errno=%d\n", r, p.revents, errno);
      return 1;
   }
   return 0;
}

static int exercise(PFN_vkGetInstanceProcAddr gipa, VkInstance instance,
                    VkPhysicalDevice physical, VkDevice device)
{
#define LOAD(name) \
   PFN_vk##name name = (PFN_vk##name)gipa(instance, "vk" #name); \
   if (!name) { fprintf(stderr, "FAIL missing vk%s\n", #name); return 1; }
   LOAD(GetDeviceQueue) LOAD(CreateBuffer) LOAD(GetBufferMemoryRequirements)
   LOAD(GetPhysicalDeviceMemoryProperties) LOAD(AllocateMemory) LOAD(BindBufferMemory)
   LOAD(MapMemory) LOAD(UnmapMemory) LOAD(DestroyBuffer) LOAD(FreeMemory)
   LOAD(CreateCommandPool) LOAD(AllocateCommandBuffers) LOAD(BeginCommandBuffer)
   LOAD(CmdFillBuffer) LOAD(CmdPipelineBarrier) LOAD(EndCommandBuffer) LOAD(DestroyCommandPool)
   LOAD(CreateSemaphore) LOAD(DestroySemaphore) LOAD(GetSemaphoreFdKHR) LOAD(ImportSemaphoreFdKHR)
   LOAD(CreateFence) LOAD(WaitForFences) LOAD(ResetFences) LOAD(DestroyFence) LOAD(QueueSubmit)
#undef LOAD
   VkQueue queue;
   GetDeviceQueue(device, 0, 0, &queue);
   VkBufferCreateInfo bci = {.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
      .size=4096, .usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT};
   VkBuffer buffer;
   CHECK(CreateBuffer(device, &bci, NULL, &buffer));
   VkMemoryRequirements req;
   GetBufferMemoryRequirements(device, buffer, &req);
   VkPhysicalDeviceMemoryProperties mp;
   GetPhysicalDeviceMemoryProperties(physical, &mp);
   uint32_t type;
   for (type=0; type<mp.memoryTypeCount; type++)
      if ((req.memoryTypeBits & (1u<<type)) &&
          (mp.memoryTypes[type].propertyFlags & (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
           VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) == (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
           VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) break;
   if (type == mp.memoryTypeCount) return 1;
   VkMemoryAllocateInfo mai = {.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
      .allocationSize=req.size, .memoryTypeIndex=type};
   VkDeviceMemory memory;
   CHECK(AllocateMemory(device, &mai, NULL, &memory));
   CHECK(BindBufferMemory(device, buffer, memory, 0));
   uint32_t *map;
   CHECK(MapMemory(device, memory, 0, VK_WHOLE_SIZE, 0, (void **)&map));
   memset(map, 0, 4096);
   VkCommandPoolCreateInfo pci = {.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
      .queueFamilyIndex=0};
   VkCommandPool pool;
   CHECK(CreateCommandPool(device, &pci, NULL, &pool));
   VkCommandBufferAllocateInfo cai = {.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
      .commandPool=pool, .level=VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount=1};
   VkCommandBuffer cmd;
   CHECK(AllocateCommandBuffers(device, &cai, &cmd));
   VkCommandBufferBeginInfo begin = {.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
   CHECK(BeginCommandBuffer(cmd, &begin));
   CmdFillBuffer(cmd, buffer, 0, 4096, 0x12345678);
   VkMemoryBarrier barrier = {.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask=VK_ACCESS_HOST_READ_BIT};
   CmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
      0, 1, &barrier, 0, NULL, 0, NULL);
   CHECK(EndCommandBuffer(cmd));
   VkExportSemaphoreCreateInfo ex = {.sType=VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO,
      .handleTypes=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT};
   VkSemaphoreCreateInfo sci = {.sType=VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, .pNext=&ex};
   VkSemaphore sem, imported;
   CHECK(CreateSemaphore(device, &sci, NULL, &sem));
   sci.pNext = NULL;
   CHECK(CreateSemaphore(device, &sci, NULL, &imported));
   VkFenceCreateInfo fci = {.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
   VkFence fence;
   CHECK(CreateFence(device, &fci, NULL, &fence));
   VkSubmitInfo first_empty = {.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,
      .signalSemaphoreCount=1, .pSignalSemaphores=&sem};
   CHECK(QueueSubmit(queue, 1, &first_empty, fence));
   CHECK(WaitForFences(device, 1, &fence, VK_TRUE, 5000000000ull));
   VkSemaphoreGetFdInfoKHR first_get = {.sType=VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
      .semaphore=sem, .handleType=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT};
   int first_fd = -2;
   CHECK(GetSemaphoreFdKHR(device, &first_get, &first_fd));
   if (first_fd < -1 || wait_fd(first_fd)) return 1;
   if (first_fd >= 0) close(first_fd);
   CHECK(ResetFences(device, 1, &fence));
   printf("PASS empty first submission: fd=%d\n", first_fd);
   unsigned real_fds = 0;
   int initial_fds = -1;
   for (unsigned n=0; n<300; n++) {
      VkSubmitInfo submit = {.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,
         .commandBufferCount=1, .pCommandBuffers=&cmd,
         .signalSemaphoreCount=1, .pSignalSemaphores=&sem};
      CHECK(QueueSubmit(queue, 1, &submit, fence));
      VkSemaphoreGetFdInfoKHR get = {.sType=VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
         .semaphore=sem, .handleType=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT};
      int fd = -2;
      CHECK(GetSemaphoreFdKHR(device, &get, &fd));
      if (fd < -1) return 1;
      real_fds += fd >= 0;
      if (wait_fd(fd)) return 1;
      CHECK(WaitForFences(device, 1, &fence, VK_TRUE, 5000000000ull));
      for (unsigned i=0; i<1024; i++)
         if (map[i] != 0x12345678) {
            fprintf(stderr, "FAIL GPU output[%u]=%x\n", i, map[i]); return 1;
         }
      CHECK(ResetFences(device, 1, &fence));
      VkImportSemaphoreFdInfoKHR imp = {.sType=VK_STRUCTURE_TYPE_IMPORT_SEMAPHORE_FD_INFO_KHR,
         .semaphore=imported, .flags=VK_SEMAPHORE_IMPORT_TEMPORARY_BIT,
         .handleType=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT, .fd=fd};
      VkResult r = ImportSemaphoreFdKHR(device, &imp);
      if (r != VK_SUCCESS && fd >= 0) close(fd);
      CHECK(r);
      VkPipelineStageFlags stage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
      VkSubmitInfo consume = {.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,
         .waitSemaphoreCount=1, .pWaitSemaphores=&imported, .pWaitDstStageMask=&stage};
      CHECK(QueueSubmit(queue, 1, &consume, fence));
      CHECK(WaitForFences(device, 1, &fence, VK_TRUE, 5000000000ull));
      CHECK(ResetFences(device, 1, &fence));
      memset(map, 0, 4096);
      if (n == 0) initial_fds = fd_count();
   }
   int final_fds = fd_count();
   if (initial_fds < 0 || final_fds != initial_fds) {
      fprintf(stderr, "FAIL FD lifetime: first=%d final=%d\n", initial_fds, final_fds);
      return 1;
   }
   printf("PASS FD lifetime: first=%d final=%d\n", initial_fds, final_fds);
   printf("PASS real-work/export/poll/import/reuse: 300 iterations, real_fds=%u\n", real_fds);
   VkSubmitInfo empty = {.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,
      .signalSemaphoreCount=1, .pSignalSemaphores=&sem};
   CHECK(QueueSubmit(queue, 1, &empty, fence));
   CHECK(WaitForFences(device, 1, &fence, VK_TRUE, 5000000000ull));
   VkSemaphoreGetFdInfoKHR get = {.sType=VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
      .semaphore=sem, .handleType=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT};
   int fd = -2;
   CHECK(GetSemaphoreFdKHR(device, &get, &fd));
   if (fd < -1 || wait_fd(fd)) return 1;
   if (fd >= 0) close(fd);
   printf("PASS already-signalled export: fd=%d\n", fd);
   CHECK(ResetFences(device, 1, &fence));
   VkImportSemaphoreFdInfoKHR imp = {.sType=VK_STRUCTURE_TYPE_IMPORT_SEMAPHORE_FD_INFO_KHR,
      .semaphore=imported, .flags=VK_SEMAPHORE_IMPORT_TEMPORARY_BIT,
      .handleType=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT, .fd=-1};
   CHECK(ImportSemaphoreFdKHR(device, &imp));
   VkPipelineStageFlags stage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
   VkSubmitInfo consume = {.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,
      .waitSemaphoreCount=1, .pWaitSemaphores=&imported, .pWaitDstStageMask=&stage};
   CHECK(QueueSubmit(queue, 1, &consume, fence));
   CHECK(WaitForFences(device, 1, &fence, VK_TRUE, 5000000000ull));
   puts("PASS import fd=-1");
   DestroyFence(device, fence, NULL);
   DestroySemaphore(device, imported, NULL);
   DestroySemaphore(device, sem, NULL);
   DestroyCommandPool(device, pool, NULL);
   UnmapMemory(device, memory);
   DestroyBuffer(device, buffer, NULL);
   FreeMemory(device, memory, NULL);
   return 0;
}

static int pending(PFN_vkGetInstanceProcAddr gipa, VkInstance instance,
                   VkDevice device, int fd)
{
   PFN_vkCreateSemaphore create = (PFN_vkCreateSemaphore)gipa(instance, "vkCreateSemaphore");
   PFN_vkDestroySemaphore destroy = (PFN_vkDestroySemaphore)gipa(instance, "vkDestroySemaphore");
   PFN_vkImportSemaphoreFdKHR import = (PFN_vkImportSemaphoreFdKHR)gipa(instance, "vkImportSemaphoreFdKHR");
   PFN_vkGetSemaphoreFdKHR export = (PFN_vkGetSemaphoreFdKHR)gipa(instance, "vkGetSemaphoreFdKHR");
   if (!create || !destroy || !import || !export || fd < 0) return 1;
   VkExportSemaphoreCreateInfo ex = {.sType=VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO,
      .handleTypes=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT};
   VkSemaphoreCreateInfo sci = {.sType=VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, .pNext=&ex};
   VkSemaphore sem;
   CHECK(create(device, &sci, NULL, &sem));
   VkImportSemaphoreFdInfoKHR imp = {.sType=VK_STRUCTURE_TYPE_IMPORT_SEMAPHORE_FD_INFO_KHR,
      .semaphore=sem, .flags=VK_SEMAPHORE_IMPORT_TEMPORARY_BIT,
      .handleType=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT, .fd=fd};
   int fence_fd = dup(fd);
   if (fence_fd < 0) return 1;
   CHECK(import(device, &imp));
   PFN_vkCreateFence create_fence = (PFN_vkCreateFence)gipa(instance, "vkCreateFence");
   PFN_vkImportFenceFdKHR import_fence = (PFN_vkImportFenceFdKHR)gipa(instance, "vkImportFenceFdKHR");
   PFN_vkWaitForFences wait_fence = (PFN_vkWaitForFences)gipa(instance, "vkWaitForFences");
   PFN_vkDestroyFence destroy_fence = (PFN_vkDestroyFence)gipa(instance, "vkDestroyFence");
   if (!create_fence || !import_fence || !wait_fence || !destroy_fence) return 1;
   VkFence fence;
   VkFenceCreateInfo fci = {.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
   CHECK(create_fence(device, &fci, NULL, &fence));
   VkImportFenceFdInfoKHR fi = {.sType=VK_STRUCTURE_TYPE_IMPORT_FENCE_FD_INFO_KHR,
      .fence=fence, .flags=VK_FENCE_IMPORT_TEMPORARY_BIT,
      .handleType=VK_EXTERNAL_FENCE_HANDLE_TYPE_SYNC_FD_BIT, .fd=fence_fd};
   CHECK(import_fence(device, &fi));
   VkResult wait_result = wait_fence(device, 1, &fence, VK_TRUE, 100000000ull);
   if (wait_result != VK_TIMEOUT) {
      fprintf(stderr, "FAIL pending CPU wait: %d\n", wait_result); return 1;
   }
   destroy_fence(device, fence, NULL);
   puts("PASS pending CPU wait: VK_TIMEOUT");
   VkSemaphoreGetFdInfoKHR get = {.sType=VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
      .semaphore=sem, .handleType=VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT};
   int copy = -2;
   CHECK(export(device, &get, &copy));
   if (copy < 0) { fprintf(stderr, "FAIL pending export fd=%d\n", copy); return 1; }
   struct pollfd p = {.fd=copy, .events=POLLIN};
   int r = poll(&p, 1, 100);
   close(copy);
   destroy(device, sem, NULL);
   if (r != 0) { fprintf(stderr, "FAIL pending fence signalled: %d %x\n", r, p.revents); return 1; }
   puts("PASS pending import/export: unsignalled fence timed out after 100 ms");
   return 0;
}

int main(int argc, char **argv)
{
   if (argc < 2 || argc > 4 ||
       (argc == 3 && strcmp(argv[2], "--exercise")) ||
       (argc == 4 && strcmp(argv[2], "--pending-fd"))) return 2;
   setvbuf(stdout, NULL, _IONBF, 0);
   alarm(60);
   void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
   PFN_vkGetInstanceProcAddr gipa = (PFN_vkGetInstanceProcAddr)dlsym(lib, "vk_icdGetInstanceProcAddr");
   if (!gipa) return 1;
   PFN_vkCreateInstance create = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
   VkApplicationInfo app = {.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion=VK_API_VERSION_1_3};
   VkInstanceCreateInfo ici = {.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo=&app};
   VkInstance instance;
   if (create(&ici, NULL, &instance)) return 1;
   PFN_vkEnumeratePhysicalDevices enumerate = (PFN_vkEnumeratePhysicalDevices)gipa(instance, "vkEnumeratePhysicalDevices");
   PFN_vkGetPhysicalDeviceExternalSemaphoreProperties properties =
      (PFN_vkGetPhysicalDeviceExternalSemaphoreProperties)gipa(instance, "vkGetPhysicalDeviceExternalSemaphoreProperties");
   PFN_vkCreateDevice create_device = (PFN_vkCreateDevice)gipa(instance, "vkCreateDevice");
   PFN_vkDestroyInstance destroy_instance = (PFN_vkDestroyInstance)gipa(instance, "vkDestroyInstance");
   uint32_t count = 1;
   VkPhysicalDevice physical;
   if (enumerate(instance, &count, &physical) || count != 1) return 1;
   PFN_vkGetPhysicalDeviceProperties2 get_properties =
      (PFN_vkGetPhysicalDeviceProperties2)gipa(instance, "vkGetPhysicalDeviceProperties2");
   VkPhysicalDeviceDriverProperties driver = {.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
   VkPhysicalDeviceProperties2 device_props = {.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,
      .pNext=&driver};
   get_properties(physical, &device_props);
   printf("device=%s driverID=%u driverName=%s driverInfo=%s\n",
      device_props.properties.deviceName, driver.driverID, driver.driverName, driver.driverInfo);
   VkExternalSemaphoreHandleTypeFlagBits types[] = {
      VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT,
      VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT};
   const char *names[] = {"OPAQUE_FD", "SYNC_FD"};
   float priority = 1;
   VkDeviceQueueCreateInfo qci = {.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
      .queueFamilyIndex=0, .queueCount=1, .pQueuePriorities=&priority};
   const char *extensions[] = {VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME,
      VK_KHR_EXTERNAL_FENCE_FD_EXTENSION_NAME};
   VkDeviceCreateInfo dci = {.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
      .queueCreateInfoCount=1, .pQueueCreateInfos=&qci,
      .enabledExtensionCount=argc == 4 ? 2 : 1, .ppEnabledExtensionNames=extensions};
   VkDevice device;
   VkResult rc = create_device(physical, &dci, NULL, &device);
   if (rc) { printf("create_device=%d\n", rc); return 1; }
   PFN_vkCreateSemaphore create_sem = (PFN_vkCreateSemaphore)gipa(instance, "vkCreateSemaphore");
   PFN_vkDestroySemaphore destroy_sem = (PFN_vkDestroySemaphore)gipa(instance, "vkDestroySemaphore");
   PFN_vkDestroyDevice destroy_device = (PFN_vkDestroyDevice)gipa(instance, "vkDestroyDevice");
   int supported = 0;
   for (unsigned i = 0; i < 2; i++) {
      VkPhysicalDeviceExternalSemaphoreInfo info = {
         .sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_SEMAPHORE_INFO, .handleType=types[i]};
      VkExternalSemaphoreProperties props = {.sType=VK_STRUCTURE_TYPE_EXTERNAL_SEMAPHORE_PROPERTIES};
      properties(physical, &info, &props);
      VkExportSemaphoreCreateInfo export = {.sType=VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO,
         .handleTypes=types[i]};
      VkSemaphoreCreateInfo sci = {.sType=VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, .pNext=&export};
      VkSemaphore sem;
      rc = create_sem(device, &sci, NULL, &sem);
      printf("%s: importable=%d exportable=%d compatible=0x%x create_exportable=%d\n",
         names[i], !!(props.externalSemaphoreFeatures & VK_EXTERNAL_SEMAPHORE_FEATURE_IMPORTABLE_BIT),
         !!(props.externalSemaphoreFeatures & VK_EXTERNAL_SEMAPHORE_FEATURE_EXPORTABLE_BIT),
         props.compatibleHandleTypes, rc);
      if (i == 1) supported = rc == VK_SUCCESS &&
         (props.externalSemaphoreFeatures & (VK_EXTERNAL_SEMAPHORE_FEATURE_IMPORTABLE_BIT |
          VK_EXTERNAL_SEMAPHORE_FEATURE_EXPORTABLE_BIT)) ==
         (VK_EXTERNAL_SEMAPHORE_FEATURE_IMPORTABLE_BIT | VK_EXTERNAL_SEMAPHORE_FEATURE_EXPORTABLE_BIT);
      if (rc == VK_SUCCESS) destroy_sem(device, sem, NULL);
   }
   int result = 0;
   if (argc >= 3) {
      if (!supported) { puts("SKIP exercise: SYNC_FD unsupported"); result = 77; }
      else if (argc == 4) result = pending(gipa, instance, device, atoi(argv[3]));
      else result = exercise(gipa, instance, physical, device);
   }
   destroy_device(device, NULL);
   destroy_instance(instance, NULL);
   dlclose(lib);
   return result;
}
