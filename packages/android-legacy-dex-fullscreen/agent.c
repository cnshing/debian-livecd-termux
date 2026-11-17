#include <jni.h>
static jclass helper;
static jmethodID dex_enabled;
static jmethodID fullscreen;
static jboolean eligible(JNIEnv *e, jclass unused, jobject decor) {
    (void)unused;
    if (!decor) return JNI_FALSE;
    jboolean dex = (*e)->CallBooleanMethod(e, decor, dex_enabled);
    if ((*e)->ExceptionCheck(e)) return JNI_FALSE;
    return dex && (*e)->CallBooleanMethod(e, decor, fullscreen);
}
static int failure(JNIEnv *e) {
    if ((*e)->ExceptionCheck(e)) {
        (*e)->ExceptionDescribe(e);
        (*e)->ExceptionClear(e);
    }
    return 1;
}
JNIEXPORT jint JNICALL Agent_OnAttach(JavaVM *vm, char *options, void *reserved) {
    JNIEnv *e = 0;
    (void)reserved;
    if ((*vm)->GetEnv(vm, (void **)&e, JNI_VERSION_1_6) != JNI_OK) return 1;
    if (!helper) {
        jclass at = (*e)->FindClass(e, "android/app/ActivityThread");
        if (!at) return failure(e);
        jmethodID current = (*e)->GetStaticMethodID(e, at, "currentApplication", "()Landroid/app/Application;");
        if (!current) return failure(e);
        jobject app = (*e)->CallStaticObjectMethod(e, at, current);
        if (!app || (*e)->ExceptionCheck(e)) return failure(e);
        jclass context = (*e)->FindClass(e, "android/content/Context");
        jmethodID getloader = (*e)->GetMethodID(e, context, "getClassLoader", "()Ljava/lang/ClassLoader;");
        jobject parent = (*e)->CallObjectMethod(e, app, getloader);
        if (!parent || (*e)->ExceptionCheck(e)) return failure(e);
        jclass dc = (*e)->FindClass(e, "dalvik/system/DexClassLoader");
        jmethodID ctor = (*e)->GetMethodID(e, dc, "<init>", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V");
        if (!ctor) return failure(e);
        jstring path = (*e)->NewStringUTF(e, options && *options ? options : "/data/user/0/com.termux.x11/files/android-legacy-dex-fullscreen/helper.dex");
        jstring optdir = (*e)->NewStringUTF(e, "/data/user/0/com.termux.x11/code_cache");
        jobject loader = (*e)->NewObject(e, dc, ctor, path, optdir, (jobject)0, parent);
        if (!loader || (*e)->ExceptionCheck(e)) return failure(e);
        jclass lc = (*e)->FindClass(e, "java/lang/ClassLoader");
        jmethodID load = (*e)->GetMethodID(e, lc, "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;");
        jstring name = (*e)->NewStringUTF(e, "org.livecd.dexfullscreen.Helper");
        jobject loaded = (*e)->CallObjectMethod(e, loader, load, name);
        if (!loaded || (*e)->ExceptionCheck(e)) return failure(e);
        helper = (jclass)(*e)->NewGlobalRef(e, loaded);
    }
    if (!dex_enabled || !fullscreen) {
        // Resolve the two firmware getters on the agent attach thread. This does
        // not disable hidden-API enforcement or alter framework methods.
        jclass decor = (*e)->FindClass(e, "com/android/internal/policy/DecorView");
        if (!decor) return failure(e);
        dex_enabled = (*e)->GetMethodID(e, decor, "isDexEnabled", "()Z");
        if (!dex_enabled) return failure(e);
        fullscreen = (*e)->GetMethodID(e, decor, "isFullScreen", "()Z");
        if (!fullscreen) return failure(e);
        JNINativeMethod methods[] = {{"eligible", "(Landroid/view/View;)Z", (void *)eligible}};
        if ((*e)->RegisterNatives(e, helper, methods, 1) != JNI_OK) return failure(e);
    }
    jmethodID start = (*e)->GetStaticMethodID(e, helper, "start", "()V");
    if (!start) return failure(e);
    (*e)->CallStaticVoidMethod(e, helper, start);
    return (*e)->ExceptionCheck(e) ? failure(e) : 0;
}
