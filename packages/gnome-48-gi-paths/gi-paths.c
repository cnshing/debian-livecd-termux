/* GNOME Shell 48's executable only uses these three legacy GI entry points.
 * Its bundled GJS uses GIRepository 2.0. Loading legacy GI 1.0 as well registers
 * two unrelated GTypes named GIRepository and crashes the process.
 *
 * Preserve path configuration through the environment consumed by GJS, and
 * supply an empty option group (the legacy introspection-dump developer option
 * is not supported). This adapter is linked only into the private executable;
 * it does not replace either system library or interpose on other programs.
 */
#include <glib.h>

static void prepend(const char *key, const char *path)
{
    const char *old = g_getenv(key);
    char *value = old ? g_strconcat(path, ":", old, NULL) : g_strdup(path);
    g_setenv(key, value, TRUE);
    g_free(value);
}

void g_irepository_prepend_search_path(const char *path)
{
    prepend("GI_TYPELIB_PATH", path);
}

void g_irepository_prepend_library_path(const char *path)
{
    /* Bionic reads LD_LIBRARY_PATH before main(). The controller already sets
     * the complete private library path before executing the Shell. */
    (void)path;
}

GOptionGroup *g_irepository_get_option_group(void)
{
    return g_option_group_new("introspection", "Introspection", "Introspection", NULL, NULL);
}
