// Build and run in native Termux:
//   clang -O2 -Wall -o camlist camlist.c -lcamera2ndk -lmediandk && ./camlist
// List cameras through the NDK from a native Termux process.
// Reads characteristics only; never calls ACameraManager_openCamera.
#include <camera/NdkCameraManager.h>
#include <camera/NdkCameraMetadata.h>
#include <media/NdkImage.h>
#include <stdio.h>

static const char *facing_name(uint8_t f) {
    switch (f) {
    case ACAMERA_LENS_FACING_FRONT: return "front";
    case ACAMERA_LENS_FACING_BACK: return "back";
    case ACAMERA_LENS_FACING_EXTERNAL: return "external";
    default: return "?";
    }
}

static const char *level_name(uint8_t l) {
    switch (l) {
    case ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED: return "LIMITED";
    case ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL_FULL: return "FULL";
    case ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY: return "LEGACY";
    case ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL_3: return "LEVEL_3";
    case ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL: return "EXTERNAL";
    default: return "?";
    }
}

int main(void) {
    ACameraManager *mgr = ACameraManager_create();
    ACameraIdList *ids = NULL;
    camera_status_t st = ACameraManager_getCameraIdList(mgr, &ids);
    if (st != ACAMERA_OK) {
        printf("getCameraIdList failed: %d\n", st);
        return 1;
    }
    printf("cameras visible to this process: %d\n", ids->numCameras);
    for (int i = 0; i < ids->numCameras; i++) {
        const char *id = ids->cameraIds[i];
        ACameraMetadata *md = NULL;
        st = ACameraManager_getCameraCharacteristics(mgr, id, &md);
        if (st != ACAMERA_OK) {
            printf("id %s: characteristics failed: %d\n", id, st);
            continue;
        }
        ACameraMetadata_const_entry e;
        const char *facing = "?", *level = "?";
        if (ACameraMetadata_getConstEntry(md, ACAMERA_LENS_FACING, &e) == ACAMERA_OK)
            facing = facing_name(e.data.u8[0]);
        if (ACameraMetadata_getConstEntry(md, ACAMERA_INFO_SUPPORTED_HARDWARE_LEVEL, &e) == ACAMERA_OK)
            level = level_name(e.data.u8[0]);
        printf("id %s: facing=%s level=%s\n", id, facing, level);

        if (ACameraMetadata_getConstEntry(md, ACAMERA_SCALER_AVAILABLE_STREAM_CONFIGURATIONS, &e) == ACAMERA_OK) {
            printf("  YUV_420_888 outputs:");
            int n = 0;
            for (uint32_t k = 0; k + 3 < e.count; k += 4) {
                const int32_t *c = &e.data.i32[k];
                if (c[0] == AIMAGE_FORMAT_YUV_420_888 && c[3] == ACAMERA_SCALER_AVAILABLE_STREAM_CONFIGURATIONS_OUTPUT &&
                    c[1] <= 1920 && n++ < 8)
                    printf(" %dx%d", c[1], c[2]);
            }
            printf("\n");
        }
        if (ACameraMetadata_getConstEntry(md, ACAMERA_CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES, &e) == ACAMERA_OK) {
            printf("  AE fps ranges:");
            for (uint32_t k = 0; k + 1 < e.count; k += 2)
                printf(" [%d,%d]", e.data.i32[k], e.data.i32[k + 1]);
            printf("\n");
        }
        ACameraMetadata_free(md);
    }
    ACameraManager_deleteCameraIdList(ids);
    ACameraManager_delete(mgr);
    return 0;
}
