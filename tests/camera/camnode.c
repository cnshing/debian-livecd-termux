// Prototype: publish one Android camera as a PipeWire camera node.
// Build and run in native Termux, after granting CAMERA to com.termux.api:
//   clang -O2 -Wall -o camnode camnode.c $(pkg-config --cflags --libs libpipewire-0.3) -lcamera2ndk -lmediandk
//   ./camnode [camera-id] [width] [height] [fps] [seconds] [--device=N] [--stamp]
// The node has media.class=Video/Source and media.role=Camera, and claims
// /dev/videoN (default 0) with object.path=v4l2:/dev/videoN, which the patched
// pw-v4l2 honors (pw-v4l2-device-path.patch). It publishes that device for
// livecd-v4l2.c's preload as files under $LIVECD_V4L2_DIR (default
// $XDG_RUNTIME_DIR/livecd-v4l2) and removes them on exit. The Android camera
// opens while a consumer streams from the node and closes 2 s after the last
// one stops. Frames are copied once, from the image reader into the
// negotiated PipeWire buffer. --stamp writes the sensor timestamp
// (CLOCK_BOOTTIME ns) over the first 8 bytes of each frame so a consumer can
// measure end-to-end latency.
#include <camera/NdkCameraCaptureSession.h>
#include <camera/NdkCameraDevice.h>
#include <camera/NdkCameraManager.h>
#include <camera/NdkCaptureRequest.h>
#include <dlfcn.h>
#include <media/NdkImageReader.h>
#include <pipewire/pipewire.h>
#include <pthread.h>
#include <signal.h>
#include <spa/debug/types.h>
#include <spa/param/video/format-utils.h>
#include <spa/param/video/type-info.h>
#include <spa/utils/result.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

struct node {
    struct pw_thread_loop *loop;
    struct pw_stream *stream;
    struct spa_hook listener;
    struct spa_source *frame_event, *close_timer;
    struct spa_video_info_raw fmt;
    int stride, size;

    const char *cam_id;
    int w, h, fps, stamp;
    ACameraManager *mgr;
    ACameraDevice *dev;
    AImageReader *reader;
    ACaptureSessionOutputContainer *outputs;
    ACaptureSessionOutput *output;
    ACameraOutputTarget *target;
    ACaptureRequest *req;
    ACameraCaptureSession *session;
    bool camera_open;

    pthread_mutex_t pending_lock;
    AImage *pending;

    uint64_t frames, replaced, starved, copy_ns;
    int64_t t_stream;
};

