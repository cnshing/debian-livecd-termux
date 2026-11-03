// Build and run in native Termux, after granting CAMERA to com.termux.api:
//   clang -O2 -Wall -o camcap camcap.c -lcamera2ndk -lmediandk
//   ./camcap [camera-id] [width] [height] [frames] [fps] [out-dir|-] [record|preview]
// Opens one camera through the NDK as the Termux UID and streams YUV_420_888.
// Reports open time, exposure-to-delivery latency, frame gaps, plane layout,
// and the per-frame cost of the copy a producer must make. Saves two frames as
// PPM for a visual check.
#include <camera/NdkCameraCaptureSession.h>
#include <camera/NdkCameraDevice.h>
#include <camera/NdkCameraManager.h>
#include <camera/NdkCameraMetadata.h>
#include <camera/NdkCaptureRequest.h>
#include <dlfcn.h>
#include <media/NdkImageReader.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

struct state {
    pthread_mutex_t lock;
    pthread_cond_t cond;
    int w, h, target, frames, error;
    int realtime_ts;
    int64_t t_open, t_first, first_ts, last_ts, frame_ns;
    int64_t lat_sum, lat_min, lat_max, gap_max;
    int late_gaps;
    int64_t native_ns, yuyv_ns;
    int64_t exposure_sum;
    int results, pipeline_depth;
    uint8_t *native, *yuyv;
    const char *outdir;
};

