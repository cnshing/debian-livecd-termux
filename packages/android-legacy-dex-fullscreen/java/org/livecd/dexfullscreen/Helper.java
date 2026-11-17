package org.livecd.dexfullscreen;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.UiAutomation;
import android.graphics.Rect;
import android.os.Build;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.os.Process;
import android.os.SystemClock;
import android.os.DeadObjectException;
import android.util.SparseArray;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.*;
import java.util.regex.*;

/** Standalone shell process. Never loaded into, attached to, or installed as an app. */
public final class Helper {
    private static final String APP = "com.termux.x11";
    private static final long LEASE_MS = 15000;
    private final WindowPolicy policy = new WindowPolicy();
    private final HandlerThread thread = new HandlerThread("dex-window-binder");
    private final ExecutorService io = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "dex-window-read"); t.setDaemon(true); return t;
    });
    private final Object accessibility;
    private final Method tokenGetter;
    private final Method callback;
    private final Method asWindow;
    private final Method execute;
    private UiAutomation automation;
    private File directory;
    private final String birth = processStart();

    private static String processStart() throws IOException {
        try (BufferedReader reader = new BufferedReader(new FileReader("/proc/self/stat"))) {
            String stat = reader.readLine();
            return stat.substring(stat.lastIndexOf(')') + 2).split(" ")[19];
        }
    }

    private static Object service(String name, String iface) throws Exception {
        IBinder binder = (IBinder) Class.forName("android.os.ServiceManager")
            .getMethod("getService", String.class).invoke(null, name);
        if (binder == null) throw new IllegalStateException("Missing " + name + " service");
        return Class.forName(iface + "$Stub").getMethod("asInterface", IBinder.class).invoke(null, binder);
    }

    private Helper() throws Exception {
        if (Process.myUid() != 2000 || Build.VERSION.SDK_INT != 30
                || !"samsung".equalsIgnoreCase(Build.MANUFACTURER)
                || !Build.SUPPORTED_ABIS[0].equals("arm64-v8a"))
            throw new IllegalStateException("Requires Samsung Android 11 ARM64 and shell UID 2000");
        accessibility = service("accessibility", "android.view.accessibility.IAccessibilityManager");
        tokenGetter = Class.forName("android.view.accessibility.IAccessibilityManager")
            .getMethod("getWindowToken", int.class, int.class);
        // Enforce RETRIEVE_WINDOW_TOKEN even when there are no windows yet.
        tokenGetter.invoke(accessibility, -1, 0);
        Object am = service("activity", "android.app.IActivityManager");
        int permission = (Integer) Class.forName("android.app.IActivityManager")
            .getMethod("checkPermission", String.class, int.class, int.class)
            .invoke(am, "android.permission.DUMP", Process.myPid(), Process.myUid());
        if (permission != 0) throw new SecurityException("Shell lacks DUMP permission");
        Class<?> iw = Class.forName("android.view.IWindow");
        callback = iw.getMethod("dispatchSystemUiVisibilityChanged", int.class, int.class, int.class, int.class);
        execute = iw.getMethod("executeCommand", String.class, String.class, ParcelFileDescriptor.class);
        asWindow = Class.forName("android.view.IWindow$Stub").getMethod("asInterface", IBinder.class);
    }

    private void connect() throws Exception {
        thread.start();
        Object connection = Class.forName("android.app.UiAutomationConnection").getConstructor().newInstance();
        automation = (UiAutomation) UiAutomation.class
            .getConstructor(Looper.class, Class.forName("android.app.IUiAutomationConnection"))
            .newInstance(thread.getLooper(), connection);
        // Keep the user's existing accessibility services running.
        UiAutomation.class.getMethod("connect", int.class).invoke(automation, 1);
        AccessibilityServiceInfo info = automation.getServiceInfo();
        info.flags |= AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;
        automation.setServiceInfo(info);
    }

    private String dumpWindows() throws Exception {
        java.lang.Process child = new ProcessBuilder("/system/bin/dumpsys", "window", APP)
            .redirectErrorStream(true).start();
        Future<String> read = io.submit(() -> {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            try (InputStream input = child.getInputStream()) {
                byte[] bytes = new byte[8192]; int n;
                while ((n = input.read(bytes)) != -1) {
                    if (out.size() + n > 2 * 1024 * 1024) throw new IOException("Window dump too large");
                    out.write(bytes, 0, n);
                }
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        });
        try {
            String dump = read.get(4, TimeUnit.SECONDS);
            if (!child.waitFor(1, TimeUnit.SECONDS) || child.exitValue() != 0)
                throw new IOException("Window dump failed");
            return dump;
        } finally { child.destroy(); read.cancel(true); }
    }

    private final class Window implements WindowPolicy.Target {
        private final IBinder binder;
        private final Object window;
        Window(IBinder binder) throws Exception {
            if (!"android.view.IWindow".equals(binder.getInterfaceDescriptor()))
                throw new IllegalStateException("Unexpected window Binder descriptor");
            this.binder = binder;
            window = asWindow.invoke(null, binder);
        }
        @Override public boolean equals(Object other) {
            return other instanceof Helper.Window && binder.equals(((Window) other).binder);
        }
        @Override public int hashCode() { return binder.hashCode(); }
        public boolean alive() { return binder.isBinderAlive(); }
        public void apply(int value, int mask) throws Exception {
            callback.invoke(window, 0, 0, value, mask);
        }
        public int flags() throws Exception {
            ParcelFileDescriptor[] pipe = ParcelFileDescriptor.createPipe();
            Future<Integer> read = io.submit(() -> {
                String first;
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                        new ParcelFileDescriptor.AutoCloseInputStream(pipe[0]), StandardCharsets.UTF_8))) {
                    first = reader.readLine();
                    // Drain remaining data without storing/logging app view contents.
                    char[] discard = new char[8192];
                    while (reader.read(discard) != -1) { }
                }
                if (first == null || !first.startsWith("com.android.internal.policy.DecorView@"))
                    throw new IOException("Unsupported root view dump");
                Matcher bits = Pattern.compile("(?:^| )mSystemUiVisibility=\\d+,0x([0-9a-fA-F]+)(?: |$)").matcher(first);
                if (!bits.find()) throw new IOException("Cannot read original window UI bits");
                return (int) Long.parseLong(bits.group(1), 16);
            });
            try {
                execute.invoke(window, "DUMP", "", pipe[1]);
                pipe[1].close();
                return read.get(4, TimeUnit.SECONDS);
            } finally { pipe[0].close(); pipe[1].close(); read.cancel(true); }
        }
    }

    private Window candidate() throws Exception {
        SparseArray<List<AccessibilityWindowInfo>> displays = automation.getWindowsOnAllDisplays();
        Window result = null;
        for (int i = 0; i < displays.size(); i++) {
            for (AccessibilityWindowInfo w : displays.valueAt(i)) {
                if (w.getDisplayId() == 0 || !w.isFocused()
                        || w.getType() != AccessibilityWindowInfo.TYPE_APPLICATION) continue;
                AccessibilityNodeInfo root = w.getRoot();
                if (root == null) continue;
                boolean matches = APP.contentEquals(root.getPackageName() == null ? "" : root.getPackageName());
                root.recycle();
                if (!matches) continue;
                Rect bounds = new Rect();
                w.getBoundsInScreen(bounds);
                if (!WindowState.eligible(dumpWindows(), w.getDisplayId(),
                        bounds.left, bounds.top, bounds.right, bounds.bottom)) continue;
                IBinder binder = (IBinder) tokenGetter.invoke(accessibility, w.getId(), 0);
                if (binder == null || !binder.isBinderAlive()) continue;
                // Multiple focused target windows is ambiguous; do not choose arbitrarily.
                if (result != null) return null;
                result = new Window(binder);
            }
        }
        return result;
    }

    private void status(String phase, String detail) throws Exception {
        String json = "{\"pid\":" + Process.myPid() + ",\"start\":\"" + birth + "\",\"phase\":\"" + phase
            + "\",\"active\":" + policy.active() + ",\"detail\":\"" + detail + "\"}\n";
        if (directory == null) { System.out.print(json); return; }
        File temp = new File(directory, "status.tmp");
        try (FileOutputStream out = new FileOutputStream(temp)) { out.write(json.getBytes(StandardCharsets.UTF_8)); }
        if (!temp.renameTo(new File(directory, "status.json"))) throw new IOException("Cannot publish status");
    }

    private void close() throws Exception {
        Exception error = null;
        try { policy.restore(); } catch (Exception e) { error = e; }
        if (automation != null) {
            try { UiAutomation.class.getMethod("disconnect").invoke(automation); }
            catch (Exception e) { if (error == null) error = e; }
        }
        thread.quitSafely();
        io.shutdownNow();
        if (error != null) throw error;
    }

    private static File session(String path) throws Exception {
        File dir = new File(path).getCanonicalFile();
        if (!dir.getPath().matches("/data/local/tmp/android-legacy-dex-fullscreen\\.[A-Za-z0-9]+")
                || !dir.isDirectory()) throw new IllegalArgumentException("Invalid session directory");
        return dir;
    }

    public static void main(String[] args) {
        Helper helper = null;
        boolean failed = false;
        try {
            helper = new Helper();
            if (args.length == 1 && args[0].equals("check")) {
                helper.connect();
                helper.status("checked", "binder-available");
            } else if (args.length == 2 && args[0].equals("spawn")) {
                File dir = session(args[1]);
                // ProcessBuilder closes inherited rish transport FDs; shell '&' can keep rish waiting.
                ProcessBuilder builder = new ProcessBuilder("/system/bin/setsid", "/system/bin/app_process", "/",
                    Helper.class.getName(), dir.getPath());
                builder.environment().put("CLASSPATH", new File(dir, "helper.dex").getPath());
                builder.redirectInput(new File("/dev/null"));
                builder.redirectOutput(new File(dir, "helper.log"));
                builder.redirectErrorStream(true);
                builder.start();
                helper.status("launched", "shell-helper-started");
            } else {
                if (args.length != 1) throw new IllegalArgumentException("Expected a shell-owned session directory");
                helper.directory = session(args[0]);
                helper.connect();
                long lastLease = Long.MIN_VALUE;
                long renewedAt = SystemClock.elapsedRealtime();
                while (!new File(helper.directory, "stop").exists()) {
                    File lease = new File(helper.directory, "lease");
                    if (!lease.isFile()) break;
                    if (lease.lastModified() != lastLease) {
                        lastLease = lease.lastModified();
                        renewedAt = SystemClock.elapsedRealtime();
                    }
                    if (SystemClock.elapsedRealtime() - renewedAt > LEASE_MS) break;
                    try { helper.policy.update(helper.candidate()); }
                    catch (Exception e) {
                        Throwable cause = e;
                        while (cause.getCause() != null) cause = cause.getCause();
                        if (!(cause instanceof DeadObjectException)) throw e;
                        helper.policy.update(null); // Window died during lookup/callback; discover its replacement.
                    }
                    helper.status("running", helper.policy.active() ? "fullscreen" : "waiting-for-dex-fullscreen");
                    Thread.sleep(1000);
                }
            }
        } catch (Throwable e) {
            failed = true;
            // Stack traces contain framework method names, not collected app view contents.
            e.printStackTrace(System.err);
        } finally {
            if (helper != null) {
                try { helper.close(); }
                catch (Throwable e) { failed = true; e.printStackTrace(System.err); }
                try { if (helper.directory != null) helper.status(failed ? "failed" : "stopped",
                    failed ? "binder-or-framework-error" : "restored"); }
                catch (Exception e) { failed = true; e.printStackTrace(System.err); }
            }
        }
        System.exit(failed ? 1 : 0);
    }
}
