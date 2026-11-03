package com.termux.x11;

import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;

/**
 * Runs Termux:X11's real X server, DRI3 included, with no Android window.
 *
 * Placed before the app's APK on the classpath, this replaces only the class that
 * tells the Android app about a new server. Its broadcasts become no-ops, so the app
 * never learns of this server and whatever it is showing stays connected.
 */
public class CmdEntryPoint {
    public native boolean start(String[] args);
    public native ParcelFileDescriptor getXConnection();
    public native ParcelFileDescriptor getLogcatOutput();
    public native void reportFatalError(String message);
    private static native boolean connected();

    // The native server looks these up by name and signature, and calls them.
    void setDocumentTag(String tag) {}
    private void sendBroadcast() {}
    private void sendBroadcastDelayed() {}

    public static void main(String[] args) {
        Looper.prepareMainLooper();
        System.load(System.getenv("LIVECD_LORIE_LIBRARY"));
        new Handler().post(() -> {
            if (!new CmdEntryPoint().start(args))
                System.exit(1);
        });
        Looper.loop();
    }
}
