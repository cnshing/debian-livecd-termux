#!/usr/bin/env python3
"""Check persistent HOST_COHERENT writes to an imported public AHB BLOB."""
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('ahb_import', Path(__file__).with_name('ahb-import.py'))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
U32, U64, PTR = a.U32, a.U64, a.PTR
Copy = a.structure('VkBufferCopy', ('srcOffset', U64), ('dstOffset', U64), ('size', U64))


def run(args, report):
    android = C.CDLL('/system/lib64/libnativewindow.so')
    android.AHardwareBuffer_allocate.argtypes = [PTR, PTR]
    android.AHardwareBuffer_allocate.restype = C.c_int
    android.AHardwareBuffer_release.argtypes = [PTR]
    android.AHardwareBuffer_release.restype = None
    blob = PTR()
    vulkan = a.Vulkan(args.driver, report)
    buffers, memories, mappings = [], [], []
    pool, fence = U64(), U64()
    def call(name, result, arguments, *values):
        return vulkan.function(name, result, PTR, *arguments, device=True)(vulkan.device, *values)
    try:
        desc = a.Desc(width=args.bytes, height=1, layers=1, format=0x21, usage=0x1000033)
        a.check('AHardwareBuffer_allocate.BLOB', android.AHardwareBuffer_allocate(
            C.byref(desc), C.byref(blob)), report)
        if not blob:
            raise a.ProbeError('Null AHB BLOB')
        vulkan.init()
        props = a.Properties(sType=1000129001)
        a.check('vkGetAndroidHardwareBufferPropertiesANDROID', call(
            'vkGetAndroidHardwareBufferPropertiesANDROID', C.c_int, [PTR, PTR], blob, C.byref(props)), report)
        properties = a.MemoryProperties()
        vulkan.function('vkGetPhysicalDeviceMemoryProperties', None, PTR, PTR)(
            vulkan.physical, C.byref(properties))
        for imported in (True, False):
            external = a.ExternalImage(sType=1000072000, handleTypes=0x400)
            info = a.BufferInfo(sType=12, pNext=a.address(external) if imported else None,
                                size=args.bytes, usage=1 if imported else 2)
            buffer = U64()
            a.check('vkCreateBuffer', call('vkCreateBuffer', C.c_int, [PTR, PTR, PTR],
                C.byref(info), None, C.byref(buffer)), report)
            buffers.append(buffer)
            req = a.Requirements()
            call('vkGetBufferMemoryRequirements', None, [U64, PTR], buffer, C.byref(req))
            bits = req.memoryTypeBits & (props.memoryTypeBits if imported else 0xFFFFFFFF)
            memory_type = next((i for i in range(properties.memoryTypeCount) if
                bits & (1 << i) and properties.memoryTypes[i].propertyFlags & 6 == 6), None)
            if memory_type is None:
                raise a.ProbeError('No HOST_VISIBLE|HOST_COHERENT memory type')
            import_info = a.ImportInfo(sType=1000129003, buffer=blob)
            dedicated = a.DedicatedInfo(sType=1000127001,
                pNext=a.address(import_info) if imported else None, buffer=buffer.value)
            info = a.AllocateInfo(sType=5, pNext=a.address(dedicated),
                allocationSize=props.allocationSize if imported else req.size,
                memoryTypeIndex=memory_type)
            memory = U64()
            a.check('vkAllocateMemory.import' if imported else 'vkAllocateMemory.readback', call(
                'vkAllocateMemory', C.c_int, [PTR, PTR, PTR], C.byref(info), None, C.byref(memory)), report)
            memories.append(memory)
            a.check('vkBindBufferMemory', call('vkBindBufferMemory', C.c_int, [U64, U64, U64],
                buffer, memory, 0), report)
            pointer = PTR()
            a.check('vkMapMemory', call('vkMapMemory', C.c_int, [U64, U64, U64, U32, PTR],
                memory, 0, args.bytes, 0, C.byref(pointer)), report)
            mappings.append(pointer)
            report.setdefault('memory_types', []).append({'imported': imported, 'index': memory_type,
                'flags': properties.memoryTypes[memory_type].propertyFlags})
        info = a.PoolInfo(sType=39, queueFamilyIndex=vulkan.family)
        a.check('vkCreateCommandPool', call('vkCreateCommandPool', C.c_int, [PTR, PTR, PTR],
            C.byref(info), None, C.byref(pool)), report)
        command = PTR()
        info = a.CommandInfo(sType=40, commandPool=pool.value, commandBufferCount=1)
        a.check('vkAllocateCommandBuffers', call('vkAllocateCommandBuffers', C.c_int, [PTR, PTR],
            C.byref(info), C.byref(command)), report)
        begin = a.BeginInfo(sType=42)
        a.check('vkBeginCommandBuffer', vulkan.function('vkBeginCommandBuffer', C.c_int,
            PTR, PTR, device=True)(command, C.byref(begin)), report)
        barrier = vulkan.function('vkCmdPipelineBarrier', None, PTR, U32, U32, U32,
            U32, PTR, U32, PTR, U32, PTR, device=True)
        source = a.BufferBarrier(sType=44, srcAccessMask=0x4000, dstAccessMask=0x800,
            srcQueueFamilyIndex=0xFFFFFFFF, dstQueueFamilyIndex=0xFFFFFFFF,
            buffer=buffers[0].value, size=args.bytes)
        barrier(command, 0x4000, 0x1000, 0, 0, None, 1, C.byref(source), 0, None)
        region = Copy(size=args.bytes)
        vulkan.function('vkCmdCopyBuffer', None, PTR, U64, U64, U32, PTR, device=True)(
            command, buffers[0], buffers[1], 1, C.byref(region))
        destination = a.BufferBarrier(sType=44, srcAccessMask=0x1000, dstAccessMask=0x2000,
            srcQueueFamilyIndex=0xFFFFFFFF, dstQueueFamilyIndex=0xFFFFFFFF,
            buffer=buffers[1].value, size=args.bytes)
        barrier(command, 0x1000, 0x4000, 0, 0, None, 1, C.byref(destination), 0, None)
        a.check('vkEndCommandBuffer', vulkan.function('vkEndCommandBuffer', C.c_int,
            PTR, device=True)(command), report)
        info = a.FenceInfo(sType=8)
        a.check('vkCreateFence', call('vkCreateFence', C.c_int, [PTR, PTR, PTR],
            C.byref(info), None, C.byref(fence)), report)
        queue = PTR()
        call('vkGetDeviceQueue', None, [U32, U32, PTR], vulkan.family, 0, C.byref(queue))
        report['iterations'] = []
        for index in range(args.iterations):
            pattern = bytes((value + index * 37) & 255 for value in range(256)) * (args.bytes // 256)
            C.memmove(mappings[0], pattern, len(pattern))
            a.check('vkResetFences', call('vkResetFences', C.c_int, [U32, PTR],
                1, C.byref(fence)), report)
            submit = a.SubmitInfo(sType=4, commandBufferCount=1, pCommandBuffers=C.pointer(command))
            a.check('vkQueueSubmit', vulkan.function('vkQueueSubmit', C.c_int, PTR, U32, PTR,
                U64, device=True)(queue, 1, C.byref(submit), fence), report)
            vulkan.in_flight = True
            a.check('vkWaitForFences', call('vkWaitForFences', C.c_int, [U32, PTR, U32, U64],
                1, C.byref(fence), 1, 10_000_000_000), report)
            vulkan.in_flight = False
            actual = C.string_at(mappings[1], args.bytes)
            report['iterations'].append({'index': index, 'all_bytes_match': actual == pattern,
                'expected_sha256': hashlib.sha256(pattern).hexdigest(),
                'actual_sha256': hashlib.sha256(actual).hexdigest()})
            if actual != pattern:
                raise a.ProbeError('Persistent HOST_COHERENT CPU writes differ in GPU readback')
        report['passed'] = True
    finally:
        if vulkan.device_created and not vulkan.in_flight:
            for memory in memories[:len(mappings)]:
                call('vkUnmapMemory', None, [U64], memory)
            if fence:
                call('vkDestroyFence', None, [U64, PTR], fence, None)
            if pool:
                call('vkDestroyCommandPool', None, [U64, PTR], pool, None)
            for buffer in buffers:
                call('vkDestroyBuffer', None, [U64, PTR], buffer, None)
            for memory in memories:
                call('vkFreeMemory', None, [U64, PTR], memory, None)
        if blob and not vulkan.in_flight:
            android.AHardwareBuffer_release(blob)
        vulkan.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bytes', type=int, default=4 * 1024 * 1024)
    parser.add_argument('--iterations', type=int, default=8)
    args = parser.parse_args()
    if not 256 <= args.bytes <= 16 * 1024 * 1024 or args.bytes % 256:
        parser.error('bytes must be a multiple of 256 between 256 and 16777216')
    if not 2 <= args.iterations <= 64:
        parser.error('iterations must be between 2 and 64')
    args.driver = args.driver.resolve(strict=True)
    if args.out.exists():
        parser.error('Use a fresh output path')
    report = {'driver': str(args.driver), 'driver_sha256': hashlib.sha256(args.driver.read_bytes()).hexdigest(),
        'bytes_per_iteration': args.bytes, 'persistent_mapping': True, 'explicit_flush_calls': 0,
        'import_sync_env': os.environ.get('PANVK_KBASE_IMPORT_SYNC'),
        'passed': False}
    try:
        run(args, report)
    except (a.ProbeError, RuntimeError, OSError) as error:
        report['error'] = str(error)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'error': report.get('error')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
