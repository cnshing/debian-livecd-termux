"""Sample the Vulkan-produced AHB with Android's EGL/GLES driver offscreen."""
import ctypes as C

PTR, INT, U32 = C.c_void_p, C.c_int32, C.c_uint32


def sample(buffer, width, height, record):
    egl = C.CDLL('/system/lib64/libEGL.so')
    gl = C.CDLL('/system/lib64/libGLESv2.so')
    def fn(lib, name, result, *arguments):
        function = getattr(lib, name)
        function.argtypes, function.restype = arguments, result
        return function
    get_proc = fn(egl, 'eglGetProcAddress', PTR, C.c_char_p)
    def extension(name, result, *arguments):
        pointer = get_proc(name.encode())
        if not pointer:
            raise RuntimeError('Missing EGL/GL extension: ' + name)
        return C.CFUNCTYPE(result, *arguments)(pointer)
    display = fn(egl, 'eglGetDisplay', PTR, PTR)(None)
    major, minor = INT(), INT()
    if not fn(egl, 'eglInitialize', U32, PTR, PTR, PTR)(display, C.byref(major), C.byref(minor)):
        raise RuntimeError('Android eglInitialize failed')
    surface = context = image = None
    texture, program, shaders = U32(), 0, []
    try:
        attributes = (INT * 13)(0x3033, 1, 0x3040, 4, 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8, 0x3038)
        config, count = PTR(), INT()
        if not fn(egl, 'eglChooseConfig', U32, PTR, PTR, PTR, INT, PTR)(
                display, attributes, C.byref(config), 1, C.byref(count)) or count.value != 1:
            raise RuntimeError('No Android GLES2 pbuffer config')
        if not fn(egl, 'eglBindAPI', U32, U32)(0x30A0):
            raise RuntimeError('Could not bind GLES API')
        context = fn(egl, 'eglCreateContext', PTR, PTR, PTR, PTR, PTR)(
            display, config, None, (INT * 3)(0x3098, 2, 0x3038))
        surface = fn(egl, 'eglCreatePbufferSurface', PTR, PTR, PTR, PTR)(
            display, config, (INT * 5)(0x3057, width, 0x3056, height, 0x3038))
        if not context or not surface or not fn(egl, 'eglMakeCurrent', U32, PTR, PTR, PTR, PTR)(
                display, surface, surface, context):
            raise RuntimeError('Could not make the Android offscreen context current')
        text = fn(gl, 'glGetString', C.c_char_p, U32)
        record['android_egl'] = {'version': [major.value, minor.value],
            'gl_vendor': text(0x1F00).decode(), 'gl_renderer': text(0x1F01).decode(),
            'gl_version': text(0x1F02).decode(), 'offscreen': True}
        client = extension('eglGetNativeClientBufferANDROID', PTR, PTR)(buffer)
        image = extension('eglCreateImageKHR', PTR, PTR, PTR, U32, PTR, PTR)(
            display, None, 0x3140, client, (INT * 3)(0x30D2, 1, 0x3038))
        if not image:
            raise RuntimeError('EGL_NATIVE_BUFFER_ANDROID import failed')
        fn(gl, 'glGenTextures', None, INT, PTR)(1, C.byref(texture))
        fn(gl, 'glBindTexture', None, U32, U32)(0x0DE1, texture)
        for key, value in ((0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)):
            fn(gl, 'glTexParameteri', None, U32, U32, INT)(0x0DE1, key, value)
        extension('glEGLImageTargetTexture2DOES', None, U32, PTR)(0x0DE1, image)
        program = fn(gl, 'glCreateProgram', U32)()
        for kind, source in (
            (0x8B31, b'attribute vec2 p; varying vec2 uv; void main(){uv=(p+1.)*.5;gl_Position=vec4(p,0.,1.);}'),
            (0x8B30, b'precision mediump float; varying vec2 uv; uniform sampler2D tex; void main(){gl_FragColor=texture2D(tex,uv);}')):
            shader = fn(gl, 'glCreateShader', U32, U32)(kind)
            shaders.append(shader)
            string = C.c_char_p(source)
            fn(gl, 'glShaderSource', None, U32, INT, PTR, PTR)(shader, 1, C.byref(string), None)
            fn(gl, 'glCompileShader', None, U32)(shader)
            status = INT()
            fn(gl, 'glGetShaderiv', None, U32, U32, PTR)(shader, 0x8B81, C.byref(status))
            if not status.value:
                raise RuntimeError('Android GLES shader compile failed')
            fn(gl, 'glAttachShader', None, U32, U32)(program, shader)
        fn(gl, 'glLinkProgram', None, U32)(program)
        status = INT()
        fn(gl, 'glGetProgramiv', None, U32, U32, PTR)(program, 0x8B82, C.byref(status))
        if not status.value:
            raise RuntimeError('Android GLES program link failed')
        fn(gl, 'glUseProgram', None, U32)(program)
        location = fn(gl, 'glGetAttribLocation', INT, U32, C.c_char_p)(program, b'p')
        vertices = (C.c_float * 8)(-1, -1, 1, -1, -1, 1, 1, 1)
        fn(gl, 'glEnableVertexAttribArray', None, U32)(location)
        fn(gl, 'glVertexAttribPointer', None, U32, INT, U32, U32, INT, PTR)(location, 2, 0x1406, 0, 0, vertices)
        fn(gl, 'glViewport', None, INT, INT, INT, INT)(0, 0, width, height)
        fn(gl, 'glDrawArrays', None, U32, INT, INT)(5, 0, 4)
        pixels = (C.c_ubyte * (width * height * 4))()
        fn(gl, 'glReadPixels', None, INT, INT, INT, INT, U32, U32, PTR)(
            0, 0, width, height, 0x1908, 0x1401, pixels)
        error = fn(gl, 'glGetError', U32)()
        record['android_egl']['gl_error'] = error
        record['android_egl']['pixels_verified'] = bytes(pixels) == bytes((0, 255, 0, 255)) * (width * height)
        if error or not record['android_egl']['pixels_verified']:
            raise RuntimeError('Android EGL sample does not match the Vulkan GPU clear')
    finally:
        if context and surface:
            if program:
                fn(gl, 'glDeleteProgram', None, U32)(program)
            for shader in shaders:
                fn(gl, 'glDeleteShader', None, U32)(shader)
            if texture.value:
                fn(gl, 'glDeleteTextures', None, INT, PTR)(1, C.byref(texture))
            if image:
                extension('eglDestroyImageKHR', U32, PTR, PTR)(display, image)
            fn(egl, 'eglMakeCurrent', U32, PTR, PTR, PTR, PTR)(display, None, None, None)
        if surface:
            fn(egl, 'eglDestroySurface', U32, PTR, PTR)(display, surface)
        if context:
            fn(egl, 'eglDestroyContext', U32, PTR, PTR)(display, context)
        fn(egl, 'eglTerminate', U32, PTR)(display)
