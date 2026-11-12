/* The glibc PanVK ICD links libSPIRV-Tools.so for one function: Mesa's
 * spirv_print_asm(), which only runs with MESA_SPIRV_DEBUG=asm to disassemble
 * shaders for debugging. Debian and Ubuntu ship SPIRV-Tools only as static
 * archives, so this provides those five symbols and reports that disassembly is
 * unavailable. Mesa then prints "Failed to disassemble SPIR-V" and carries on.
 * Built with -nostdlib: nothing here calls into the C library.
 */
typedef int spv_result_t;
enum { SPV_UNSUPPORTED = -2 };

__attribute__((visibility("default"))) void *spvContextCreate(int env)
{
   (void)env;
   return 0;
}

__attribute__((visibility("default"))) spv_result_t
spvBinaryToText(const void *context, const unsigned *binary, unsigned long word_count,
                unsigned options, void **text, void **diagnostic)
{
   (void)context, (void)binary, (void)word_count, (void)options;
   if (text)
      *text = 0;
   if (diagnostic)
      *diagnostic = 0;
   return SPV_UNSUPPORTED;
}

__attribute__((visibility("default"))) spv_result_t spvDiagnosticPrint(const void *diagnostic)
{
   (void)diagnostic;
   return SPV_UNSUPPORTED;
}

__attribute__((visibility("default"))) void spvDiagnosticDestroy(void *diagnostic)
{
   (void)diagnostic;
}

__attribute__((visibility("default"))) void spvTextDestroy(void *text)
{
   (void)text;
}
