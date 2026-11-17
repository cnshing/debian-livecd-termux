#!/data/data/com.termux/files/usr/bin/python
"""Check OpenCL through the installed ICD loader: a GPU platform, kernels checked exactly on the CPU,
and FFmpeg's OpenCL filters compared with its CPU filters.

  kernels   integer hash over 2^20 items, float SAXPY, a local-memory reduction with barriers
            and a 128x128 matrix product, each compared with Python's own result; a control
            compares one result with a deliberately wrong reference and must fail.
  ffmpeg    avgblur_opencl and unsharp_opencl on a generated picture against avgblur and unsharp
            on the CPU (PSNR), saved as PNG: open them.

--expect hardware (default) requires a GPU device (CL_DEVICE_TYPE_GPU naming Adreno/Turnip/Mali);
--expect none requires no platform (negative control: run with OCL_ICD_VENDORS=/nonexistent).
Usage: test-opencl.py --out NEW_DIRECTORY [--expect hardware|none]
"""
import argparse
import array
import ctypes
import json
import math
from pathlib import Path
import re
import subprocess
import sys

KERNELS = r'''
__kernel void hash(__global uint *h) { uint i = get_global_id(0); h[i] = (i * 2654435761u) ^ (i >> 3); }
__kernel void saxpy(float a, __global const float *x, __global float *y) { uint i = get_global_id(0); y[i] = a * x[i] + y[i]; }
__kernel void reduce(__global const uint *in, __global uint *out, __local uint *part) {
  uint l = get_local_id(0); part[l] = in[get_global_id(0)] & 1023u; barrier(CLK_LOCAL_MEM_FENCE);
  for (uint s = get_local_size(0) / 2; s > 0; s >>= 1) { if (l < s) part[l] += part[l + s]; barrier(CLK_LOCAL_MEM_FENCE); }
  if (l == 0) out[get_group_id(0)] = part[0]; }
__kernel void mm(__global const float *a, __global const float *b, __global float *c) {
  uint x = get_global_id(0), y = get_global_id(1); float s = 0;
  for (uint k = 0; k < 128; k++) s += a[y * 128 + k] * b[k * 128 + x];
  c[y * 128 + x] = s; }
'''


