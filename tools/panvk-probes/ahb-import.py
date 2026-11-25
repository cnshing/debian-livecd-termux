#!/usr/bin/env python3
"""Check public RGBA AHB layout and Vulkan import/readback, without an X display.

This is the import/readback gate for s20-panvk-ahb-present.md, not presentation.
Run from plain 64-bit Termux with LD_LIBRARY_PATH and LD_PRELOAD unset.
"""
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import platform
from pathlib import Path
import sys

U32, U64, PTR = C.c_uint32, C.c_uint64, C.c_void_p


def structure(name, *fields):
    return type(name, (C.Structure,), {'_fields_': fields})


Desc = structure('AHardwareBuffer_Desc', ('width', U32), ('height', U32),
    ('layers', U32), ('format', U32), ('usage', U64), ('stride', U32),
    ('rfu0', U32), ('rfu1', U64))
Plane = structure('AHardwareBuffer_Plane', ('data', PTR), ('pixelStride', U32),
    ('rowStride', U32))
Planes = structure('AHardwareBuffer_Planes', ('planeCount', U32), ('planes', Plane * 4))
App = structure('VkApplicationInfo', ('sType', U32), ('pNext', PTR),
    ('pApplicationName', C.c_char_p), ('applicationVersion', U32),
    ('pEngineName', C.c_char_p), ('engineVersion', U32), ('apiVersion', U32))
InstanceInfo = structure('VkInstanceCreateInfo', ('sType', U32), ('pNext', PTR),
    ('flags', U32), ('pApplicationInfo', C.POINTER(App)), ('enabledLayerCount', U32),
    ('ppEnabledLayerNames', PTR), ('enabledExtensionCount', U32),
    ('ppEnabledExtensionNames', PTR))
QueueInfo = structure('VkDeviceQueueCreateInfo', ('sType', U32), ('pNext', PTR),
    ('flags', U32), ('queueFamilyIndex', U32), ('queueCount', U32),
    ('pQueuePriorities', C.POINTER(C.c_float)))
DeviceInfo = structure('VkDeviceCreateInfo', ('sType', U32), ('pNext', PTR),
    ('flags', U32), ('queueCreateInfoCount', U32), ('pQueueCreateInfos', C.POINTER(QueueInfo)),
    ('enabledLayerCount', U32), ('ppEnabledLayerNames', PTR),
    ('enabledExtensionCount', U32), ('ppEnabledExtensionNames', C.POINTER(C.c_char_p)),
    ('pEnabledFeatures', PTR))
Extent = structure('VkExtent3D', ('width', U32), ('height', U32), ('depth', U32))
QueueProperties = structure('VkQueueFamilyProperties', ('queueFlags', U32),
    ('queueCount', U32), ('timestampValidBits', U32), ('minImageTransferGranularity', Extent))
Properties = structure('VkAndroidHardwareBufferPropertiesANDROID', ('sType', U32),
    ('pNext', PTR), ('allocationSize', U64), ('memoryTypeBits', U32))
ExternalImage = structure('VkExternalMemoryImageCreateInfo', ('sType', U32),
    ('pNext', PTR), ('handleTypes', U32))
ImageInfo = structure('VkImageCreateInfo', ('sType', U32), ('pNext', PTR),
    ('flags', U32), ('imageType', U32), ('format', U32), ('extent', Extent),
    ('mipLevels', U32), ('arrayLayers', U32), ('samples', U32), ('tiling', U32),
    ('usage', U32), ('sharingMode', U32), ('queueFamilyIndexCount', U32),
    ('pQueueFamilyIndices', PTR), ('initialLayout', U32))
ImportInfo = structure('VkImportAndroidHardwareBufferInfoANDROID', ('sType', U32),
    ('pNext', PTR), ('buffer', PTR))
DedicatedInfo = structure('VkMemoryDedicatedAllocateInfo', ('sType', U32),
    ('pNext', PTR), ('image', U64), ('buffer', U64))
