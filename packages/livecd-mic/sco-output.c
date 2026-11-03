/* MIT. Native PCM output for PulseAudio's pipe sink. Android owns Bluetooth. */
#include <SLES/OpenSLES.h>
#include <SLES/OpenSLES_Android.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <semaphore.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

#define BUFFERS 4
#define FRAMES 320 /* 20 ms, mono, 16 kHz */

static volatile sig_atomic_t stopping;
static sem_t available;

static void stop(int signal_number) { (void)signal_number; stopping = 1; }
static void played(SLAndroidSimpleBufferQueueItf queue, void *context) {
    (void)queue;
    (void)context;
    sem_post(&available);
}

int main(int argc, char **argv) {
    if (argc != 2) { fputs("Usage: sco-output PCM_FIFO\n", stderr); return 2; }
    int fd = open(argv[1], O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
    struct stat info;
    if (fd < 0 || fstat(fd, &info) || !S_ISFIFO(info.st_mode) || info.st_uid != getuid()) {
        fputs("Expected a private FIFO owned by this Termux user\n", stderr);
        if (fd >= 0) close(fd);
        return 1;
    }
    struct sigaction action = { .sa_handler = stop };
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGHUP, &action, NULL);
    if (sem_init(&available, 0, BUFFERS)) { close(fd); return 1; }

    SLObjectItf engine_object = NULL, mix = NULL, player = NULL;
    SLEngineItf engine;
    SLPlayItf play;
    SLAndroidSimpleBufferQueueItf queue;
    SLAndroidConfigurationItf configuration;
    int result = 1;
    SLresult status;
#define CHECK(expression) do { \
    status = (expression); \
    if (status != SL_RESULT_SUCCESS) { \
        fprintf(stderr, "OpenSL voice output failed (%u): %s\n", (unsigned)status, #expression); \
        goto done; \
    } \
} while (0)
    CHECK(slCreateEngine(&engine_object, 0, NULL, 0, NULL, NULL));
    CHECK((*engine_object)->Realize(engine_object, SL_BOOLEAN_FALSE));
    CHECK((*engine_object)->GetInterface(engine_object, SL_IID_ENGINE, &engine));
    CHECK((*engine)->CreateOutputMix(engine, &mix, 0, NULL, NULL));
    CHECK((*mix)->Realize(mix, SL_BOOLEAN_FALSE));

    SLDataLocator_AndroidSimpleBufferQueue locator = {
        SL_DATALOCATOR_ANDROIDSIMPLEBUFFERQUEUE, BUFFERS
    };
    SLDataFormat_PCM format = {
        SL_DATAFORMAT_PCM, 1, SL_SAMPLINGRATE_16,
        SL_PCMSAMPLEFORMAT_FIXED_16, SL_PCMSAMPLEFORMAT_FIXED_16,
        SL_SPEAKER_FRONT_CENTER, SL_BYTEORDER_LITTLEENDIAN
    };
    SLDataSource source = { &locator, &format };
    SLDataLocator_OutputMix output = { SL_DATALOCATOR_OUTPUTMIX, mix };
    SLDataSink sink = { &output, NULL };
    const SLInterfaceID interfaces[] = { SL_IID_ANDROIDSIMPLEBUFFERQUEUE, SL_IID_ANDROIDCONFIGURATION };
    const SLboolean required[] = { SL_BOOLEAN_TRUE, SL_BOOLEAN_TRUE };
    CHECK((*engine)->CreateAudioPlayer(engine, &player, &source, &sink, 2, interfaces, required));
    CHECK((*player)->GetInterface(player, SL_IID_ANDROIDCONFIGURATION, &configuration));
    SLuint32 stream = SL_ANDROID_STREAM_VOICE;
    CHECK((*configuration)->SetConfiguration(configuration, SL_ANDROID_KEY_STREAM_TYPE,
                                            &stream, sizeof(stream)));
    CHECK((*player)->Realize(player, SL_BOOLEAN_FALSE));
    CHECK((*player)->GetInterface(player, SL_IID_PLAY, &play));
    CHECK((*player)->GetInterface(player, SL_IID_ANDROIDSIMPLEBUFFERQUEUE, &queue));
    CHECK((*queue)->RegisterCallback(queue, played, NULL));
    CHECK((*play)->SetPlayState(play, SL_PLAYSTATE_PLAYING));
    puts("{\"ready\":true,\"rate\":16000,\"channels\":1}");
    fflush(stdout);

    int16_t pcm[BUFFERS][FRAMES];
    unsigned next = 0;
    while (!stopping) {
        while (sem_wait(&available)) {
            if (errno != EINTR) { perror("sem_wait"); goto done; }
            if (stopping) goto stopped;
        }
        size_t offset = 0;
        while (offset < sizeof(pcm[next]) && !stopping) {
            struct pollfd input = { .fd = fd, .events = POLLIN };
            int events = poll(&input, 1, 1000);
            if (events < 0) {
                if (errno == EINTR) continue;
                perror("poll"); goto done;
            }
            if (!events) continue;
            if (input.revents & (POLLERR | POLLNVAL)) goto done;
            ssize_t count = read(fd, (char *)pcm[next] + offset, sizeof(pcm[next]) - offset);
            if (count > 0) offset += (size_t)count;
            else if (count == 0) goto stopped; /* writer closed: do not spin on HUP */
            else if (errno != EAGAIN && errno != EINTR) { perror("read"); goto done; }
        }
        if (stopping) break;
        CHECK((*queue)->Enqueue(queue, pcm[next], sizeof(pcm[next])));
        next = (next + 1) % BUFFERS;
    }
stopped:
    result = 0;
done:
    if (player) (*player)->Destroy(player);
    if (mix) (*mix)->Destroy(mix);
    if (engine_object) (*engine_object)->Destroy(engine_object);
    sem_destroy(&available);
    close(fd);
    return result;
}