static int64_t now_ns(clockid_t c) {
    struct timespec ts;
    clock_gettime(c, &ts);
    return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

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

// Camera thread: keep only the newest image, then wake the PipeWire loop.
static void on_image(void *ctx, AImageReader *reader) {
    struct node *n = ctx;
    AImage *img = NULL;
    if (AImageReader_acquireLatestImage(reader, &img) != AMEDIA_OK || !img) return;
    pthread_mutex_lock(&n->pending_lock);
    AImage *old = n->pending;
    n->pending = img;
    pthread_mutex_unlock(&n->pending_lock);
    if (old) {
        AImage_delete(old);
        n->replaced++;
    }
    pw_loop_signal_event(pw_thread_loop_get_loop(n->loop), n->frame_event);
}

static void on_frame_event(void *data, uint64_t count) {
    struct node *n = data;
    pw_stream_trigger_process(n->stream);
}

static void copy_frame(struct node *n, AImage *img, uint8_t *dst) {
    uint8_t *p[3];
    int len, row[3], pix[3], w = n->w, h = n->h;
    for (int i = 0; i < 3; i++) {
        AImage_getPlaneData(img, i, &p[i], &len);
        AImage_getPlaneRowStride(img, i, &row[i]);
        AImage_getPlanePixelStride(img, i, &pix[i]);
    }
    uint8_t *u = p[1], *v = p[2];
    switch (n->fmt.format) {
    case SPA_VIDEO_FORMAT_NV21:
    case SPA_VIDEO_FORMAT_NV12: {
        for (int r = 0; r < h; r++) memcpy(dst + r * w, p[0] + r * row[0], w);
        uint8_t *first = n->fmt.format == SPA_VIDEO_FORMAT_NV21 ? v : u;
        uint8_t *second = n->fmt.format == SPA_VIDEO_FORMAT_NV21 ? u : v;
        uint8_t *c = dst + w * h;
        if (pix[1] == 2 && second == first + 1) {
            for (int r = 0; r < h / 2; r++) memcpy(c + r * w, first + r * row[1], w);
        } else {
            for (int r = 0; r < h / 2; r++)
                for (int x = 0; x < w / 2; x++) {
                    c[r * w + 2 * x] = first[r * row[1] + x * pix[1]];
                    c[r * w + 2 * x + 1] = second[r * row[2] + x * pix[2]];
                }
        }
        break;
    }
    case SPA_VIDEO_FORMAT_I420: {
        for (int r = 0; r < h; r++) memcpy(dst + r * w, p[0] + r * row[0], w);
        uint8_t *cu = dst + w * h, *cv = cu + w * h / 4;
        for (int r = 0; r < h / 2; r++)
            for (int x = 0; x < w / 2; x++) {
                cu[r * w / 2 + x] = u[r * row[1] + x * pix[1]];
                cv[r * w / 2 + x] = v[r * row[2] + x * pix[2]];
            }
        break;
    }
    case SPA_VIDEO_FORMAT_YUY2:
        for (int r = 0; r < h; r++) {
            const uint8_t *y = p[0] + r * row[0], *ur = u + (r / 2) * row[1], *vr = v + (r / 2) * row[2];
            uint8_t *o = dst + r * n->stride;
            for (int x = 0; x < w / 2; x++) {
                o[4 * x] = y[2 * x];
                o[4 * x + 1] = ur[x * pix[1]];
                o[4 * x + 2] = y[2 * x + 1];
                o[4 * x + 3] = vr[x * pix[2]];
            }
        }
        break;
    default:
        break;
    }
}

// PipeWire loop thread: one copy from the newest camera image into the buffer.
static void on_process(void *data) {
    struct node *n = data;
    pthread_mutex_lock(&n->pending_lock);
    AImage *img = n->pending;
    n->pending = NULL;
    pthread_mutex_unlock(&n->pending_lock);
    if (!img) return;
    struct pw_buffer *b = pw_stream_dequeue_buffer(n->stream);
    if (!b) {
        n->starved++;
        AImage_delete(img);
        return;
    }
    struct spa_data *d = &b->buffer->datas[0];
    int64_t ts = 0;
    AImage_getTimestamp(img, &ts);
    if (d->data && (int)d->maxsize >= n->size) {
        int64_t c0 = now_ns(CLOCK_MONOTONIC);
        copy_frame(n, img, d->data);
        n->copy_ns += now_ns(CLOCK_MONOTONIC) - c0;
        if (n->stamp) memcpy(d->data, &ts, sizeof ts);
        d->chunk->offset = 0;
        d->chunk->size = n->size;
        d->chunk->stride = n->stride;
    }
    struct spa_meta_header *h = spa_buffer_find_meta_data(b->buffer, SPA_META_Header, sizeof(*h));
    if (h) {
        h->pts = ts;
        h->flags = 0;
        h->seq = n->frames;
        h->dts_offset = 0;
    }
    AImage_delete(img);
    n->frames++;
    pw_stream_queue_buffer(n->stream, b);
}

static void on_cam_disconnected(void *ctx, ACameraDevice *dev) { fprintf(stderr, "camera disconnected\n"); }
static void on_cam_error(void *ctx, ACameraDevice *dev, int err) { fprintf(stderr, "camera error %d\n", err); }
static void on_session(void *ctx, ACameraCaptureSession *s) {}

static int camera_start(struct node *n) {
    ACameraDevice_StateCallbacks dcb = {.context = n, .onDisconnected = on_cam_disconnected, .onError = on_cam_error};
    int r;
    if ((r = ACameraManager_openCamera(n->mgr, n->cam_id, &dcb, &n->dev))) return r;
    if ((r = AImageReader_new(n->w, n->h, AIMAGE_FORMAT_YUV_420_888, 4, &n->reader))) return r;
    AImageReader_ImageListener l = {.context = n, .onImageAvailable = on_image};
    AImageReader_setImageListener(n->reader, &l);
    ANativeWindow *win;
    AImageReader_getWindow(n->reader, &win);
    ACaptureSessionOutputContainer_create(&n->outputs);
    ACaptureSessionOutput_create(win, &n->output);
    ACaptureSessionOutputContainer_add(n->outputs, n->output);
    ACameraOutputTarget_create(win, &n->target);
    ACameraDevice_createCaptureRequest(n->dev, TEMPLATE_RECORD, &n->req);
    ACaptureRequest_addTarget(n->req, n->target);
    int32_t range[2] = {n->fps, n->fps};
    ACaptureRequest_setEntry_i32(n->req, ACAMERA_CONTROL_AE_TARGET_FPS_RANGE, 2, range);
    ACameraCaptureSession_stateCallbacks scb = {
        .context = n, .onClosed = on_session, .onReady = on_session, .onActive = on_session};
    if ((r = ACameraDevice_createCaptureSession(n->dev, n->outputs, &scb, &n->session))) return r;
    if ((r = ACameraCaptureSession_setRepeatingRequest(n->session, NULL, 1, &n->req, NULL))) return r;
    n->camera_open = true;
    return 0;
}

static void camera_stop(struct node *n) {
    if (n->session) {
        ACameraCaptureSession_stopRepeating(n->session);
        ACameraCaptureSession_close(n->session);
    }
    if (n->dev) ACameraDevice_close(n->dev);
    if (n->req) ACaptureRequest_free(n->req);
    if (n->target) ACameraOutputTarget_free(n->target);
    if (n->output) ACaptureSessionOutput_free(n->output);
    if (n->outputs) ACaptureSessionOutputContainer_free(n->outputs);
    pthread_mutex_lock(&n->pending_lock);
    if (n->pending) AImage_delete(n->pending);
    n->pending = NULL;
    pthread_mutex_unlock(&n->pending_lock);
    if (n->reader) AImageReader_delete(n->reader);
    n->session = NULL, n->dev = NULL, n->req = NULL, n->target = NULL;
    n->output = NULL, n->outputs = NULL, n->reader = NULL;
    n->camera_open = false;
}

static void on_close_timer(void *data, uint64_t expirations) {
    struct node *n = data;
    if (!n->camera_open) return;
    camera_stop(n);
    fprintf(stderr, "camera %s closed\n", n->cam_id);
}

// V4L2 clients stream once to negotiate a format and again to capture, so the
// camera stays open briefly after a stream stops instead of reopening.
static void on_state_changed(void *data, enum pw_stream_state old, enum pw_stream_state state, const char *error) {
    struct node *n = data;
    struct pw_loop *loop = pw_thread_loop_get_loop(n->loop);
    fprintf(stderr, "stream %s -> %s%s%s\n", pw_stream_state_as_string(old), pw_stream_state_as_string(state),
            error ? ": " : "", error ? error : "");
    if (state == PW_STREAM_STATE_STREAMING) {
        pw_loop_update_timer(loop, n->close_timer, NULL, NULL, false);
        if (n->camera_open) return;
        int64_t t0 = now_ns(CLOCK_MONOTONIC);
        int r = camera_start(n);
        fprintf(stderr, "camera %s opened in %.0f ms (status %d)\n", n->cam_id, (now_ns(CLOCK_MONOTONIC) - t0) / 1e6,
                r);
        n->t_stream = now_ns(CLOCK_MONOTONIC);
        if (r) camera_stop(n);
    } else if (n->camera_open) {
        struct timespec delay = {.tv_sec = 2};
        pw_loop_update_timer(loop, n->close_timer, &delay, NULL, false);
    }
}

// Files the livecd-v4l2 preload reads to present /dev/videoN.
static char v4l2_dir[PATH_MAX];

static void mkdirs(char *path) {
    for (char *p = path + 1; *p; p++)
        if (*p == '/') {
            *p = 0;
            mkdir(path, 0700);
            *p = '/';
        }
    mkdir(path, 0700);
}

static void write_file(const char *dir, const char *name, const char *text) {
    char path[PATH_MAX];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "w");
    if (f) {
        fputs(text, f);
        fclose(f);
    }
}

