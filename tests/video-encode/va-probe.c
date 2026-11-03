// Opens a VA-API display the way Linux applications do and prints, as JSON,
// how it was found and which encoders it offers.
//   va-probe PATH   open this DRM device, as `ffmpeg -vaapi_device PATH` does
//   va-probe scan   try /dev/dri/renderD128 to renderD135 in order, as
//                   GStreamer's va plugin, OBS and Chromium do, and use the
//                   first that initializes
// Build: clang -O2 -Wall va-probe.c -o va-probe $(pkg-config --cflags --libs libva-drm libdrm)
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <va/va.h>
#include <va/va_drm.h>
#include <xf86drm.h>

static const struct {
    VAProfile profile;
    const char *name;
} profiles[] = {
    {VAProfileH264ConstrainedBaseline, "h264-constrained-baseline"},
    {VAProfileH264Main, "h264-main"},
    {VAProfileH264High, "h264-high"},
    {VAProfileHEVCMain, "hevc-main"},
    {VAProfileVP9Profile0, "vp9-profile0"},
    {VAProfileAV1Profile0, "av1-main"},
};

static int open_device(const char *path, char *why, size_t size) {
    struct stat st;
    if (stat(path, &st) != 0) {
        snprintf(why, size, "stat: %s", strerror(errno));
        return -1;
    }
    if (!S_ISCHR(st.st_mode) || major(st.st_rdev) != 226 || minor(st.st_rdev) < 128) {
        snprintf(why, size, "not a DRM render node (%u:%u)", major(st.st_rdev), minor(st.st_rdev));
        return -1;
    }
    int fd = open(path, O_RDWR | O_CLOEXEC);
    if (fd < 0)
        snprintf(why, size, "open: %s", strerror(errno));
    return fd;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s PATH|scan\n", argv[0]);
        return 2;
    }
    char path[64], why[128] = "";
    int fd = -1;
    if (!strcmp(argv[1], "scan")) {
        for (int i = 128; i < 136 && fd < 0; i++) {
            snprintf(path, sizeof(path), "/dev/dri/renderD%d", i);
            fd = open_device(path, why, sizeof(why));
        }
    } else {
        snprintf(path, sizeof(path), "%s", argv[1]);
        // An explicit path need not be a render node: ffmpeg accepts any DRM fd.
        fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd < 0)
            snprintf(why, sizeof(why), "open: %s", strerror(errno));
    }
    if (fd < 0) {
        printf("{\"device\": null, \"error\": \"%s\"}\n", why);
        return 1;
    }
    drmVersionPtr version = drmGetVersion(fd);
    printf("{\"device\": \"%s\", \"drm_driver\": \"%s\", ", path, version ? version->name : "");
    drmFreeVersion(version);
    // libdrm's sysfs view, which Mesa's loader and Chromium consult.
    drmDevicePtr device = NULL;
    if (drmGetDevice2(fd, 0, &device) == 0) {
        printf("\"drm_bus\": \"%s\", \"drm_render_node\": \"%s\", \"drm_of_fullname\": \"%s\", ",
               device->bustype == DRM_BUS_PLATFORM ? "platform" : "other",
               device->available_nodes & (1 << DRM_NODE_RENDER) ? device->nodes[DRM_NODE_RENDER] : "",
               device->bustype == DRM_BUS_PLATFORM && device->businfo.platform
                   ? device->businfo.platform->fullname : "");
        drmFreeDevice(&device);
    } else {
        printf("\"drm_bus\": null, ");
    }
    VADisplay display = vaGetDisplayDRM(fd);
    int major_version, minor_version;
    if (!display || vaInitialize(display, &major_version, &minor_version) != VA_STATUS_SUCCESS) {
        printf("\"error\": \"vaInitialize failed\"}\n");
        return 1;
    }
    printf("\"vendor\": \"%s\", \"encoders\": {", vaQueryVendorString(display));
    const char *separator = "";
    for (size_t i = 0; i < sizeof(profiles) / sizeof(profiles[0]); i++) {
        VAEntrypoint entrypoints[16];
        int count = 0;
        if (vaQueryConfigEntrypoints(display, profiles[i].profile, entrypoints, &count) !=
            VA_STATUS_SUCCESS)
            continue;
        for (int e = 0; e < count; e++) {
            if (entrypoints[e] != VAEntrypointEncSlice && entrypoints[e] != VAEntrypointEncSliceLP)
                continue;
            VAConfigAttrib attributes[] = {
                {.type = VAConfigAttribRTFormat},       {.type = VAConfigAttribRateControl},
                {.type = VAConfigAttribEncPackedHeaders}, {.type = VAConfigAttribEncMaxRefFrames},
                {.type = VAConfigAttribMaxPictureWidth}, {.type = VAConfigAttribMaxPictureHeight},
            };
            vaGetConfigAttributes(display, profiles[i].profile, entrypoints[e], attributes, 6);
            printf("%s\"%s\": {\"low_power\": %s, \"nv12\": %s, \"cbr\": %s, \"vbr\": %s, "
                   "\"packed_headers\": %u, \"max_ref_frames\": %u, \"max_size\": [%u, %u]}",
                   separator, profiles[i].name,
                   entrypoints[e] == VAEntrypointEncSliceLP ? "true" : "false",
                   attributes[0].value & VA_RT_FORMAT_YUV420 ? "true" : "false",
                   attributes[1].value & VA_RC_CBR ? "true" : "false",
                   attributes[1].value & VA_RC_VBR ? "true" : "false", attributes[2].value,
                   attributes[3].value, attributes[4].value, attributes[5].value);
            separator = ", ";
        }
    }
    printf("}}\n");
    vaTerminate(display);
    close(fd);
    return 0;
}