AllocateInfo = structure('VkMemoryAllocateInfo', ('sType', U32), ('pNext', PTR),
    ('allocationSize', U64), ('memoryTypeIndex', U32))
BufferInfo = structure('VkBufferCreateInfo', ('sType', U32), ('pNext', PTR),
    ('flags', U32), ('size', U64), ('usage', U32), ('sharingMode', U32),
    ('queueFamilyIndexCount', U32), ('pQueueFamilyIndices', PTR))
Requirements = structure('VkMemoryRequirements', ('size', U64), ('alignment', U64), ('memoryTypeBits', U32))
MemoryType = structure('VkMemoryType', ('propertyFlags', U32), ('heapIndex', U32))
MemoryHeap = structure('VkMemoryHeap', ('size', U64), ('flags', U32))
MemoryProperties = structure('VkPhysicalDeviceMemoryProperties', ('memoryTypeCount', U32),
    ('memoryTypes', MemoryType * 32), ('memoryHeapCount', U32), ('memoryHeaps', MemoryHeap * 16))
PoolInfo = structure('VkCommandPoolCreateInfo', ('sType', U32), ('pNext', PTR),
    ('flags', U32), ('queueFamilyIndex', U32))
CommandInfo = structure('VkCommandBufferAllocateInfo', ('sType', U32), ('pNext', PTR),
    ('commandPool', U64), ('level', U32), ('commandBufferCount', U32))
BeginInfo = structure('VkCommandBufferBeginInfo', ('sType', U32), ('pNext', PTR),
    ('flags', U32), ('pInheritanceInfo', PTR))
SubresourceRange = structure('VkImageSubresourceRange', ('aspectMask', U32),
    ('baseMipLevel', U32), ('levelCount', U32), ('baseArrayLayer', U32), ('layerCount', U32))
ImageBarrier = structure('VkImageMemoryBarrier', ('sType', U32), ('pNext', PTR),
    ('srcAccessMask', U32), ('dstAccessMask', U32), ('oldLayout', U32), ('newLayout', U32),
    ('srcQueueFamilyIndex', U32), ('dstQueueFamilyIndex', U32), ('image', U64),
    ('subresourceRange', SubresourceRange))
BufferBarrier = structure('VkBufferMemoryBarrier', ('sType', U32), ('pNext', PTR),
    ('srcAccessMask', U32), ('dstAccessMask', U32), ('srcQueueFamilyIndex', U32),
    ('dstQueueFamilyIndex', U32), ('buffer', U64), ('offset', U64), ('size', U64))
Layers = structure('VkImageSubresourceLayers', ('aspectMask', U32), ('mipLevel', U32),
    ('baseArrayLayer', U32), ('layerCount', U32))
Offset = structure('VkOffset3D', ('x', C.c_int32), ('y', C.c_int32), ('z', C.c_int32))
BufferImageCopy = structure('VkBufferImageCopy', ('bufferOffset', U64),
    ('bufferRowLength', U32), ('bufferImageHeight', U32), ('imageSubresource', Layers),
    ('imageOffset', Offset), ('imageExtent', Extent))
FenceInfo = structure('VkFenceCreateInfo', ('sType', U32), ('pNext', PTR), ('flags', U32))
SubmitInfo = structure('VkSubmitInfo', ('sType', U32), ('pNext', PTR),
    ('waitSemaphoreCount', U32), ('pWaitSemaphores', PTR), ('pWaitDstStageMask', PTR),
    ('commandBufferCount', U32), ('pCommandBuffers', C.POINTER(PTR)),
    ('signalSemaphoreCount', U32), ('pSignalSemaphores', PTR))


