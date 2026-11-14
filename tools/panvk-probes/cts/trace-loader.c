/* Diagnostic forwarding loader. No Vulkan calls or input structures are changed. */
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

static void *loader;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static pthread_mutex_t maps_lock = PTHREAD_MUTEX_INITIALIZER;
static struct mapping {
   VkDeviceMemory memory;
   VkDeviceSize bytes, offset, mapped_bytes;
   void *address;
} maps[128];

static void init(void)
{
   const char *path = getenv("PANVK_TRACE_LOADER");
   if (!path || !(loader = dlopen(path, RTLD_NOW | RTLD_LOCAL))) {
      fprintf(stderr, "TRACE loader unavailable: %s\n", path ? dlerror() : "PANVK_TRACE_LOADER unset");
      abort();
   }
}

static void *entry(const char *name)
{
   pthread_once(&once, init);
   void *p = dlsym(loader, name);
   if (!p) { fprintf(stderr, "TRACE missing %s\n", name); abort(); }
   return p;
}

#define NEXT(name) PFN_##name next = (PFN_##name)entry(#name)
#define HANDLE(h) ((uint64_t)(uintptr_t)(h))

VKAPI_ATTR VkResult VKAPI_CALL
vkCreateDevice(VkPhysicalDevice p, const VkDeviceCreateInfo *i,
               const VkAllocationCallbacks *a, VkDevice *d)
{
   NEXT(vkCreateDevice);
   fprintf(stderr, "TRACE CreateDevice flags=%u queues=%u robustBufferAccess=%u\n",
           i->flags, i->queueCreateInfoCount, i->pEnabledFeatures ? i->pEnabledFeatures->robustBufferAccess : 0);
   for (unsigned n = 0; n < i->enabledExtensionCount; n++)
      fprintf(stderr, "TRACE extension %s\n", i->ppEnabledExtensionNames[n]);
   for (const VkBaseInStructure *s = i->pNext; s; s = s->pNext)
      fprintf(stderr, "TRACE deviceFeatureSType=%u\n", s->sType);
   return next(p, i, a, d);
}

VKAPI_ATTR VkResult VKAPI_CALL
vkCreateBuffer(VkDevice d, const VkBufferCreateInfo *i, const VkAllocationCallbacks *a, VkBuffer *b)
{
   NEXT(vkCreateBuffer);
   VkResult r = next(d, i, a, b);
   fprintf(stderr, "TRACE CreateBuffer result=%d buffer=%" PRIx64 " bytes=%" PRIu64 " usage=%x\n",
           r, r == VK_SUCCESS ? HANDLE(*b) : 0, i->size, i->usage);
   return r;
}

VKAPI_ATTR VkResult VKAPI_CALL
vkAllocateMemory(VkDevice d, const VkMemoryAllocateInfo *i, const VkAllocationCallbacks *a, VkDeviceMemory *m)
{
   NEXT(vkAllocateMemory);
   VkResult r = next(d, i, a, m);
   fprintf(stderr, "TRACE AllocateMemory result=%d memory=%" PRIx64 " bytes=%" PRIu64 " type=%u\n",
           r, r == VK_SUCCESS ? HANDLE(*m) : 0, i->allocationSize, i->memoryTypeIndex);
   if (r == VK_SUCCESS) {
      pthread_mutex_lock(&maps_lock);
      unsigned n;
      for (n = 0; n < 128 && maps[n].memory; n++) {}
      if (n < 128) maps[n] = (struct mapping){.memory = *m, .bytes = i->allocationSize};
      else fprintf(stderr, "TRACE mapping table full\n");
      pthread_mutex_unlock(&maps_lock);
   }
   return r;
}

VKAPI_ATTR void VKAPI_CALL
vkFreeMemory(VkDevice d, VkDeviceMemory m, const VkAllocationCallbacks *a)
{
   NEXT(vkFreeMemory);
   pthread_mutex_lock(&maps_lock);
   for (unsigned n = 0; n < 128; n++) if (maps[n].memory == m) maps[n] = (struct mapping){0};
   pthread_mutex_unlock(&maps_lock);
   next(d, m, a);
}

VKAPI_ATTR VkResult VKAPI_CALL
vkMapMemory(VkDevice d, VkDeviceMemory m, VkDeviceSize offset, VkDeviceSize size, VkMemoryMapFlags f, void **p)
{
   NEXT(vkMapMemory);
   VkResult r = next(d, m, offset, size, f, p);
   fprintf(stderr, "TRACE MapMemory result=%d memory=%" PRIx64 " offset=%" PRIu64 " bytes=%" PRIu64 "\n",
           r, HANDLE(m), offset, size);
   if (r == VK_SUCCESS) {
      pthread_mutex_lock(&maps_lock);
      for (unsigned n = 0; n < 128; n++) if (maps[n].memory == m) {
         maps[n].address = *p;
         maps[n].offset = offset;
         maps[n].mapped_bytes = size == VK_WHOLE_SIZE ? maps[n].bytes - offset : size;
      }
      pthread_mutex_unlock(&maps_lock);
   }
   return r;
}

VKAPI_ATTR void VKAPI_CALL
vkUnmapMemory(VkDevice d, VkDeviceMemory m)
{
   NEXT(vkUnmapMemory);
   pthread_mutex_lock(&maps_lock);
   for (unsigned n = 0; n < 128; n++) if (maps[n].memory == m) maps[n].address = NULL;
   pthread_mutex_unlock(&maps_lock);
   next(d, m);
}

