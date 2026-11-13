/* Separate extension presence from actual SYNC_FD import/export support. */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <vulkan/vulkan.h>

int main(int argc, char **argv)
{
   if (argc != 2) return 2;
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
   const char *extension = VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME;
   VkDeviceCreateInfo dci = {.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
      .queueCreateInfoCount=1, .pQueueCreateInfos=&qci,
      .enabledExtensionCount=1, .ppEnabledExtensionNames=&extension};
   VkDevice device;
   VkResult rc = create_device(physical, &dci, NULL, &device);
   if (rc) { printf("create_device=%d\n", rc); return 1; }
   PFN_vkCreateSemaphore create_sem = (PFN_vkCreateSemaphore)gipa(instance, "vkCreateSemaphore");
   PFN_vkDestroySemaphore destroy_sem = (PFN_vkDestroySemaphore)gipa(instance, "vkDestroySemaphore");
   PFN_vkDestroyDevice destroy_device = (PFN_vkDestroyDevice)gipa(instance, "vkDestroyDevice");
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
      if (rc == VK_SUCCESS) destroy_sem(device, sem, NULL);
   }
   destroy_device(device, NULL);
   destroy_instance(instance, NULL);
   dlclose(lib);
   return 0;
}
