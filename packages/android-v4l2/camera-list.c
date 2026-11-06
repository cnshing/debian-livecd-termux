// Enumerate Android camera characteristics without opening any camera.
#include <camera/NdkCameraManager.h>
#include <camera/NdkCameraMetadata.h>
#include <media/NdkImage.h>
#include <stdio.h>

static void json_string(const char *s) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

int main(void) {
    ACameraManager *manager = ACameraManager_create();
    ACameraIdList *ids = NULL;
    int status = ACameraManager_getCameraIdList(manager, &ids);
    if (status != ACAMERA_OK) {
        fprintf(stderr, "Cannot enumerate Android cameras: %d\n", status);
        ACameraManager_delete(manager);
        return 1;
    }
    putchar('[');
    int count = 0;
    for (int i = 0; i < ids->numCameras; i++) {
        ACameraMetadata *metadata = NULL;
        if (ACameraManager_getCameraCharacteristics(manager, ids->cameraIds[i], &metadata) != ACAMERA_OK)
            continue;
        ACameraMetadata_const_entry entry;
        const char *facing = "unknown";
        if (ACameraMetadata_getConstEntry(metadata, ACAMERA_LENS_FACING, &entry) == ACAMERA_OK && entry.count) {
            switch (entry.data.u8[0]) {
            case ACAMERA_LENS_FACING_FRONT: facing = "front"; break;
            case ACAMERA_LENS_FACING_BACK: facing = "rear"; break;
            case ACAMERA_LENS_FACING_EXTERNAL: facing = "external"; break;
            }
        }
        if (count++) putchar(',');
        printf("{\"id\":"); json_string(ids->cameraIds[i]);
        printf(",\"facing\":"); json_string(facing);
        printf(",\"sizes\":[");
        int sizes = 0;
        if (ACameraMetadata_getConstEntry(metadata, ACAMERA_SCALER_AVAILABLE_STREAM_CONFIGURATIONS,
                                        &entry) == ACAMERA_OK) {
            for (uint32_t k = 0; k + 3 < entry.count; k += 4) {
                const int32_t *v = entry.data.i32 + k;
                if (v[0] != AIMAGE_FORMAT_YUV_420_888 ||
                    v[3] != ACAMERA_SCALER_AVAILABLE_STREAM_CONFIGURATIONS_OUTPUT ||
                    v[1] <= 0 || v[2] <= 0 || (v[1] & 1) || (v[2] & 1)) continue;
                printf("%s[%d,%d]", sizes++ ? "," : "", v[1], v[2]);
            }
        }
        printf("],\"fps_ranges\":[");
        int ranges = 0;
        if (ACameraMetadata_getConstEntry(metadata, ACAMERA_CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES,
                                        &entry) == ACAMERA_OK) {
            for (uint32_t k = 0; k + 1 < entry.count; k += 2)
                printf("%s[%d,%d]", ranges++ ? "," : "", entry.data.i32[k], entry.data.i32[k + 1]);
        }
        printf("]}");
        ACameraMetadata_free(metadata);
    }
    puts("]");
    ACameraManager_deleteCameraIdList(ids);
    ACameraManager_delete(manager);
    return 0;
}