def kernels(cl):
    u, p, sz = ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t
    count = u()
    cl.clGetPlatformIDs(0, None, ctypes.byref(count))
    if not count.value:
        return {'platforms': 0}
    platforms = (p * count.value)()
    cl.clGetPlatformIDs(count, platforms, None)

    def text(fn, handle, key):
        buffer = ctypes.create_string_buffer(4096)
        fn(p(handle), u(key), sz(4096), buffer, None)
        return buffer.value.decode(errors='replace')
    result = {'platforms': count.value, 'devices': []}
    chosen = None
    for platform in platforms:
        n = u()
        if cl.clGetDeviceIDs(p(platform), ctypes.c_uint64(0xFFFFFFFF), 0, None, ctypes.byref(n)) or not n.value:
            continue
        devices = (p * n.value)()
        cl.clGetDeviceIDs(p(platform), ctypes.c_uint64(0xFFFFFFFF), n, devices, None)
        for device in devices:
            kind = ctypes.c_uint64()
            cl.clGetDeviceInfo(p(device), u(0x1000), sz(8), ctypes.byref(kind), None)
            record = {'platform': text(cl.clGetPlatformInfo, platform, 0x0902),
                      'name': text(cl.clGetDeviceInfo, device, 0x102B),
                      'version': text(cl.clGetDeviceInfo, device, 0x102F),
                      'c_version': text(cl.clGetDeviceInfo, device, 0x103D), 'gpu': bool(kind.value & 4)}
            result['devices'].append(record)
            if record['gpu'] and chosen is None:
                chosen = device
    if chosen is None:
        return result
    error = ctypes.c_int()
    cl.clCreateContext.restype = p
    cl.clCreateCommandQueue.restype = p
    cl.clCreateProgramWithSource.restype = p
    cl.clCreateKernel.restype = p
    cl.clCreateBuffer.restype = p
    device = (p * 1)(chosen)
    context = cl.clCreateContext(None, 1, device, None, None, ctypes.byref(error))
    queue = cl.clCreateCommandQueue(p(context), p(chosen), ctypes.c_uint64(0), ctypes.byref(error))
    source = ctypes.c_char_p(KERNELS.encode())
    program = cl.clCreateProgramWithSource(p(context), 1, ctypes.byref(source), None, ctypes.byref(error))
    built = cl.clBuildProgram(p(program), 1, device, None, None, None)
    if built:
        log = ctypes.create_string_buffer(65536)
        cl.clGetProgramBuildInfo(p(program), p(chosen), u(0x1183), sz(65536), log, None)
        result['build_error'] = log.value.decode(errors='replace')[:2000]
        return result

    def buffer(data=None, size=None):
        size = size or len(data) * data.itemsize
        flags = 1 | (32 if data is not None else 0)  # READ_WRITE | COPY_HOST_PTR
        host = (ctypes.c_char * size).from_buffer(data) if data is not None else None
        return cl.clCreateBuffer(p(context), ctypes.c_uint64(flags), sz(size), host, ctypes.byref(error))

    def run(name, args, global_size, local_size=None):
        kernel = cl.clCreateKernel(p(program), name.encode(), ctypes.byref(error))
        for index, (size, value) in enumerate(args):
            cl.clSetKernelArg(p(kernel), u(index), sz(size), value)
        dims = len(global_size)
        g = (sz * dims)(*global_size)
        l = (sz * dims)(*local_size) if local_size else None
        status = cl.clEnqueueNDRangeKernel(p(queue), p(kernel), u(dims), None, g, l, 0, None, None)
        assert status == 0, (name, status)

    def read(handle, data):
        cl.clEnqueueReadBuffer(p(queue), p(handle), u(1), sz(0), sz(len(data) * data.itemsize),
                               (ctypes.c_char * (len(data) * data.itemsize)).from_buffer(data), 0, None, None)
        return data
    ptr = lambda handle: (ctypes.sizeof(p), ctypes.byref(p(handle)))
    checks = {}
    n = 1 << 20
    h = buffer(size=n * 4)
    run('hash', [ptr(h)], [n])
    hashes = read(h, array.array('I', bytes(n * 4)))
    want = [((i * 2654435761) & 0xFFFFFFFF) ^ (i >> 3) for i in range(n)]
    checks['hash'] = {'bad': sum(a != b for a, b in zip(hashes, want))}
    checks['control_detects_error'] = sum(a != (b ^ 1) for a, b in zip(hashes[:1024], want)) > 0
    x = array.array('f', [(i % 97) * 0.25 for i in range(n)])
    y = array.array('f', [(i % 13) * 0.5 for i in range(n)])
    bx, by = buffer(x), buffer(y)
    run('saxpy', [(4, ctypes.byref(ctypes.c_float(1.5))), ptr(bx), ptr(by)], [n])
    out = read(by, array.array('f', bytes(n * 4)))
    checks['saxpy'] = {'bad': sum(out[i] != 1.5 * x[i] + y[i] for i in range(n))}
    sums = buffer(size=(n // 256) * 4)
    run('reduce', [ptr(h), ptr(sums), (256 * 4, None)], [n], [256])
    got = read(sums, array.array('I', bytes((n // 256) * 4)))
    checks['reduce'] = {'bad': sum(got[w] != sum(v & 1023 for v in want[w * 256:(w + 1) * 256]) for w in range(n // 256))}
    a = array.array('f', [((i * 37) % 17 - 8) / 8 for i in range(128 * 128)])
    b = array.array('f', [((i * 53) % 13 - 6) / 4 for i in range(128 * 128)])
    ba, bb, bc = buffer(a), buffer(b), buffer(size=128 * 128 * 4)
    run('mm', [ptr(ba), ptr(bb), ptr(bc)], [128, 128], [8, 8])
    c = read(bc, array.array('f', bytes(128 * 128 * 4)))
    worst = max(abs(c[y * 128 + x] - sum(a[y * 128 + k] * b[k * 128 + x] for k in range(128)))
                for y in range(0, 128, 3) for x in range(128))
    checks['matmul'] = {'worst': worst, 'bad': int(worst > 1e-3)}
    cl.clFinish(p(queue))
    result['checks'] = checks
    result['ok'] = checks['control_detects_error'] and all(
        v['bad'] == 0 for k, v in checks.items() if isinstance(v, dict))
    return result


def ffmpeg(out):
    source = ['-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=1,format=yuv420p', '-frames:v', '1']
    cases = {'avgblur': ('avgblur=sizeX=4:sizeY=4', 'avgblur_opencl=sizeX=4:sizeY=4'),
             'unsharp': ('unsharp=5:5:1.0:5:5:1.0', 'unsharp_opencl=lx=5:ly=5:la=1.0:cx=5:cy=5:ca=1.0')}
    results = {}
    for name, (cpu, gpu) in cases.items():
        files = {}
        for kind, chain in (('cpu', cpu), ('opencl', gpu)):
            files[kind] = out / f'{name}-{kind}.png'
            graph = chain if kind == 'cpu' else 'format=yuv420p,hwupload,' + chain + ',hwdownload,format=yuv420p'
            run = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y',
                                  *(['-init_hw_device', 'opencl=cl', '-filter_hw_device', 'cl'] if kind == 'opencl' else []),
                                  *source, '-vf', graph, str(files[kind])], capture_output=True, text=True, timeout=120)
            if run.returncode:
                results[name] = {'error': run.stderr[-800:]}
                break
        else:
            compare = subprocess.run(['ffmpeg', '-v', 'info', '-nostdin', '-i', str(files['cpu']), '-i', str(files['opencl']),
                                      '-lavfi', 'psnr', '-f', 'null', '-'], capture_output=True, text=True, timeout=120)
            match = re.search(r'average:(\S+)', compare.stderr)
            psnr = float('inf') if match and match.group(1) == 'inf' else float(match.group(1)) if match else 0
            results[name] = {'psnr': psnr if math.isfinite(psnr) else 'inf', 'ok': psnr >= 40}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--expect', choices=('hardware', 'none'), default='hardware')
    args = parser.parse_args()
    args.out.mkdir(parents=True)
    cl = ctypes.CDLL('libOpenCL.so.1')
    result = {'expect': args.expect, 'kernels': kernels(cl)}
    devices = result['kernels'].get('devices', [])
    gpu = [d for d in devices if d['gpu'] and re.search('adreno|turnip|mali', d['name'], re.I)]
    if args.expect == 'none':
        result['ok'] = not devices
    else:
        result['ffmpeg'] = ffmpeg(args.out)
        result['ok'] = bool(gpu) and result['kernels'].get('ok') is True and all(
            case.get('ok') for case in result['ffmpeg'].values())
    (args.out / 'result.json').write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps(result, indent=1))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