static void publish_device(int dev, const char *desc) {
    const char *dir = getenv("LIVECD_V4L2_DIR"), *run = getenv("XDG_RUNTIME_DIR"), *tmp = getenv("TMPDIR");
    if (dir && *dir)
        snprintf(v4l2_dir, sizeof v4l2_dir, "%s", dir);
    else
        snprintf(v4l2_dir, sizeof v4l2_dir, "%s/livecd-v4l2", run && *run ? run : tmp);
    char sys[PATH_MAX], devdir[PATH_MAX], text[128];
    snprintf(sys, sizeof sys, "%s/sys/class/video4linux/video%d", v4l2_dir, dev);
    snprintf(devdir, sizeof devdir, "%s/dev", v4l2_dir);
    mkdirs(sys);
    mkdirs(devdir);
    snprintf(text, sizeof text, "%s\n", desc);
    write_file(sys, "name", text);
    write_file(sys, "index", "0\n");
    snprintf(text, sizeof text, "%d:%d\n", 81, dev);
    write_file(sys, "dev", text);
    snprintf(text, sizeof text, "MAJOR=81\nMINOR=%d\nDEVNAME=video%d\n", dev, dev);
    write_file(sys, "uevent", text);
    snprintf(text, sizeof text, "video%d", dev);
    write_file(devdir, text, "");  // last: the marker means the device is ready
}

