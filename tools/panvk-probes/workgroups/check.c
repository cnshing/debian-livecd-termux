// CPU oracle for every output word; source tests inspired by soulexit's lwg tests.
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(expr) do { VkResult r = (expr); if (r != VK_SUCCESS) { \
   fprintf(stderr, "%s: VkResult %d\n", #expr, r); return 1; } } while (0)
#define INST(name) PFN_##name name = (PFN_##name)gipa(instance, #name)
#define DEV(name) PFN_##name name = (PFN_##name)gdpa(device, #name)

int main(int argc, char **argv)
{
   setvbuf(stdout, NULL, _IONBF, 0);
   if (argc != 7) { fprintf(stderr, "check ICD SPV X Y Z run|compile|reject|skip\n"); return 2; }
   if (strcmp(argv[6], "run") && strcmp(argv[6], "compile") &&
       strcmp(argv[6], "reject") && strcmp(argv[6], "skip")) return 2;
   const int capture_stats = getenv("PANVK_PROBE_STATS") && !strcmp(getenv("PANVK_PROBE_STATS"), "1");
   unsigned x = strtoul(argv[3], NULL, 10), y = strtoul(argv[4], NULL, 10);
   unsigned z = strtoul(argv[5], NULL, 10), n = x * y * z;
   if (!x || !y || !z || n > 1024) return 2;
   void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
   PFN_vkGetInstanceProcAddr gipa = (PFN_vkGetInstanceProcAddr)dlsym(lib, "vk_icdGetInstanceProcAddr");
   if (!gipa) return 1;
   VkInstance instance = VK_NULL_HANDLE;
   INST(vkCreateInstance);
   VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
   VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
   CHECK(vkCreateInstance(&ici, NULL, &instance));
   INST(vkEnumeratePhysicalDevices); INST(vkGetPhysicalDeviceProperties);
   INST(vkGetPhysicalDeviceFeatures); INST(vkGetPhysicalDeviceMemoryProperties);
   INST(vkGetPhysicalDeviceQueueFamilyProperties); INST(vkCreateDevice);
   INST(vkGetDeviceProcAddr);
   uint32_t count = 1; VkPhysicalDevice physical;
   CHECK(vkEnumeratePhysicalDevices(instance, &count, &physical));
   if (count != 1) return 1;
   VkPhysicalDeviceProperties props;
   vkGetPhysicalDeviceProperties(physical, &props);
   printf("pipelineCacheUUID=");
   for (unsigned i = 0; i < VK_UUID_SIZE; i++) printf("%02x", props.pipelineCacheUUID[i]);
   putchar('\n');
   printf("device=%s maxInvocations=%u shape=%ux%ux%u mode=%s\n", props.deviceName,
          props.limits.maxComputeWorkGroupInvocations, x, y, z, argv[6]);
   if (props.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU || !strstr(props.deviceName, "Mali")) return 1;
   if (n > props.limits.maxComputeWorkGroupInvocations || x > props.limits.maxComputeWorkGroupSize[0] ||
       y > props.limits.maxComputeWorkGroupSize[1] || z > props.limits.maxComputeWorkGroupSize[2]) {
      puts("SKIP: shader exceeds advertised limits; no pipeline or dispatch");
      return !strcmp(argv[6], "skip") ? 0 : 1;
   }
   if (!strcmp(argv[6], "skip")) { puts("FAIL: expected a limit rejection"); return 1; }
   VkPhysicalDeviceFeatures features;
   vkGetPhysicalDeviceFeatures(physical, &features);
   uint32_t queues = 0;
   vkGetPhysicalDeviceQueueFamilyProperties(physical, &queues, NULL);
   VkQueueFamilyProperties *qp = calloc(queues, sizeof(*qp));
   if (!qp) return 1;
   vkGetPhysicalDeviceQueueFamilyProperties(physical, &queues, qp);
   unsigned family = 0;
   while (family < queues && !(qp[family].queueFlags & VK_QUEUE_COMPUTE_BIT)) family++;
   free(qp);
   if (family == queues) return 1;
   float priority = 1;
   VkDeviceQueueCreateInfo qi = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
      .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
   VkDeviceCreateInfo di = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
      .queueCreateInfoCount = 1, .pQueueCreateInfos = &qi, .pEnabledFeatures = &features};
   const char *stats_extension = VK_KHR_PIPELINE_EXECUTABLE_PROPERTIES_EXTENSION_NAME;
   VkPhysicalDevicePipelineExecutablePropertiesFeaturesKHR stats_feature = {
      .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PIPELINE_EXECUTABLE_PROPERTIES_FEATURES_KHR,
      .pipelineExecutableInfo = VK_TRUE};
   if (capture_stats) {
      INST(vkGetPhysicalDeviceFeatures2);
      VkPhysicalDeviceFeatures2 available = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2,
         .pNext = &stats_feature};
      vkGetPhysicalDeviceFeatures2(physical, &available);
      if (!stats_feature.pipelineExecutableInfo) {
         puts("FAIL: pipeline executable statistics unavailable"); return 1;
      }
      di.pNext = &stats_feature;
      di.enabledExtensionCount = 1;
      di.ppEnabledExtensionNames = &stats_extension;
   }
   VkDevice device;
   CHECK(vkCreateDevice(physical, &di, NULL, &device));
   PFN_vkGetDeviceProcAddr gdpa = vkGetDeviceProcAddr;
   DEV(vkCreateShaderModule); DEV(vkCreateDescriptorSetLayout); DEV(vkCreatePipelineLayout);
   DEV(vkCreateComputePipelines); DEV(vkCreateBuffer); DEV(vkGetBufferMemoryRequirements);
   DEV(vkAllocateMemory); DEV(vkBindBufferMemory); DEV(vkMapMemory);
   DEV(vkCreateDescriptorPool); DEV(vkAllocateDescriptorSets); DEV(vkUpdateDescriptorSets);
   DEV(vkCreateCommandPool); DEV(vkAllocateCommandBuffers); DEV(vkBeginCommandBuffer);
   DEV(vkEndCommandBuffer); DEV(vkCmdBindPipeline); DEV(vkCmdBindDescriptorSets);
   DEV(vkCmdDispatch); DEV(vkCmdPipelineBarrier); DEV(vkGetDeviceQueue);
   DEV(vkCreateFence); DEV(vkQueueSubmit); DEV(vkWaitForFences);
   FILE *file = fopen(argv[2], "rb");
   if (!file || fseek(file, 0, SEEK_END)) return 1;
   long bytes = ftell(file);
   if (bytes <= 0 || bytes % 4 || fseek(file, 0, SEEK_SET)) return 1;
   uint32_t *code = malloc(bytes);
   if (!code || fread(code, 1, bytes, file) != (size_t)bytes) return 1;
   fclose(file);
   VkShaderModuleCreateInfo smi = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
      .codeSize = bytes, .pCode = code};
   VkShaderModule module;
   CHECK(vkCreateShaderModule(device, &smi, NULL, &module)); free(code);
   VkDescriptorSetLayoutBinding binding = {.binding = 0, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
      .descriptorCount = 1, .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT};
   VkDescriptorSetLayoutCreateInfo sli = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
      .bindingCount = 1, .pBindings = &binding};
   VkDescriptorSetLayout sl;
   CHECK(vkCreateDescriptorSetLayout(device, &sli, NULL, &sl));
   VkPipelineLayoutCreateInfo pli = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
      .setLayoutCount = 1, .pSetLayouts = &sl};
   VkPipelineLayout layout;
   CHECK(vkCreatePipelineLayout(device, &pli, NULL, &layout));
   VkComputePipelineCreateInfo pi = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
      .flags = capture_stats ? VK_PIPELINE_CREATE_CAPTURE_STATISTICS_BIT_KHR : 0,
      .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
         .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = module, .pName = "main"}, .layout = layout};
   VkPipeline pipeline;
   VkResult result = vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pi, NULL, &pipeline);
   if (!strcmp(argv[6], "reject")) {
      printf("pipeline result=%d (expected %d); no dispatch\n", result, VK_ERROR_FEATURE_NOT_PRESENT);
      return result == VK_ERROR_FEATURE_NOT_PRESENT ? 0 : 1;
   }
   CHECK(result);
   if (capture_stats) {
      DEV(vkGetPipelineExecutablePropertiesKHR); DEV(vkGetPipelineExecutableStatisticsKHR);
      if (!vkGetPipelineExecutablePropertiesKHR || !vkGetPipelineExecutableStatisticsKHR) return 1;
      VkPipelineInfoKHR info = {.sType = VK_STRUCTURE_TYPE_PIPELINE_INFO_KHR, .pipeline = pipeline};
      uint32_t executables = 0;
      CHECK(vkGetPipelineExecutablePropertiesKHR(device, &info, &executables, NULL));
      if (!executables) return 1;
      for (uint32_t e = 0; e < executables; e++) {
         VkPipelineExecutableInfoKHR ei = {.sType = VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_INFO_KHR,
            .pipeline = pipeline, .executableIndex = e};
         uint32_t total = 0;
         CHECK(vkGetPipelineExecutableStatisticsKHR(device, &ei, &total, NULL));
         VkPipelineExecutableStatisticKHR *stats = calloc(total, sizeof(*stats));
         if (!total || !stats) return 1;
         for (uint32_t s = 0; s < total; s++)
            stats[s].sType = VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_STATISTIC_KHR;
         CHECK(vkGetPipelineExecutableStatisticsKHR(device, &ei, &total, stats));
         for (uint32_t s = 0; s < total; s++) {
            printf("STAT executable=%u name=%s value=", e, stats[s].name);
            switch (stats[s].format) {
            case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_BOOL32_KHR:
               printf("%u", stats[s].value.b32); break;
            case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_INT64_KHR:
               printf("%lld", (long long)stats[s].value.i64); break;
            case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_UINT64_KHR:
               printf("%llu", (unsigned long long)stats[s].value.u64); break;
            case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_FLOAT64_KHR:
               printf("%.9g", stats[s].value.f64); break;
            default: free(stats); return 1;
            }
            putchar('\n');
         }
         free(stats);
      }
   }
   if (!strcmp(argv[6], "compile")) { puts("PASS: pipeline creation; no dispatch"); return 0; }
   const size_t words = (size_t)n * 6 * 16;
   VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
      .size = words * 4, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
   VkBuffer buffer;
   CHECK(vkCreateBuffer(device, &bi, NULL, &buffer));
   VkMemoryRequirements req;
   vkGetBufferMemoryRequirements(device, buffer, &req);
   VkPhysicalDeviceMemoryProperties memory;
   vkGetPhysicalDeviceMemoryProperties(physical, &memory);
   unsigned type = 0;
   VkMemoryPropertyFlags want = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
   while (type < memory.memoryTypeCount && (!(req.memoryTypeBits & (1u << type)) ||
          (memory.memoryTypes[type].propertyFlags & want) != want)) type++;
   if (type == memory.memoryTypeCount) return 1;
   VkMemoryAllocateInfo mai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
      .allocationSize = req.size, .memoryTypeIndex = type};
   VkDeviceMemory allocation;
   CHECK(vkAllocateMemory(device, &mai, NULL, &allocation));
   CHECK(vkBindBufferMemory(device, buffer, allocation, 0));
   uint32_t *map;
   CHECK(vkMapMemory(device, allocation, 0, VK_WHOLE_SIZE, 0, (void **)&map));
   memset(map, 0xee, words * 4);
   VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1};
   VkDescriptorPoolCreateInfo dpi = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
      .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &ps};
   VkDescriptorPool pool;
   CHECK(vkCreateDescriptorPool(device, &dpi, NULL, &pool));
   VkDescriptorSetAllocateInfo sai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
      .descriptorPool = pool, .descriptorSetCount = 1, .pSetLayouts = &sl};
   VkDescriptorSet set;
   CHECK(vkAllocateDescriptorSets(device, &sai, &set));
   VkDescriptorBufferInfo dbi = {buffer, 0, VK_WHOLE_SIZE};
   VkWriteDescriptorSet write = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
      .dstSet = set, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
      .pBufferInfo = &dbi};
   vkUpdateDescriptorSets(device, 1, &write, 0, NULL);
   VkCommandPoolCreateInfo cpi = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = family};
   VkCommandPool commands;
   CHECK(vkCreateCommandPool(device, &cpi, NULL, &commands));
   VkCommandBufferAllocateInfo cai = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
      .commandPool = commands, .commandBufferCount = 1, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY};
   VkCommandBuffer cb;
   CHECK(vkAllocateCommandBuffers(device, &cai, &cb));
   VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
   CHECK(vkBeginCommandBuffer(cb, &begin));
   vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
   vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1, &set, 0, NULL);
   vkCmdDispatch(cb, 3, 2, 1);
   VkMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
      .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
   vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
      0, 1, &barrier, 0, NULL, 0, NULL);
   CHECK(vkEndCommandBuffer(cb));
   VkQueue queue;
   vkGetDeviceQueue(device, family, 0, &queue);
   VkFenceCreateInfo fi = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
   VkFence fence;
   CHECK(vkCreateFence(device, &fi, NULL, &fence));
   VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb};
   CHECK(vkQueueSubmit(queue, 1, &submit, fence));
   CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, 5000000000ull));
   size_t wrong = 0;
   for (unsigned g = 0; g < 6; g++) for (unsigned i = 0; i < n; i++) {
      unsigned lx = i % x, ly = (i / x) % y, lz = i / (x * y);
      unsigned mine = i * 3 + g * 17 + 1, neighbour = (n - 1 - i) * 3 + g * 17 + 1;
      uint32_t expected[16] = {i, lx, ly, lz, (g % 3) * x + lx, (g / 3) * y + ly,
         lz, x, y, z, g, neighbour, n * (n - 1) / 2, mine, 15, mine ^ neighbour};
      if (!strncmp(argv[6], "run-nested", 10)) {
         unsigned loops = 3 + g / 3;
         unsigned rotations = loops, delta = loops * (loops + 1) / 2;
         if (strstr(argv[6], "control")) {
            rotations--;
            delta -= 2;
         } else if (strstr(argv[6], "-if")) {
            rotations = (g % 3) % 2 == 0 ? 1 : 0;
            delta = rotations ? 13 : 29;
         }
         unsigned shared_value = ((i + rotations) % n) * 3 + g * 17 + 1 + delta;
         unsigned private_value = mine + (i & 3) * 11 + delta;
         expected[15] = shared_value ^ private_value;
      }
      for (unsigned w = 0; w < 16; w++) {
         uint32_t got = map[((size_t)g * n + i) * 16 + w];
         if (got != expected[w]) {
            if (wrong < 12) printf("mismatch g=%u i=%u word=%u got=%u expected=%u\n", g, i, w, got, expected[w]);
            wrong++;
         }
      }
   }
   printf("%s: %zu words checked, %zu wrong\n", wrong ? "FAIL" : "PASS", words, wrong);
   // Each case is its own process; the completed fence precedes process teardown.
   return wrong ? 1 : 0;
}
