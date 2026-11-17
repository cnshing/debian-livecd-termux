/* SPDX-License-Identifier: MIT
 * Check actual MediaCodec ByteBuffer precision on Adreno. This is format
 * negotiation evidence, not pixel, HDR, performance or VA-API qualification.
 * Build with the Android NDK (API 29): clang probe-bytebuffer.c -lmediandk.
 * Default: request YUV420Flexible. --nv12 is the expected-failing control.
 * Uses two synthetic 96x96 grey keyframes, never the camera or live display.
 */
#include <media/NdkMediaCodec.h>
#include <media/NdkMediaFormat.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
/* libx265 Main 10 and libvpx-vp9 profile 2, 96x96, one grey key frame each. */
static const uint8_t probe_hevc_main10[] = {
    0x00, 0x00, 0x00, 0x01, 0x40, 0x01, 0x0c, 0x01, 0xff, 0xff, 0x04, 0x08, 0x00, 0x00, 0x03, 0x00,
    0x9d, 0xa8, 0x00, 0x00, 0x03, 0x00, 0x00, 0x1e, 0xba, 0x02, 0x40, 0x00, 0x00, 0x00, 0x01, 0x42,
    0x01, 0x01, 0x04, 0x08, 0x00, 0x00, 0x03, 0x00, 0x9d, 0xa8, 0x00, 0x00, 0x03, 0x00, 0x00, 0x1e,
    0xa0, 0x30, 0x81, 0x84, 0xd9, 0x6e, 0xa4, 0x93, 0x2b, 0xc0, 0x5a, 0x02, 0x00, 0x00, 0x03, 0x00,
    0x02, 0x00, 0x00, 0x03, 0x00, 0x02, 0x10, 0x00, 0x00, 0x00, 0x01, 0x44, 0x01, 0xc1, 0x72, 0xb0,
    0x22, 0x40, 0x00, 0x00, 0x01, 0x28, 0x01, 0xaf, 0x78, 0xeb, 0xae, 0xfb, 0xfe, 0x75, 0x57, 0xca,
    0xc2, 0xa7, 0x9e, 0x4e, 0x84,
};
static const uint8_t probe_vp9_profile2[] = {
    0x92, 0x49, 0x83, 0x42, 0x00, 0x02, 0xf8, 0x02, 0xfb, 0x00, 0x1c, 0x12, 0x0e, 0x0c, 0x49, 0x00,
    0x00, 0x18, 0x60, 0x00, 0x00, 0x67, 0x36, 0x91, 0x3b, 0xc2, 0x80, 0xd7, 0x00,
};

static bool probe(const char *mime, const uint8_t *unit, size_t length, int requested)
{
    bool ok = false, started = false;
    AMediaCodec *codec = AMediaCodec_createDecoderByType(mime);
    AMediaFormat *format = NULL;
    if (!codec) return false;
    char *name = NULL;
    if (AMediaCodec_getName(codec, &name) != AMEDIA_OK || !name) goto done;
    printf("%s component=%s request=0x%x\n", mime, name, requested);
    bool qualcomm = !strncmp(name, "OMX.qcom.", 9) || !strncmp(name, "c2.qti.", 7);
    AMediaCodec_releaseName(codec, name);
    if (!qualcomm) goto done;
    format = AMediaFormat_new();
    if (!format) goto done;
    AMediaFormat_setString(format, "mime", mime);
    AMediaFormat_setInt32(format, "width", 96);
    AMediaFormat_setInt32(format, "height", 96);
    AMediaFormat_setInt32(format, "color-format", requested);
    media_status_t status = AMediaCodec_configure(codec, format, NULL, NULL, 0);
    if (status != AMEDIA_OK) { printf("configure=%d\n", status); goto done; }
    status = AMediaCodec_start(codec);
    if (status != AMEDIA_OK) { printf("start=%d\n", status); goto done; }
    started = true;
    int sent = 0;
    int32_t color = -1;
    for (int attempt = 0; attempt < 300; attempt++) {
        if (sent < 2) {
            ssize_t input = AMediaCodec_dequeueInputBuffer(codec, 10000);
            if (input >= 0) {
                size_t capacity = 0;
                uint8_t *buffer = AMediaCodec_getInputBuffer(codec, input, &capacity);
                if (!buffer || capacity < length) break;
                if (!sent) memcpy(buffer, unit, length);
                status = AMediaCodec_queueInputBuffer(codec, input, 0, sent ? 0 : length, 0,
                    sent ? AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM : 0);
                if (status != AMEDIA_OK) break;
                sent++;
            }
        }
        AMediaCodecBufferInfo info;
        ssize_t output = AMediaCodec_dequeueOutputBuffer(codec, &info, 10000);
        if (output == AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED) {
            AMediaFormat *actual = AMediaCodec_getOutputFormat(codec);
            if (actual) {
                AMediaFormat_getInt32(actual, "color-format", &color);
                printf("actual %s\n", AMediaFormat_toString(actual));
                AMediaFormat_delete(actual);
            }
        } else if (output >= 0) {
            size_t capacity = 0;
            uint8_t *buffer = AMediaCodec_getOutputBuffer(codec, output, &capacity);
            bool range = info.offset >= 0 && info.size > 0 &&
                (size_t)info.offset <= capacity && (size_t)info.size <= capacity - (size_t)info.offset;
            /* Android P010 or Qualcomm linear Venus P010. Buffer presence and
             * size are checked too: a format name alone is not an output frame. */
            if (buffer && range) {
                ok = (color == 54 || color == 0x7fa30c0a) && info.size >= 96 * 96 * 3;
                printf("frame size=%d capacity=%zu color=0x%x p010=%s\n",
                       info.size, capacity, color, ok ? "yes" : "no");
            }
            AMediaCodec_releaseOutputBuffer(codec, output, false);
            if (info.size > 0 || (info.flags & AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM)) break;
        }
    }
done:
    if (started) AMediaCodec_stop(codec);
    AMediaCodec_delete(codec);
    if (format) AMediaFormat_delete(format);
    return ok;
}

int main(int argc, char **argv)
{
    if (argc > 2 || (argc == 2 && strcmp(argv[1], "--nv12"))) {
        fprintf(stderr, "usage: %s [--nv12]\n", argv[0]);
        return 2;
    }
    int color = argc == 2 ? 21 : 0x7f420888;
    bool hevc = probe("video/hevc", probe_hevc_main10, sizeof(probe_hevc_main10), color);
    bool vp9 = probe("video/x-vnd.on2.vp9", probe_vp9_profile2, sizeof(probe_vp9_profile2), color);
    printf("HEVC Main10 P010=%s; VP9 profile2 P010=%s\n", hevc ? "yes" : "no", vp9 ? "yes" : "no");
    return hevc && vp9 ? 0 : 1;
}