VKAPI_ATTR VkResult VKAPI_CALL
vkInvalidateMappedMemoryRanges(VkDevice d, uint32_t count, const VkMappedMemoryRange *ranges)
{
   NEXT(vkInvalidateMappedMemoryRanges);
   VkResult r = next(d, count, ranges);
   fprintf(stderr, "TRACE Invalidate result=%d ranges=%u\n", r, count);
   if (r != VK_SUCCESS) return r;
   pthread_mutex_lock(&maps_lock);
   for (unsigned k = 0; k < count; k++) for (unsigned n = 0; n < 128; n++) {
      const struct mapping *m = &maps[n];
      if (m->memory != ranges[k].memory || !m->address || ranges[k].offset < m->offset) continue;
      VkDeviceSize delta = ranges[k].offset - m->offset;
      if (delta >= m->mapped_bytes || (delta & 3)) continue;
      VkDeviceSize bytes = m->mapped_bytes - delta;
      if (ranges[k].size < bytes) bytes = ranges[k].size;
      unsigned words = bytes / 4 > 1024 ? 1024 : bytes / 4;
      volatile const uint32_t *p = (const uint32_t *)((const char *)m->address + delta);
      unsigned ones = 0, zeros = 0, first_bad = words;
      for (unsigned j = 0; j < words; j++) {
         uint32_t v = p[j];
         ones += v == 1; zeros += v == 0;
         if (v != 1 && first_bad == words) first_bad = j;
      }
      fprintf(stderr, "TRACE readback memory=%" PRIx64 " words=%u ones=%u zeros=%u firstNonOne=%u\n",
              HANDLE(m->memory), words, ones, zeros, first_bad);
   }
   pthread_mutex_unlock(&maps_lock);
   return r;
}

VKAPI_ATTR VkResult VKAPI_CALL
vkCreateShaderModule(VkDevice d, const VkShaderModuleCreateInfo *i, const VkAllocationCallbacks *a, VkShaderModule *m)
{
   NEXT(vkCreateShaderModule);
   uint64_t hash = UINT64_C(14695981039346656037);
   const unsigned char *code = (const unsigned char *)i->pCode;
   for (size_t n = 0; n < i->codeSize; n++) hash = (hash ^ code[n]) * UINT64_C(1099511628211);
   fprintf(stderr, "TRACE ShaderModule bytes=%zu fnv64=%016" PRIx64 "\n", i->codeSize, hash);
   const char *dir = getenv("PANVK_TRACE_SPIRV_DIR");
   if (dir) {
      char path[4096];
      int len = snprintf(path, sizeof(path), "%s/%016" PRIx64 ".spv", dir, hash);
      if (len > 0 && (size_t)len < sizeof(path)) {
         FILE *f = fopen(path, "wb");
         if (f) { fwrite(code, 1, i->codeSize, f); fclose(f); }
      }
   }
   return next(d, i, a, m);
}

VKAPI_ATTR VkResult VKAPI_CALL
vkCreateComputePipelines(VkDevice d, VkPipelineCache c, uint32_t count,
                        const VkComputePipelineCreateInfo *i, const VkAllocationCallbacks *a, VkPipeline *p)
{
   NEXT(vkCreateComputePipelines);
   for (unsigned n = 0; n < count; n++) {
      fprintf(stderr, "TRACE ComputePipeline flags=%x stageFlags=%x\n", i[n].flags, i[n].stage.flags);
      const VkSpecializationInfo *s = i[n].stage.pSpecializationInfo;
      for (unsigned j = 0; s && j < s->mapEntryCount; j++) {
         const VkSpecializationMapEntry *e = &s->pMapEntries[j];
         uint32_t value = 0;
         if (e->size == 4 && e->offset <= s->dataSize && s->dataSize - e->offset >= 4)
            memcpy(&value, (const char *)s->pData + e->offset, 4);
         fprintf(stderr, "TRACE specialization id=%u bytes=%zu value=%u\n", e->constantID, e->size, value);
      }
   }
   return next(d, c, count, i, a, p);
}

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice d, const char *name);
static PFN_vkVoidFunction wrapped(const char *name)
{
#define WRAP(n) if (!strcmp(name, #n)) return (PFN_vkVoidFunction)n
   WRAP(vkCreateDevice); WRAP(vkGetDeviceProcAddr); WRAP(vkCreateBuffer);
   WRAP(vkAllocateMemory); WRAP(vkFreeMemory); WRAP(vkMapMemory); WRAP(vkUnmapMemory);
   WRAP(vkInvalidateMappedMemoryRanges); WRAP(vkCreateShaderModule); WRAP(vkCreateComputePipelines);
#undef WRAP
   return NULL;
}

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vkGetInstanceProcAddr(VkInstance instance, const char *name)
{
   NEXT(vkGetInstanceProcAddr);
   PFN_vkVoidFunction real = next(instance, name), wrap = wrapped(name);
   return real && wrap ? wrap : real;
}

VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vkGetDeviceProcAddr(VkDevice device, const char *name)
{
   NEXT(vkGetDeviceProcAddr);
   PFN_vkVoidFunction real = next(device, name), wrap = wrapped(name);
   return real && wrap ? wrap : real;
}