def pattern(width, height):
    top = bytes((255, 0, 0, 255)) * (width // 2) + bytes((0, 0, 255, 255)) * (width - width // 2)
    bottom = bytes((255, 255, 0, 255)) * (width // 2) + bytes((0, 255, 255, 255)) * (width - width // 2)
    return top * (height // 2) + bottom * (height - height // 2)


def locked_pixels(android, buffer, width, height, write=None):
    if write is not None and len(write) != width * height * 4:
        raise ProbeError('CPU pattern size does not match the image')
    planes = Planes()
    result = android.AHardwareBuffer_lockPlanes(buffer, 0x33 if write is not None else 3,
                                                -1, None, C.byref(planes))
    if result:
        raise ProbeError(f'AHardwareBuffer_lockPlanes: {result}')
    try:
        plane = planes.planes[0]
        if planes.planeCount != 1 or not plane.data or plane.pixelStride != 4 or plane.rowStride < width * 4:
            raise ProbeError('Public CPU planes do not expose single-plane RGBA rows')
        rows = []
        for y in range(height):
            pointer = plane.data + y * plane.rowStride
            if write is not None:
                C.memmove(pointer, write[y * width * 4:(y + 1) * width * 4], width * 4)
            else:
                rows.append(C.string_at(pointer, width * 4))
        return b''.join(rows)
    finally:
        if android.AHardwareBuffer_unlock(buffer, None):
            raise ProbeError('AHardwareBuffer_unlock failed')


def address(value):
    return C.cast(C.pointer(value), PTR)


class ProbeError(RuntimeError):
    pass


def check(stage, result, record):
    record.setdefault('calls', []).append({'stage': stage, 'result': result})
    if result != 0:
        raise ProbeError(f'{stage}: {result}')


class Vulkan:
    def __init__(self, driver, record):
        self.instance, self.device = PTR(), PTR()
        self.record = record
        self.lib = C.CDLL(str(driver))
        self.gipa = self.lib.vk_icdGetInstanceProcAddr
        self.gipa.argtypes, self.gipa.restype = [PTR, C.c_char_p], PTR
        self.gdpa = None
        self.in_flight = False
        self.instance_created = self.device_created = False

    def function(self, name, result, *arguments, device=False):
        proc = (self.gdpa(self.device, name.encode()) if device else
                self.gipa(self.instance, name.encode()))
        if not proc:
            raise ProbeError('Missing Vulkan entry point: ' + name)
        return C.CFUNCTYPE(result, *arguments)(proc)

    def init(self):
        app = App(sType=0, apiVersion=(1 << 22) | (1 << 12))  # Vulkan 1.1
        info = InstanceInfo(sType=1, pApplicationInfo=C.pointer(app))
        check('vkCreateInstance', self.function('vkCreateInstance', C.c_int, PTR, PTR, PTR)(
            C.byref(info), None, C.byref(self.instance)), self.record)
        self.instance_created = True
        enum = self.function('vkEnumeratePhysicalDevices', C.c_int, PTR, PTR, PTR)
        count = U32()
        check('vkEnumeratePhysicalDevices.count', enum(self.instance, C.byref(count), None), self.record)
        if count.value != 1:
            raise ProbeError(f'Expected one physical device in the private ICD, got {count.value}')
        devices = (PTR * count.value)()
        check('vkEnumeratePhysicalDevices', enum(self.instance, C.byref(count), devices), self.record)
        physical = devices[0]
        self.physical = physical
        queues = self.function('vkGetPhysicalDeviceQueueFamilyProperties', None, PTR, PTR, PTR)
        queues(physical, C.byref(count), None)
        props = (QueueProperties * count.value)()
        queues(physical, C.byref(count), props)
        family = next((i for i, q in enumerate(props) if q.queueCount and q.queueFlags & 1), None)
        if family is None:
            raise ProbeError('No graphics queue')
        self.family = family
        priority = C.c_float(1)
        queue = QueueInfo(sType=2, queueFamilyIndex=family, queueCount=1,
                          pQueuePriorities=C.pointer(priority))
        extensions = (C.c_char_p * 2)(b'VK_ANDROID_external_memory_android_hardware_buffer',
                                      b'VK_EXT_queue_family_foreign')
        info = DeviceInfo(sType=3, queueCreateInfoCount=1, pQueueCreateInfos=C.pointer(queue),
                          enabledExtensionCount=len(extensions), ppEnabledExtensionNames=extensions)
        check('vkCreateDevice', self.function('vkCreateDevice', C.c_int, PTR, PTR, PTR, PTR)(
            physical, C.byref(info), None, C.byref(self.device)), self.record)
        self.device_created = True
        self.gdpa = self.function('vkGetDeviceProcAddr', PTR, PTR, C.c_char_p)

    def close(self):
        if self.in_flight:
            return
        if self.device_created:
            self.function('vkDestroyDevice', None, PTR, PTR, device=True)(self.device, None)
        if self.instance_created:
            self.function('vkDestroyInstance', None, PTR, PTR)(self.instance, None)

    def readback(self, image, width, height, initial, record):
        size = width * height * 4
        buffer, memory, pool, fence = U64(), U64(), U64(), U64()
        created = set()
        mapped = PTR()
        def call(name, result, arguments, *values):
            return self.function(name, result, PTR, *arguments, device=True)(self.device, *values)
        try:
            info = BufferInfo(sType=12, size=size * 2, usage=2)
            check('vkCreateBuffer', call('vkCreateBuffer', C.c_int, [PTR, PTR, PTR],
                C.byref(info), None, C.byref(buffer)), record)
            created.add('buffer')
            req = Requirements()
            call('vkGetBufferMemoryRequirements', None, [U64, PTR], buffer, C.byref(req))
            properties = MemoryProperties()
            self.function('vkGetPhysicalDeviceMemoryProperties', None, PTR, PTR)(
                self.physical, C.byref(properties))
            memory_type = next((i for i in range(properties.memoryTypeCount) if
                req.memoryTypeBits & (1 << i) and properties.memoryTypes[i].propertyFlags & 6 == 6), None)
            if memory_type is None:
                raise ProbeError('No coherent host-visible readback memory')
            info = AllocateInfo(sType=5, allocationSize=req.size, memoryTypeIndex=memory_type)
            check('vkAllocateMemory.readback', call('vkAllocateMemory', C.c_int, [PTR, PTR, PTR],
                C.byref(info), None, C.byref(memory)), record)
            created.add('memory')
            check('vkBindBufferMemory', call('vkBindBufferMemory', C.c_int, [U64, U64, U64],
                buffer, memory, 0), record)
            info = PoolInfo(sType=39, queueFamilyIndex=self.family)
            check('vkCreateCommandPool', call('vkCreateCommandPool', C.c_int, [PTR, PTR, PTR],
                C.byref(info), None, C.byref(pool)), record)
            created.add('pool')
            command = PTR()
            info = CommandInfo(sType=40, commandPool=pool.value, commandBufferCount=1)
            check('vkAllocateCommandBuffers', call('vkAllocateCommandBuffers', C.c_int, [PTR, PTR],
                C.byref(info), C.byref(command)), record)
            info = BeginInfo(sType=42, flags=1)
            check('vkBeginCommandBuffer', self.function('vkBeginCommandBuffer', C.c_int,
                PTR, PTR, device=True)(command, C.byref(info)), record)
            barrier_fn = self.function('vkCmdPipelineBarrier', None, PTR, U32, U32, U32,
                U32, PTR, U32, PTR, U32, PTR, device=True)
            full = SubresourceRange(1, 0, 1, 0, 1)
            def barrier(src, dst, old, new, source=0xFFFFFFFF, target=0xFFFFFFFF):
                value = ImageBarrier(sType=45, srcAccessMask=src, dstAccessMask=dst,
                    oldLayout=old, newLayout=new, srcQueueFamilyIndex=source,
                    dstQueueFamilyIndex=target, image=image.value, subresourceRange=full)
                barrier_fn(command, 0x10000, 0x10000, 0, 0, None, 0, None, 1, C.byref(value))
            copy = self.function('vkCmdCopyImageToBuffer', None, PTR, U64, U32, U64, U32, PTR, device=True)
            region = BufferImageCopy(imageSubresource=Layers(1, 0, 0, 1), imageExtent=Extent(width, height, 1))
            barrier(0, 0x800 if initial else 0x1000, 1 if initial else 0, 1,
                    0xFFFFFFFD, self.family)
            if initial:
                copy(command, image, 1, buffer, 1, C.byref(region))
                barrier(0x800, 0x1000, 1, 1)
            color = (C.c_float * 4)(*(value / 255 for value in record['clear_rgba']))
            self.function('vkCmdClearColorImage', None, PTR, U64, U32, PTR, U32, PTR,
                device=True)(command, image, 1, color, 1, C.byref(full))
            barrier(0x1000, 0x800, 1, 1)
            region.bufferOffset = size
            copy(command, image, 1, buffer, 1, C.byref(region))
            barrier(0x800, 0, 1, 1, self.family, 0xFFFFFFFD)
            host = BufferBarrier(sType=44, srcAccessMask=0x1000, dstAccessMask=0x2000,
                srcQueueFamilyIndex=0xFFFFFFFF, dstQueueFamilyIndex=0xFFFFFFFF,
                buffer=buffer.value, size=size * 2)
            barrier_fn(command, 0x1000, 0x4000, 0, 0, None, 1, C.byref(host), 0, None)
            check('vkEndCommandBuffer', self.function('vkEndCommandBuffer', C.c_int,
                PTR, device=True)(command), record)
            info = FenceInfo(sType=8)
            check('vkCreateFence', call('vkCreateFence', C.c_int, [PTR, PTR, PTR],
                C.byref(info), None, C.byref(fence)), record)
            created.add('fence')
            queue = PTR()
            call('vkGetDeviceQueue', None, [U32, U32, PTR], self.family, 0, C.byref(queue))
            info = SubmitInfo(sType=4, commandBufferCount=1, pCommandBuffers=C.pointer(command))
            check('vkQueueSubmit', self.function('vkQueueSubmit', C.c_int, PTR, U32, PTR, U64,
                device=True)(queue, 1, C.byref(info), fence), record)
            self.in_flight = True
            check('vkWaitForFences', call('vkWaitForFences', C.c_int, [U32, PTR, U32, U64],
                1, C.byref(fence), 1, 10_000_000_000), record)
            self.in_flight = False
            check('vkMapMemory', call('vkMapMemory', C.c_int, [U64, U64, U64, U32, PTR],
                memory, 0, size * 2, 0, C.byref(mapped)), record)
            if initial:
                record['cpu_to_gpu_verified'] = C.string_at(mapped, size) == pattern(width, height)
                if not record['cpu_to_gpu_verified']:
                    raise ProbeError('CPU pattern differs in GPU readback')
            record['gpu_readback_verified'] = C.string_at(mapped.value + size, size) == bytes(record['storage_clear_bytes']) * (width * height)
            if not record['gpu_readback_verified']:
                raise ProbeError('GPU clear differs in GPU readback')
        finally:
            if not self.in_flight:
                if mapped:
                    call('vkUnmapMemory', None, [U64], memory)
                if 'fence' in created:
                    call('vkDestroyFence', None, [U64, PTR], fence, None)
                if 'pool' in created:
                    call('vkDestroyCommandPool', None, [U64, PTR], pool, None)
                if 'buffer' in created:
                    call('vkDestroyBuffer', None, [U64, PTR], buffer, None)
                if 'memory' in created:
                    call('vkFreeMemory', None, [U64, PTR], memory, None)

    def import_image(self, buffer, width, height, record, image_format):
        image, memory = U64(), U64()
        image_created = memory_allocated = False
        try:
            props = Properties(sType=1000129001)
            check('vkGetAndroidHardwareBufferPropertiesANDROID', self.function(
                'vkGetAndroidHardwareBufferPropertiesANDROID', C.c_int, PTR, PTR, PTR,
                device=True)(self.device, buffer, C.byref(props)), record)
            record.update(allocation_size=props.allocationSize, memory_type_bits=props.memoryTypeBits)
            if not props.allocationSize or not props.memoryTypeBits:
                raise ProbeError('AHB properties returned no allocation or memory types')
            external = ExternalImage(sType=1000072001, handleTypes=0x400)
            info = ImageInfo(sType=14, pNext=address(external), imageType=1,
                format=image_format, extent=Extent(width, height, 1), mipLevels=1, arrayLayers=1,
                samples=1, tiling=0, usage=0x10 | 0x4 | 0x2 | 0x1)
            check('vkCreateImage', self.function('vkCreateImage', C.c_int, PTR, PTR, PTR, PTR,
                device=True)(self.device, C.byref(info), None, C.byref(image)), record)
            image_created = True
            imported = ImportInfo(sType=1000129003, buffer=buffer)
            dedicated = DedicatedInfo(sType=1000127001, pNext=address(imported), image=image.value)
            info = AllocateInfo(sType=5, pNext=address(dedicated), allocationSize=props.allocationSize,
                memoryTypeIndex=(props.memoryTypeBits & -props.memoryTypeBits).bit_length() - 1)
            check('vkAllocateMemory.import', self.function('vkAllocateMemory', C.c_int,
                PTR, PTR, PTR, PTR, device=True)(self.device, C.byref(info), None, C.byref(memory)), record)
            memory_allocated = True
            check('vkBindImageMemory', self.function('vkBindImageMemory', C.c_int,
                PTR, U64, U64, U64, device=True)(self.device, image, memory, 0), record)
            record['import_bound'] = True
            self.readback(image, width, height, record.get('cpu_pattern_initialized', False), record)
        finally:
            if image_created and not self.in_flight:
                self.function('vkDestroyImage', None, PTR, U64, PTR, device=True)(self.device, image, None)
            if memory_allocated and not self.in_flight:
                self.function('vkFreeMemory', None, PTR, U64, PTR, device=True)(self.device, memory, None)


def probe(args, report):
    if sys.platform not in ('linux', 'android') or platform.machine() != 'aarch64' or C.sizeof(PTR) != 8:
        raise ProbeError('Run from 64-bit Android Termux on the Mali phone')
    android = C.CDLL('/system/lib64/libnativewindow.so')
    for name, types, result in (
        ('allocate', [PTR, PTR], C.c_int), ('describe', [PTR, PTR], None),
        ('lockPlanes', [PTR, U64, C.c_int32, PTR, PTR], C.c_int),
        ('unlock', [PTR, PTR], C.c_int), ('release', [PTR], None)):
        function = getattr(android, 'AHardwareBuffer_' + name)
        function.argtypes, function.restype = types, result
    vulkan = Vulkan(args.driver, report)
    try:
        vulkan.init()
        for cpu in (False, True):
            record = {'cpu_usable': cpu, 'import_bound': False, 'gpu_readback_verified': False}
            record['clear_rgba'] = {'red': [255, 0, 0, 255], 'green': [0, 255, 0, 255],
                                    'blue': [0, 0, 255, 255]}[args.clear]
            r, g, b, a = record['clear_rgba']
            record['storage_clear_bytes'] = [r, g, b, a] if args.format == 'rgba' else [b, g, r, a]
            report['cases'].append(record)
            buffer = PTR()
            allocated = False
            try:
                desc = Desc(width=args.width, height=args.height, layers=1,
                            format=1 if args.format == 'rgba' else 5,
                            usage=0x300 | (0x33 if cpu else 0))
                record['requested_usage'] = desc.usage
                check('AHardwareBuffer_allocate', android.AHardwareBuffer_allocate(
                    C.byref(desc), C.byref(buffer)), record)
                allocated = True
                if not buffer:
                    raise ProbeError('AHardwareBuffer_allocate returned a null buffer')
                android.AHardwareBuffer_describe(buffer, C.byref(desc))
                record['description'] = {name: getattr(desc, name) for name in
                    ('width', 'height', 'layers', 'format', 'usage', 'stride')}
                if cpu and not args.no_cpu_mapping:
                    planes = Planes()
                    result = android.AHardwareBuffer_lockPlanes(buffer, 0x33, -1, None, C.byref(planes))
                    record['lock_planes_result'] = result
                    if result == 0:
                        try:
                            if planes.planeCount > 4:
                                raise ProbeError('Invalid public plane count')
                            record['planes'] = [{'pixel_stride': p.pixelStride,
                                'row_stride': p.rowStride} for p in planes.planes[:planes.planeCount]]
                        finally:
                            check('AHardwareBuffer_unlock', android.AHardwareBuffer_unlock(buffer, None), record)
                    locked_pixels(android, buffer, args.width, args.height,
                                  write=pattern(args.width, args.height))
                    record['cpu_pattern_initialized'] = True
                vulkan.import_image(buffer, args.width, args.height, record,
                                    37 if args.format == 'rgba' else 44)
                if cpu and not args.no_cpu_mapping:
                    record['gpu_to_cpu_verified'] = locked_pixels(android, buffer, args.width,
                        args.height) == bytes(record['storage_clear_bytes']) * (args.width * args.height)
                    if not record['gpu_to_cpu_verified']:
                        raise ProbeError('GPU clear differs in public CPU mapping')
                record['import_readback_passed'] = True
                if args.present_display:
                    helper = Path(__file__).with_name('ahb-x11.py')
                    spec = importlib.util.spec_from_file_location('ahb_x11', helper)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.present(buffer, android, args.present_display, desc, record,
                        args.out.with_name(args.out.stem + ('-cpu' if cpu else '-gpu') + '.png'),
                        args.present_frames)
                if args.egl:
                    spec = importlib.util.spec_from_file_location('ahb_egl', Path(__file__).with_name('ahb-egl.py'))
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.sample(buffer, args.width, args.height, record)
            except (ProbeError, RuntimeError, OSError) as error:
                record['error'] = str(error)
            finally:
                if allocated and buffer and not vulkan.in_flight:
                    android.AHardwareBuffer_release(buffer)
            if vulkan.in_flight:
                raise ProbeError('GPU wait failed; leaving in-flight resources for process teardown')
    finally:
        vulkan.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--format', choices=('rgba', 'bgra'), default='rgba')
    parser.add_argument('--clear', choices=('red', 'green', 'blue'), default='green')
    parser.add_argument('--no-cpu-mapping', action='store_true',
                        help='Test GPU readback/EGL/Present only; do not claim CPU mapping validation')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--present-display', help='Private harness display; also test modifier 1255 and Present')
    parser.add_argument('--present-frames', type=int, default=180)
    parser.add_argument('--egl', action='store_true', help='Also sample the AHB with Android EGL/GLES offscreen')
    args = parser.parse_args()
    if not 1 <= args.width <= 4096 or not 1 <= args.height <= 4096:
        parser.error('Dimensions must be between 1 and 4096')
    if not 1 <= args.present_frames <= 1800:
        parser.error('present-frames must be between 1 and 1800')
    args.driver = args.driver.resolve(strict=True)
    report = {'driver': str(args.driver), 'driver_sha256': hashlib.sha256(args.driver.read_bytes()).hexdigest(),
              'cases': [], 'format': args.format, 'cpu_mapping_requested': not args.no_cpu_mapping,
              'present_display': args.present_display, 'android_egl_requested': args.egl,
              'scope': 'AHB import/readback; optional private X11 Present and offscreen Android EGL; no physical scanout'}
    with args.out.open('x') as output:
        try:
            probe(args, report)
        except Exception as error:
            report['error'] = str(error)
        report['qualified_usages'] = [case['requested_usage'] for case in report['cases']
            if case['gpu_readback_verified'] and 'error' not in case]
        report['import_gate_passed'] = any(case.get('import_readback_passed') for case in report['cases'])
        report['all_requested_checks_passed'] = bool(report['qualified_usages']) and 'error' not in report
        output.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['all_requested_checks_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
