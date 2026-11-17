package org.livecd.dexfullscreen;

import android.app.Activity;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.util.Log;
import android.view.View;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;

/** Loaded by the agent; never rewrites app/framework bytecode or preferences. */
public final class Helper implements Runnable {
    private static final String TAG = "LegacyDexFullscreen";
    private static final int MASK = View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION;
    private static final File DIR = new File("/data/user/0/com.termux.x11/files/android-legacy-dex-fullscreen");
    private static Helper instance;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Method activityGetter;
    private final Field prefsField;
    private final Field fullscreenField;
    private final Method preferenceGetter;
    private static native boolean eligible(View decor);
    private View decor;
    private int baseline;
    private boolean active;
    private boolean running;
    private String lastStatus = "";

    private Helper() throws Exception {
        Class<?> activity = Class.forName("com.termux.x11.MainActivity");
        activityGetter = activity.getMethod("getFocusedOrAnyInstance");
        prefsField = activity.getField("prefs");
        fullscreenField = prefsField.getType().getField("fullscreen");
        preferenceGetter = fullscreenField.getType().getMethod("get");
    }

    public static synchronized void start() throws Exception {
        if (Build.VERSION.SDK_INT != 30 || !"samsung".equalsIgnoreCase(Build.MANUFACTURER))
            throw new IllegalStateException("Only Samsung Android 11 is supported");
        if (instance == null) instance = new Helper();
        if (!instance.running) {
            instance.running = true;
            instance.handler.post(instance);
        }
    }

    private void restore() {
        if (active && decor != null) {
            decor.setSystemUiVisibility((decor.getSystemUiVisibility() & ~MASK) | baseline);
            active = false;
        }
    }

    private void status(String phase, String detail) throws Exception {
        String identity = phase + ":" + active + ":" + detail;
        if (identity.equals(lastStatus)) return;
        // Do not include exception messages or app content in this shell-readable record.
        String json = "{\"pid\":" + Process.myPid() + ",\"phase\":\"" + phase
            + "\",\"active\":" + active + ",\"detail\":\"" + detail + "\"}\n";
        File temporary = new File(DIR, "status.tmp");
        try (FileOutputStream out = new FileOutputStream(temporary)) {
            out.write(json.getBytes(StandardCharsets.UTF_8));
        }
        if (!temporary.renameTo(new File(DIR, "status.json")))
            throw new IllegalStateException("Cannot publish helper status");
        lastStatus = identity;
        Log.i(TAG, identity);
    }

    @Override public void run() {
        try {
            if (new File(DIR, "stop").exists()) {
                restore();
                decor = null;
                running = false;
                status("stopped", "stop-requested");
                return;
            }
            Activity activity = (Activity) activityGetter.invoke(null);
            boolean enabled = activity != null && !activity.isDestroyed()
                && activity.getDisplay() != null && activity.getDisplay().getDisplayId() != 0;
            if (enabled) {
                Object prefs = prefsField.get(activity);
                enabled = prefs != null && Boolean.TRUE.equals(preferenceGetter.invoke(fullscreenField.get(prefs)));
            }
            if (enabled) {
                View view = activity.getWindow().getDecorView();
                // Refuse to apply the workaround to a freeform/non-DeX window.
                enabled = eligible(view);
                if (enabled) {
                    if (view != decor) { restore(); decor = view; }
                    int current = view.getSystemUiVisibility();
                    if (!active) { baseline = current & MASK; active = true; }
                    if ((current & MASK) != MASK) view.setSystemUiVisibility(current | MASK);
                }
            }
            if (!enabled) { restore(); decor = null; }
            status("running", enabled ? "fullscreen" : "waiting-for-dex-fullscreen");
            handler.postDelayed(this, 250);
        } catch (Throwable error) {
            running = false;
            try { restore(); decor = null; status("failed", "unsupported-app-or-framework"); }
            catch (Throwable ignored) { /* Main thread must remain usable. */ }
            Log.e(TAG, "Runtime helper stopped", error);
        }
    }
}
