#!/usr/bin/env python3
"""Check one-plane EGL-exported RGBA dma-buf colors without GTK or glFinish."""
import ctypes as C
import fcntl
import struct
import mmap
import os


def main():
    egl = C.CDLL('libEGL.so')
    egl.eglGetProcAddress.argtypes = [C.c_char_p]
    egl.eglGetProcAddress.restype = C.c_void_p

    def proc(name, result, *args):
        address = egl.eglGetProcAddress(name.encode())
        if not address:
            raise RuntimeError('missing ' + name)
        return C.CFUNCTYPE(result, *args)(address)

    ptr, integer, uint = C.c_void_p, C.c_int, C.c_uint
    ints = C.POINTER(integer)
    display = proc('eglGetPlatformDisplayEXT', ptr, uint, ptr, ints)(0x31dd, None, None)
    def check(value):
        if not value:
            raise RuntimeError('EGL/GL call failed')
        return value
    check(proc('eglInitialize', uint, ptr, ints, ints)(display, None, None))
    check(proc('eglBindAPI', uint, uint)(0x30a0))
    config = ptr()
    count = integer()
    attrs = (integer * 7)(0x3033, 1, 0x3040, 0x40, 0x3024, 8, 0x3038)
    check(proc('eglChooseConfig', uint, ptr, ints, C.POINTER(ptr), integer, ints)(display, attrs, C.byref(config), 1, C.byref(count)))
    if count.value != 1:
        raise RuntimeError('no GLES3 EGL config')
    ca = (integer * 3)(0x3098, 3, 0x3038)
    context = proc('eglCreateContext', ptr, ptr, ptr, ptr, ints)(display, config, None, ca)
    check(context)
    check(proc('eglMakeCurrent', uint, ptr, ptr, ptr, ptr)(display, None, None, context))
    renderer = proc('glGetString', C.c_char_p, uint)(0x1f01).decode()
    print('renderer=' + renderer, flush=True)
    if 'panvk' not in renderer.lower():
        raise RuntimeError('expected PanVK renderer')
    texture, fbo = uint(), uint()
    proc('glGenTextures', None, integer, C.POINTER(uint))(1, C.byref(texture))
    proc('glBindTexture', None, uint, uint)(0x0de1, texture)
    width = height = 512
    proc('glTexImage2D', None, uint, integer, integer, integer, integer, integer, uint, uint, ptr)(0x0de1, 0, 0x8058, width, height, 0, 0x1908, 0x1401, None)
    proc('glGenFramebuffers', None, integer, C.POINTER(uint))(1, C.byref(fbo))
    proc('glBindFramebuffer', None, uint, uint)(0x8d40, fbo)
    proc('glFramebufferTexture2D', None, uint, uint, uint, uint, integer)(0x8d40, 0x8ce0, 0x0de1, texture, 0)
    if proc('glCheckFramebufferStatus', uint, uint)(0x8d40) != 0x8cd5:
        raise RuntimeError('incomplete FBO')
    image_attrs = (integer * 3)(0x30bc, 0, 0x3038)
    create = proc('eglCreateImageKHR', ptr, ptr, ptr, uint, ptr, ints)
    destroy = proc('eglDestroyImageKHR', uint, ptr, ptr)
    query = proc('eglExportDMABUFImageQueryMESA', uint, ptr, ptr, ints, ints, C.POINTER(C.c_uint64))
    export = proc('eglExportDMABUFImageMESA', uint, ptr, ptr, ints, ints, ints)
    clear_color = proc('glClearColor', None, C.c_float, C.c_float, C.c_float, C.c_float)
    clear = proc('glClear', None, uint)
    for frame in range(30):
        rgb = ((frame * 37) % 256, (frame * 79) % 256, (frame * 113) % 256)
        clear_color(*(x / 255 for x in rgb), 1)
        clear(0x4000)
        image = create(display, context, 0x30b1, texture.value, image_attrs)
        check(image)
        fourcc, planes, modifier = integer(), integer(), C.c_uint64()
        check(query(display, image, C.byref(fourcc), C.byref(planes), C.byref(modifier)))
        if planes.value != 1 or modifier.value not in (0, 0x00ffffffffffffff):
            raise RuntimeError(f'expected one linear or implicit plane, got {planes.value} modifier={modifier.value:x}')
        if frame == 0: print(f'fourcc={fourcc.value:x} modifier={modifier.value:x}', flush=True)
        fd, stride, offset = integer(-1), integer(), integer()
        check(export(display, image, C.byref(fd), C.byref(stride), C.byref(offset)))
        if fd.value < 0:
            raise RuntimeError('export returned no dma-buf')
        try:
            fcntl.ioctl(fd.value, 0x40086200, struct.pack("Q", 1))
            with mmap.mmap(fd.value, offset.value + stride.value * height, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ) as data:
                if fourcc.value == 0x34325241:
                    pixel = bytes((*reversed(rgb), 255))
                elif fourcc.value == 0x34324241:
                    pixel = bytes((*rgb, 255))
                else:
                    raise RuntimeError(f'unsupported fourcc={fourcc.value:x}')
                for y in range(height):
                    row = data[offset.value + y * stride.value:offset.value + y * stride.value + width * 4]
                    if row != pixel * width:
                        raise RuntimeError(f'stale/incorrect dma-buf frame={frame} row={y} expected={pixel.hex()}')
        finally:
            fcntl.ioctl(fd.value, 0x40086200, struct.pack("Q", 5))
            os.close(fd.value)
            check(destroy(display, image))
    proc('glDeleteFramebuffers', None, integer, C.POINTER(uint))(1, C.byref(fbo))
    proc('glDeleteTextures', None, integer, C.POINTER(uint))(1, C.byref(texture))
    check(proc('eglMakeCurrent', uint, ptr, ptr, ptr, ptr)(display, None, None, None))
    check(proc('eglDestroyContext', uint, ptr, ptr)(display, context))
    check(proc('eglTerminate', uint, ptr)(display))
    print('PASS 30 exported dma-buf frames; all 7,864,320 pixels exact; no glFinish/glReadPixels', flush=True)


if __name__ == '__main__':
    main()