static void unpublish_device(int dev) {
    char path[PATH_MAX];
    snprintf(path, sizeof path, "%s/dev/video%d", v4l2_dir, dev);
    unlink(path);
    static const char *const files[] = {"name", "index", "dev", "uevent"};
    for (size_t i = 0; i < sizeof files / sizeof *files; i++) {
        snprintf(path, sizeof path, "%s/sys/class/video4linux/video%d/%s", v4l2_dir, dev, files[i]);
        unlink(path);
    }
    snprintf(path, sizeof path, "%s/sys/class/video4linux/video%d", v4l2_dir, dev);
    rmdir(path);
}

static void on_param_changed(void *data, uint32_t id, const struct spa_pod *param) {
    struct node *n = data;
    if (param == NULL || id != SPA_PARAM_Format) return;
    if (spa_format_video_raw_parse(param, &n->fmt) < 0) return;
    bool packed = n->fmt.format == SPA_VIDEO_FORMAT_YUY2;
    n->stride = packed ? n->w * 2 : n->w;
    n->size = packed ? n->w * n->h * 2 : n->w * n->h * 3 / 2;
    fprintf(stderr, "negotiated %s %ux%u\n", spa_debug_type_find_short_name(spa_type_video_format, n->fmt.format),
            n->fmt.size.width, n->fmt.size.height);
    uint8_t buf[1024];
    struct spa_pod_builder b = SPA_POD_BUILDER_INIT(buf, sizeof(buf));
    const struct spa_pod *params[2];
    params[0] = spa_pod_builder_add_object(&b, SPA_TYPE_OBJECT_ParamBuffers, SPA_PARAM_Buffers,
        SPA_PARAM_BUFFERS_buffers, SPA_POD_CHOICE_RANGE_Int(4, 2, 8),
        SPA_PARAM_BUFFERS_blocks, SPA_POD_Int(1),
        SPA_PARAM_BUFFERS_size, SPA_POD_Int(n->size),
        SPA_PARAM_BUFFERS_stride, SPA_POD_Int(n->stride),
        SPA_PARAM_BUFFERS_dataType, SPA_POD_CHOICE_FLAGS_Int(1 << SPA_DATA_MemFd));
    params[1] = spa_pod_builder_add_object(&b, SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
        SPA_PARAM_META_type, SPA_POD_Id(SPA_META_Header),
        SPA_PARAM_META_size, SPA_POD_Int(sizeof(struct spa_meta_header)));
    pw_stream_update_params(n->stream, params, 2);
}

static const struct pw_stream_events stream_events = {
    PW_VERSION_STREAM_EVENTS,
    .state_changed = on_state_changed,
    .param_changed = on_param_changed,
    .process = on_process,
};

static volatile sig_atomic_t stop;
static void on_signal(int sig) { stop = 1; }

static double cpu_s(void) {
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
    return ru.ru_utime.tv_sec + ru.ru_stime.tv_sec + (ru.ru_utime.tv_usec + ru.ru_stime.tv_usec) / 1e6;
}