static int64_t now_ns(clockid_t c) {
    struct timespec ts;
    clock_gettime(c, &ts);
    return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static double cpu_s(void) {
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
    return ru.ru_utime.tv_sec + ru.ru_stime.tv_sec + (ru.ru_utime.tv_usec + ru.ru_stime.tv_usec) / 1e6;
}

struct planes {
    uint8_t *p[3];
    int len[3], row[3], pix[3];
};

static void get_planes(AImage *img, struct planes *pl) {
    for (int i = 0; i < 3; i++) {
        AImage_getPlaneData(img, i, &pl->p[i], &pl->len[i]);
        AImage_getPlaneRowStride(img, i, &pl->row[i]);
        AImage_getPlanePixelStride(img, i, &pl->pix[i]);
    }
}

// Copy in the camera's own layout: Y rows, then the interleaved chroma rows.
// This is the one copy into a shared buffer when consumers accept NV12/NV21.
static void copy_native(const struct planes *pl, uint8_t *dst, int w, int h) {
    for (int r = 0; r < h; r++)
        memcpy(dst + r * w, pl->p[0] + r * pl->row[0], w);
    const uint8_t *c = pl->p[1] < pl->p[2] ? pl->p[1] : pl->p[2];
    for (int r = 0; r < h / 2; r++)
        memcpy(dst + w * h + r * w, c + r * pl->row[1], w);
}

// Convert to packed YUYV, the format most V4L2 programs accept.
static void to_yuyv(const struct planes *pl, uint8_t *dst, int w, int h) {
    for (int r = 0; r < h; r++) {
        const uint8_t *y = pl->p[0] + r * pl->row[0];
        const uint8_t *u = pl->p[1] + (r / 2) * pl->row[1];
        const uint8_t *v = pl->p[2] + (r / 2) * pl->row[2];
        uint8_t *o = dst + r * w * 2;
        for (int c = 0; c < w / 2; c++) {
            o[4 * c] = y[2 * c];
            o[4 * c + 1] = u[c * pl->pix[1]];
            o[4 * c + 2] = y[2 * c + 1];
            o[4 * c + 3] = v[c * pl->pix[2]];
        }
    }
}

static uint8_t clamp(int v) { return v < 0 ? 0 : v > 255 ? 255 : v; }

// JFIF full-range BT.601, which Android uses for camera YUV_420_888.
static void save_ppm(const struct state *s, const struct planes *pl, int n) {
    char path[512];
    snprintf(path, sizeof path, "%s/frame-%03d.ppm", s->outdir, n);
    FILE *f = fopen(path, "wb");
    if (!f) return;
    fprintf(f, "P6\n%d %d\n255\n", s->w, s->h);
    uint8_t *row = malloc(s->w * 3);
    for (int r = 0; r < s->h; r++) {
        for (int c = 0; c < s->w; c++) {
            int Y = pl->p[0][r * pl->row[0] + c];
            int U = pl->p[1][(r / 2) * pl->row[1] + (c / 2) * pl->pix[1]] - 128;
            int V = pl->p[2][(r / 2) * pl->row[2] + (c / 2) * pl->pix[2]] - 128;
            row[3 * c] = clamp(Y + (91881 * V >> 16));
            row[3 * c + 1] = clamp(Y - ((22554 * U + 46802 * V) >> 16));
            row[3 * c + 2] = clamp(Y + (116130 * U >> 16));
        }
        fwrite(row, 1, s->w * 3, f);
    }
    free(row);
    fclose(f);
}

static void on_image(void *ctx, AImageReader *reader) {
    struct state *s = ctx;
    AImage *img = NULL;
    if (AImageReader_acquireLatestImage(reader, &img) != AMEDIA_OK || !img)
        return;
    int64_t now = now_ns(CLOCK_BOOTTIME), ts = 0;
    AImage_getTimestamp(img, &ts);
    pthread_mutex_lock(&s->lock);
    int n = s->frames;
    pthread_mutex_unlock(&s->lock);
    if (n >= s->target) {
        AImage_delete(img);
        return;
    }
    struct planes pl;
    get_planes(img, &pl);
    if (n == 0) {
        s->t_first = now_ns(CLOCK_MONOTONIC);
        s->first_ts = ts;
        const char *layout = pl.pix[1] == 1 ? "planar (I420-like)"
                             : pl.p[2] == pl.p[1] + 1 ? "semi-planar NV12 (U first)"
                             : pl.p[1] == pl.p[2] + 1 ? "semi-planar NV21 (V first)"
                                                      : "semi-planar, separate";
        printf("planes: Y row=%d | U row=%d pix=%d | V row=%d pix=%d | %s\n", pl.row[0], pl.row[1], pl.pix[1],
               pl.row[2], pl.pix[2], layout);
    } else {
        int64_t gap = ts - s->last_ts;
        if (gap > s->gap_max) s->gap_max = gap;
        if (gap > s->frame_ns * 3 / 2) s->late_gaps++;
    }
    s->last_ts = ts;
    if (s->realtime_ts) {
        int64_t lat = now - ts;
        s->lat_sum += lat;
        if (n == 0 || lat < s->lat_min) s->lat_min = lat;
        if (lat > s->lat_max) s->lat_max = lat;
    }
    int64_t c0 = now_ns(CLOCK_MONOTONIC);
    copy_native(&pl, s->native, s->w, s->h);
    int64_t c1 = now_ns(CLOCK_MONOTONIC);
    to_yuyv(&pl, s->yuyv, s->w, s->h);
    s->native_ns += c1 - c0;
    s->yuyv_ns += now_ns(CLOCK_MONOTONIC) - c1;
    if (s->outdir && (n == 30 || n == s->target - 1))
        save_ppm(s, &pl, n);
    AImage_delete(img);
    pthread_mutex_lock(&s->lock);
    s->frames++;
    pthread_cond_signal(&s->cond);
    pthread_mutex_unlock(&s->lock);
}

static void on_disconnected(void *ctx, ACameraDevice *dev) {
    struct state *s = ctx;
    printf("device disconnected\n");
    pthread_mutex_lock(&s->lock);
    s->error = -1;
    pthread_cond_signal(&s->cond);
    pthread_mutex_unlock(&s->lock);
}

static void on_error(void *ctx, ACameraDevice *dev, int err) {
    struct state *s = ctx;
    printf("device error %d\n", err);
    pthread_mutex_lock(&s->lock);
    s->error = err ? err : -2;
    pthread_cond_signal(&s->cond);
    pthread_mutex_unlock(&s->lock);
}

static void on_session(void *ctx, ACameraCaptureSession *session) {}

// Capture results carry each frame's exposure time and the HAL's pipeline depth.
static void on_result(void *ctx, ACameraCaptureSession *session, ACaptureRequest *req, const ACameraMetadata *md) {
    struct state *s = ctx;
    ACameraMetadata_const_entry e;
    pthread_mutex_lock(&s->lock);
    if (ACameraMetadata_getConstEntry(md, ACAMERA_SENSOR_EXPOSURE_TIME, &e) == ACAMERA_OK) {
        s->exposure_sum += e.data.i64[0];
        s->results++;
    }
    if (ACameraMetadata_getConstEntry(md, ACAMERA_REQUEST_PIPELINE_DEPTH, &e) == ACAMERA_OK)
        s->pipeline_depth = e.data.u8[0];
    pthread_mutex_unlock(&s->lock);
}

// The image reader's buffer queue lives in this process, and the camera
// service calls into it over Binder. App processes get a Binder thread pool
// from the runtime; a plain executable must start one or the stream stalls.
// libbinder_ndk is a public library, but binder_process.h is not in the app NDK.
static int start_binder_pool(void) {
    void *lib = dlopen("libbinder_ndk.so", RTLD_NOW);
    if (!lib) return -1;
    bool (*set_max)(uint32_t) = (bool (*)(uint32_t))dlsym(lib, "ABinderProcess_setThreadPoolMaxThreadCount");
    void (*start)(void) = (void (*)(void))dlsym(lib, "ABinderProcess_startThreadPool");
    if (!set_max || !start) return -1;
    set_max(4);
    start();
    return 0;
}

#define CHECK(call)                                                   \
    do {                                                              \
        int _r = (call);                                              \
        if (_r != 0) {                                                \
            printf("%s failed: %d\n", #call, _r);                     \
            return 1;                                                 \
        }                                                             \
    } while (0)

int main(int argc, char **argv) {
    const char *id = argc > 1 ? argv[1] : "0";
    if (!getenv("CAMCAP_NO_BINDER_POOL") && start_binder_pool())
        printf("could not start a Binder thread pool\n");
    struct state s = {.lock = PTHREAD_MUTEX_INITIALIZER, .cond = PTHREAD_COND_INITIALIZER};
    s.w = argc > 2 ? atoi(argv[2]) : 1280;
    s.h = argc > 3 ? atoi(argv[3]) : 720;
    s.target = argc > 4 ? atoi(argv[4]) : 300;
    int fps = argc > 5 ? atoi(argv[5]) : 30;
    s.outdir = argc > 6 && strcmp(argv[6], "-") ? argv[6] : NULL;
    bool preview = argc > 7 && !strcmp(argv[7], "preview");
    s.frame_ns = 1000000000LL / fps;
    s.native = malloc(s.w * s.h * 3 / 2);
    s.yuyv = malloc(s.w * s.h * 2);

    ACameraManager *mgr = ACameraManager_create();
    ACameraMetadata *md = NULL;
    CHECK(ACameraManager_getCameraCharacteristics(mgr, id, &md));
    ACameraMetadata_const_entry e;
    if (ACameraMetadata_getConstEntry(md, ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE, &e) == ACAMERA_OK)
        s.realtime_ts = e.data.u8[0] == ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME;
    int orientation = -1;
    if (ACameraMetadata_getConstEntry(md, ACAMERA_SENSOR_ORIENTATION, &e) == ACAMERA_OK)
        orientation = e.data.i32[0];
    printf("camera %s: %dx%d @ %d fps, sensor orientation %d, timestamps %s\n", id, s.w, s.h, fps, orientation,
           s.realtime_ts ? "realtime (CLOCK_BOOTTIME)" : "unknown base");
    ACameraMetadata_free(md);

    ACameraDevice *dev = NULL;
    ACameraDevice_StateCallbacks dcb = {.context = &s, .onDisconnected = on_disconnected, .onError = on_error};
    s.t_open = now_ns(CLOCK_MONOTONIC);
    CHECK(ACameraManager_openCamera(mgr, id, &dcb, &dev));

    AImageReader *reader = NULL;
    CHECK(AImageReader_new(s.w, s.h, AIMAGE_FORMAT_YUV_420_888, 4, &reader));
    AImageReader_ImageListener listener = {.context = &s, .onImageAvailable = on_image};
    CHECK(AImageReader_setImageListener(reader, &listener));
    ANativeWindow *win = NULL;
    CHECK(AImageReader_getWindow(reader, &win));

    ACaptureSessionOutputContainer *outputs = NULL;
    ACaptureSessionOutput *output = NULL;
    ACameraOutputTarget *target = NULL;
    ACaptureRequest *req = NULL;
    ACameraCaptureSession *session = NULL;
    CHECK(ACaptureSessionOutputContainer_create(&outputs));
    CHECK(ACaptureSessionOutput_create(win, &output));
    CHECK(ACaptureSessionOutputContainer_add(outputs, output));
    CHECK(ACameraOutputTarget_create(win, &target));
    CHECK(ACameraDevice_createCaptureRequest(dev, preview ? TEMPLATE_PREVIEW : TEMPLATE_RECORD, &req));
    printf("template %s\n", preview ? "PREVIEW" : "RECORD");
    if (getenv("CAMCAP_NO_PROCESSING")) {
        uint8_t off = 0;  // NOISE_REDUCTION_MODE_OFF, EDGE_MODE_OFF, VIDEO_STABILIZATION_MODE_OFF
        ACaptureRequest_setEntry_u8(req, ACAMERA_NOISE_REDUCTION_MODE, 1, &off);
        ACaptureRequest_setEntry_u8(req, ACAMERA_EDGE_MODE, 1, &off);
        ACaptureRequest_setEntry_u8(req, ACAMERA_CONTROL_VIDEO_STABILIZATION_MODE, 1, &off);
        printf("noise reduction, edge enhancement and stabilization off\n");
    }
    CHECK(ACaptureRequest_addTarget(req, target));
    int32_t range[2] = {fps, fps};
    CHECK(ACaptureRequest_setEntry_i32(req, ACAMERA_CONTROL_AE_TARGET_FPS_RANGE, 2, range));
    ACameraCaptureSession_stateCallbacks scb = {
        .context = &s, .onClosed = on_session, .onReady = on_session, .onActive = on_session};
    CHECK(ACameraDevice_createCaptureSession(dev, outputs, &scb, &session));

    double cpu0 = cpu_s();
    int64_t wall0 = now_ns(CLOCK_MONOTONIC);
    ACameraCaptureSession_captureCallbacks ccb = {.context = &s, .onCaptureCompleted = on_result};
    CHECK(ACameraCaptureSession_setRepeatingRequest(session, &ccb, 1, &req, NULL));

    struct timespec deadline;
    clock_gettime(CLOCK_REALTIME, &deadline);
    deadline.tv_sec += s.target / fps + 10;
    pthread_mutex_lock(&s.lock);
    while (s.frames < s.target && !s.error)
        if (pthread_cond_timedwait(&s.cond, &s.lock, &deadline)) break;
    int got = s.frames;
    pthread_mutex_unlock(&s.lock);
    double cpu = cpu_s() - cpu0;
    double wall = (now_ns(CLOCK_MONOTONIC) - wall0) / 1e9;

    ACameraCaptureSession_stopRepeating(session);
    ACameraCaptureSession_close(session);
    ACameraDevice_close(dev);
    ACaptureRequest_free(req);
    ACameraOutputTarget_free(target);
    ACaptureSessionOutput_free(output);
    ACaptureSessionOutputContainer_free(outputs);
    AImageReader_delete(reader);
    ACameraManager_delete(mgr);

    printf("frames: %d of %d, error %d\n", got, s.target, s.error);
    if (got < 2) return 2;
    printf("open to first frame: %.0f ms\n", (s.t_first - s.t_open) / 1e6);
    printf("delivered rate: %.1f fps by sensor timestamps; largest gap %.1f ms; gaps over 1.5 frames: %d\n",
           (got - 1) / ((s.last_ts - s.first_ts) / 1e9), s.gap_max / 1e6, s.late_gaps);
    if (s.realtime_ts)
        printf("exposure start to delivery: avg %.1f ms, min %.1f, max %.1f\n", s.lat_sum / 1e6 / got,
               s.lat_min / 1e6, s.lat_max / 1e6);
    if (s.results)
        printf("exposure time: avg %.1f ms; HAL pipeline depth %d frames\n", s.exposure_sum / 1e6 / s.results,
               s.pipeline_depth);
    printf("per frame: native-layout copy %.2f ms, YUYV conversion %.2f ms\n", s.native_ns / 1e6 / got,
           s.yuyv_ns / 1e6 / got);
    printf("this process CPU: %.1f%% of one core (includes both copies)\n", 100 * cpu / wall);
    return 0;
}
