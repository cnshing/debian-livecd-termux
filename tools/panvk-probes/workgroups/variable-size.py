#!/usr/bin/env python3
"""Exercise ARB_compute_variable_group_size through Zink in a private GL context."""
import argparse
import array
import ctypes as C
import hashlib
import json
import os
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--driver', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--large-workgroups', action='store_true')
    a = p.parse_args()
    driver = a.driver.resolve(strict=True)
    a.out = a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=False)
    prefix = Path(os.environ['PREFIX'])
    for name in ('MESA_GL_VERSION_OVERRIDE', 'MESA_GLSL_VERSION_OVERRIDE', 'LIBGL_ALWAYS_SOFTWARE'):
        os.environ.pop(name, None)
    icd = a.out / 'icd.json'
    icd.write_text(json.dumps({'file_format_version':'1.0.1','ICD':{
        'library_path':str(driver),'api_version':'1.3.363'}}))
    os.environ.update(VK_DRIVER_FILES=str(icd), VK_ICD_FILENAMES=str(icd),
        GALLIUM_DRIVER='zink', MESA_LOADER_DRIVER_OVERRIDE='zink', EGL_PLATFORM='surfaceless',
        PANVK_G77_LWG='1' if a.large_workgroups else '0', PANVK_G77_NESTED='0',
        XDG_CACHE_HOME=str(a.out/'cache'), MESA_SHADER_CACHE_DISABLE='false')
    egl = C.CDLL(str(prefix/'lib/libEGL.so.1'))
    def function(name, result, *args):
        f = getattr(egl, name)
        f.restype, f.argtypes = result, list(args)
        return f
    get_proc = function('eglGetProcAddress', C.c_void_p, C.c_char_p)
    def gl(name, result, *args):
        address = get_proc(name.encode())
        if not address:
            raise RuntimeError('Missing GL function '+name)
        return C.CFUNCTYPE(result, *args)(address)
    platform = C.CFUNCTYPE(C.c_void_p, C.c_uint, C.c_void_p, C.c_void_p)(get_proc(b'eglGetPlatformDisplayEXT'))
    display = platform(0x31DD, None, None)
    initialize = function('eglInitialize', C.c_uint, C.c_void_p, C.c_void_p, C.c_void_p)
    bind = function('eglBindAPI', C.c_uint, C.c_uint)
    choose = function('eglChooseConfig', C.c_uint, C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_void_p), C.c_int, C.POINTER(C.c_int))
    create = function('eglCreateContext', C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int))
    current = function('eglMakeCurrent', C.c_uint, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p)
    destroy = function('eglDestroyContext', C.c_uint, C.c_void_p, C.c_void_p)
    terminate = function('eglTerminate', C.c_uint, C.c_void_p)
    context = None
    result = {'driver':str(driver),'driver_sha256':hashlib.sha256(driver.read_bytes()).hexdigest(),
              'large_workgroups':a.large_workgroups,'cases':[],'ok':False}
    try:
        if not initialize(display,None,None) or not bind(0x30A2):
            raise RuntimeError('Cannot initialize desktop OpenGL EGL')
        attrs = (C.c_int*7)(0x3033,1,0x3040,8,0x3038,0,0)
        config, count = C.c_void_p(), C.c_int()
        if not choose(display,attrs,C.byref(config),1,C.byref(count)) or not count.value:
            raise RuntimeError('No OpenGL pbuffer EGL configuration')
        context = create(display,config,None,(C.c_int*7)(0x3098,4,0x30FB,3,0x30FD,1,0x3038))
        if not context:
            result['unsupported']='OpenGL 4.3 context unavailable'
            return 2
        if not current(display,None,None,context):
            raise RuntimeError('Cannot make private context current')
        get_string = gl('glGetString',C.c_char_p,C.c_uint)
        result['version'] = get_string(0x1F02).decode()
        result['renderer'] = get_string(0x1F01).decode()
        get_int = gl('glGetIntegerv',None,C.c_uint,C.POINTER(C.c_int))
        get_index_string = gl('glGetStringi',C.c_char_p,C.c_uint,C.c_uint)
        total = C.c_int(); get_int(0x821D,C.byref(total))
        extensions = {get_index_string(0x1F03,i).decode() for i in range(total.value)}
        if 'GL_ARB_compute_variable_group_size' not in extensions:
            result['unsupported']='ARB_compute_variable_group_size unavailable'
            return 2
        maps = Path('/proc/self/maps').read_text()
        if str(driver) not in maps or 'Mali' not in result['renderer'] or 'zink' not in result['renderer']:
            raise RuntimeError('Context did not load the requested Mali/Zink driver')
        result['libraries'] = sorted({line.split()[-1] for line in maps.splitlines()
            if any(x in line for x in ('panfrost','gallium','libEGL','libGLES'))})
        source = b'''#version 430
#extension GL_ARB_compute_variable_group_size : require
layout(local_size_variable) in;
layout(std430,binding=0) buffer Out { uint data[]; };
shared uint values[1024];
void main() {
 uint i=gl_LocalInvocationIndex;
 uint n=gl_LocalGroupSizeARB.x*gl_LocalGroupSizeARB.y*gl_LocalGroupSizeARB.z;
 uint g=gl_WorkGroupID.x+3u*gl_WorkGroupID.y;
 values[i]=i*3u+g*17u+1u;
 barrier();
 uint o=(g*n+i)*8u;
 data[o]=i; data[o+1u]=gl_LocalInvocationID.x;
 data[o+2u]=gl_LocalInvocationID.y; data[o+3u]=gl_LocalInvocationID.z;
 data[o+4u]=gl_LocalGroupSizeARB.x; data[o+5u]=gl_LocalGroupSizeARB.y;
 data[o+6u]=gl_LocalGroupSizeARB.z; data[o+7u]=values[n-1u-i];
}'''
        create_shader = gl('glCreateShader',C.c_uint,C.c_uint)
        shader = create_shader(0x91B9)
        strings=(C.c_char_p*1)(source)
        gl('glShaderSource',None,C.c_uint,C.c_int,C.POINTER(C.c_char_p),C.c_void_p)(shader,1,strings,None)
        gl('glCompileShader',None,C.c_uint)(shader)
        status=C.c_int(); gl('glGetShaderiv',None,C.c_uint,C.c_uint,C.POINTER(C.c_int))(shader,0x8B81,C.byref(status))
        if not status.value:
            log=C.create_string_buffer(8192)
            gl('glGetShaderInfoLog',None,C.c_uint,C.c_int,C.c_void_p,C.c_void_p)(shader,len(log),None,log)
            raise RuntimeError(log.value.decode())
        program=gl('glCreateProgram',C.c_uint)()
        gl('glAttachShader',None,C.c_uint,C.c_uint)(program,shader)
        gl('glLinkProgram',None,C.c_uint)(program)
        gl('glGetProgramiv',None,C.c_uint,C.c_uint,C.POINTER(C.c_int))(program,0x8B82,C.byref(status))
        if not status.value:
            raise RuntimeError('Compute program link failed')
        gl('glUseProgram',None,C.c_uint)(program)
        bind_buffer=gl('glBindBuffer',None,C.c_uint,C.c_uint)
        upload=gl('glBufferData',None,C.c_uint,C.c_ssize_t,C.c_void_p,C.c_uint)
        dispatch=gl('glDispatchComputeGroupSizeARB',None,*([C.c_uint]*6))
        barrier=gl('glMemoryBarrier',None,C.c_uint)
        finish=gl('glFinish',None)
        map_buffer=gl('glMapBufferRange',C.c_void_p,C.c_uint,C.c_ssize_t,C.c_ssize_t,C.c_uint)
        unmap=gl('glUnmapBuffer',C.c_ubyte,C.c_uint)
        get_error=gl('glGetError',C.c_uint)
        buffer=C.c_uint(); gl('glGenBuffers',None,C.c_int,C.POINTER(C.c_uint))(1,C.byref(buffer))
        bind_buffer(0x90D2,buffer)
        gl('glBindBufferBase',None,C.c_uint,C.c_uint,C.c_uint)(0x90D2,0,buffer)
        for x,y,z in ((512,1,1),(769,1,1),(1024,1,1),(17,19,3),(8,8,16)):
            n=x*y*z; words=n*6*8; size=words*4
            sentinel=(C.c_uint*words)(*([0xDEADBEEF]*words))
            upload(0x90D2,size,sentinel,0x88E9)
            dispatch(3,2,1,x,y,z); barrier(0x2200); finish()
            if get_error():
                raise RuntimeError('GL error after variable-size dispatch')
            address=map_buffer(0x90D2,0,size,1)
            if not address:
                raise RuntimeError('Cannot read result buffer')
            data=array.array('I'); data.frombytes(C.string_at(address,size)); unmap(0x90D2)
            for g in range(6):
                for i in range(n):
                    expected=[i,i%x,(i//x)%y,i//(x*y),x,y,z,(n-1-i)*3+g*17+1]
                    offset=(g*n+i)*8
                    if list(data[offset:offset+8]) != expected:
                        raise RuntimeError(f'Wrong variable-size output: shape={x,y,z} group={g} i={i}')
            result['cases'].append({'shape':[x,y,z],'words_checked':words,'ok':True})
            print('PASS variable size',x,y,z,words,'words',flush=True)
        result['ok']=True
        return 0
    except Exception as error:
        result['error']=repr(error)
        raise
    finally:
        if context:
            current(display,None,None,None); destroy(display,context)
        if display:
            terminate(display)
        (a.out/'results.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    raise SystemExit(main())