int main(int argc, char **argv) {
    struct node n = {.pending_lock = PTHREAD_MUTEX_INITIALIZER};
    const char *pos[5] = {"1", "1280", "720", "30", "0"};
    int npos = 0, device = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--stamp"))
            n.stamp = 1;
        else if (!strncmp(argv[i], "--device=", 9))
            device = atoi(argv[i] + 9);
        else if (npos < 5)
            pos[npos++] = argv[i];
    }
    n.cam_id = pos[0];
    n.w = atoi(pos[1]);
    n.h = atoi(pos[2]);
    n.fps = atoi(pos[3]);
    int seconds = atoi(pos[4]);
    if (start_binder_pool()) fprintf(stderr, "could not start a Binder thread pool\n");
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    pw_init(&argc, &argv);
    n.mgr = ACameraManager_create();
    n.loop = pw_thread_loop_new("camnode", NULL);
    char name[64], desc[64], path[32];
    snprintf(name, sizeof name, "livecd-camera-%s", n.cam_id);
    snprintf(desc, sizeof desc, "Phone camera %s", n.cam_id);
    snprintf(path, sizeof path, "v4l2:/dev/video%d", device);
    n.stream = pw_stream_new_simple(pw_thread_loop_get_loop(n.loop), name,
        pw_properties_new(PW_KEY_MEDIA_TYPE, "Video", PW_KEY_MEDIA_CATEGORY, "Capture", PW_KEY_MEDIA_ROLE, "Camera",
                          PW_KEY_MEDIA_CLASS, "Video/Source", PW_KEY_NODE_DESCRIPTION, desc,
                          PW_KEY_OBJECT_PATH, path, NULL),
        &stream_events, &n);
    n.frame_event = pw_loop_add_event(pw_thread_loop_get_loop(n.loop), on_frame_event, &n);
    n.close_timer = pw_loop_add_timer(pw_thread_loop_get_loop(n.loop), on_close_timer, &n);

    // One EnumFormat per pixel format: pw-v4l2 lists formats only from a fixed
    // format id, as hardware nodes publish them, and skips a choice list.
    static const uint32_t formats[] = {SPA_VIDEO_FORMAT_NV21, SPA_VIDEO_FORMAT_NV12, SPA_VIDEO_FORMAT_YUY2,
                                       SPA_VIDEO_FORMAT_I420};
    uint8_t buf[2048];
    struct spa_pod_builder b = SPA_POD_BUILDER_INIT(buf, sizeof(buf));
    const struct spa_pod *params[SPA_N_ELEMENTS(formats)];
    for (size_t i = 0; i < SPA_N_ELEMENTS(formats); i++)
        params[i] = spa_pod_builder_add_object(&b, SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat,
            SPA_FORMAT_mediaType, SPA_POD_Id(SPA_MEDIA_TYPE_video),
            SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
            SPA_FORMAT_VIDEO_format, SPA_POD_Id(formats[i]),
            SPA_FORMAT_VIDEO_size, SPA_POD_Rectangle(&SPA_RECTANGLE(n.w, n.h)),
            SPA_FORMAT_VIDEO_framerate, SPA_POD_Fraction(&SPA_FRACTION(n.fps, 1)));
    pw_stream_connect(n.stream, PW_DIRECTION_OUTPUT, PW_ID_ANY, PW_STREAM_FLAG_DRIVER | PW_STREAM_FLAG_MAP_BUFFERS,
                      params, SPA_N_ELEMENTS(formats));
    pw_thread_loop_start(n.loop);
    publish_device(device, desc);
    fprintf(stderr, "node %s ready as %s\n", name, path + 5);

    int64_t t0 = now_ns(CLOCK_MONOTONIC);
    while (!stop && (!seconds || now_ns(CLOCK_MONOTONIC) - t0 < seconds * 1000000000LL)) {
        double c0 = cpu_s();
        int64_t w0 = now_ns(CLOCK_MONOTONIC);
        uint64_t f0 = n.frames, k0 = n.copy_ns;
        sleep(5);
        uint64_t df = n.frames - f0;
        if (df)
            fprintf(stderr, "%.1f fps out, copy %.2f ms/frame, CPU %.1f%% of one core, replaced %llu, starved %llu\n",
                    df * 1e9 / (now_ns(CLOCK_MONOTONIC) - w0), (n.copy_ns - k0) / 1e6 / df,
                    100 * (cpu_s() - c0) * 1e9 / (now_ns(CLOCK_MONOTONIC) - w0), (unsigned long long)n.replaced,
                    (unsigned long long)n.starved);
    }
    unpublish_device(device);
    pw_thread_loop_lock(n.loop);
    if (n.camera_open) camera_stop(&n);
    pw_stream_destroy(n.stream);
    pw_thread_loop_unlock(n.loop);
    pw_thread_loop_stop(n.loop);
    pw_thread_loop_destroy(n.loop);
    ACameraManager_delete(n.mgr);
    pw_deinit();
    return 0;
}
