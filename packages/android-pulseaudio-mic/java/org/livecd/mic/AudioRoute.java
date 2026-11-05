package org.livecd.mic;

import android.Manifest;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothHeadset;
import android.bluetooth.BluetoothProfile;
import android.content.AttributionSource;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.pm.PackageManager;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.net.Socket;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Shell-only routing companion. PCM stays in Termux's native PulseAudio. */
public final class AudioRoute {
    private final AudioManager audio;
    private final Context context;
    private final Socket socket;
    private final PrintWriter out;
    private final CountDownLatch connected = new CountDownLatch(1);
    private volatile boolean ready;
    private volatile String lost;
    private boolean requestedMode;
    private boolean requestedRoute;
    private AudioDeviceInfo selected;
    private BluetoothAdapter adapter;
    private volatile BluetoothHeadset headset;
    private BluetoothDevice headsetDevice;
    private boolean requestedVoiceRecognition;
    private final boolean canSetAudio;

    // app_process has no Application. Attribute requests to the actual shell UID/package.
    private static final class ShellContext extends ContextWrapper {
        ShellContext(Context base) { super(base); }
        @Override public String getPackageName() { return "com.android.shell"; }
        @Override public String getOpPackageName() { return "com.android.shell"; }
        @Override public Context getApplicationContext() { return this; }
        @Override public AttributionSource getAttributionSource() {
            return new AttributionSource.Builder(Process.myUid())
                    .setPackageName("com.android.shell").build();
        }
    }

    private AudioRoute(Context context, Socket socket) throws Exception {
        this.context = context;
        this.socket = socket;
        // getSystemService() on the system context would cache an AudioManager with
        // the wrong attribution. The Context constructor is hidden, so reflect it.
        audio = AudioManager.class.getConstructor(Context.class).newInstance(context);
        canSetAudio = context.checkPermission(Manifest.permission.MODIFY_AUDIO_SETTINGS,
                Process.myPid(), Process.myUid()) == PackageManager.PERMISSION_GRANTED;
        out = new PrintWriter(new OutputStreamWriter(socket.getOutputStream(), "UTF-8"), true);
    }

    private List<AudioDeviceInfo> devices() {
        if (Build.VERSION.SDK_INT >= 31) return audio.getAvailableCommunicationDevices();
        List<AudioDeviceInfo> result = new ArrayList<>();
        for (AudioDeviceInfo device : audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
            if (device.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) result.add(device);
        }
        return result;
    }

    private static boolean bluetooth(AudioDeviceInfo device) {
        return device.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_SCO
                || (Build.VERSION.SDK_INT >= 31
                    && device.getType() == AudioDeviceInfo.TYPE_BLE_HEADSET);
    }

    private static JSONObject describe(AudioDeviceInfo device) throws Exception {
        return new JSONObject().put("id", device.getId()).put("type", device.getType())
                .put("name", device.getProductName().toString());
    }

    private JSONObject status() throws Exception {
        JSONArray devices = new JSONArray();
        for (AudioDeviceInfo device : devices()) {
            if (bluetooth(device)) devices.put(describe(device));
        }
        JSONObject result = new JSONObject().put("sdk", Build.VERSION.SDK_INT)
                .put("audio_mode", audio.getMode()).put("sco_on", audio.isBluetoothScoOn())
                .put("can_set_audio_settings", canSetAudio)
                .put("bluetooth_devices", devices);
        if (Build.VERSION.SDK_INT >= 31 && audio.getCommunicationDevice() != null) {
            result.put("communication_device", describe(audio.getCommunicationDevice()));
        }
        return result;
    }

    private synchronized void send(JSONObject message) { out.println(message.toString()); }

    private void routeLost(String reason) {
        lost = reason;
        connected.countDown();
        if (!ready) return;
        try {
            send(new JSONObject().put("event", "lost").put("error", reason));
            // Wake the reader so its finally block releases our Binder requests.
            socket.shutdownInput();
        } catch (Exception ignored) { }
    }

    private void enable(int deviceId) throws Exception {
        if (audio.getMode() != AudioManager.MODE_NORMAL || audio.isBluetoothScoOn()) {
            throw new IllegalStateException("Android audio is already in a call or using SCO");
        }
        List<AudioDeviceInfo> candidates = new ArrayList<>();
        for (AudioDeviceInfo device : devices()) {
            if (bluetooth(device) && (deviceId == 0 || device.getId() == deviceId)) {
                candidates.add(device);
            }
        }
        if (candidates.size() != 1) {
            throw new IllegalStateException(candidates.isEmpty()
                    ? "No matching Bluetooth call device; connect a headset with Calls enabled"
                    : "More than one Bluetooth call device; select one with --device ID");
        }
        selected = candidates.get(0);
        if (!canSetAudio) {
            if (Build.VERSION.SDK_INT >= 31) {
                throw new SecurityException("Shell lacks MODIFY_AUDIO_SETTINGS on this Android build");
            }
            enableHeadsetProfile();
            return;
        }
        if (Build.VERSION.SDK_INT >= 31) {
            audio.addOnModeChangedListener(
                    command -> new Handler(Looper.getMainLooper()).post(command), mode -> {
                        if (ready && mode != AudioManager.MODE_IN_COMMUNICATION) {
                            routeLost("Another Android audio mode replaced this session");
                        }
                    });
            audio.addOnCommunicationDeviceChangedListener(
                    command -> new Handler(Looper.getMainLooper()).post(command), device -> {
                        if (device != null && device.getId() == selected.getId()) {
                            connected.countDown();
                        } else if (ready) {
                            routeLost("Android changed the communication device");
                        }
                    });
        }
        requestedMode = true;
        audio.setMode(AudioManager.MODE_IN_COMMUNICATION);
        requestedRoute = true;
        if (Build.VERSION.SDK_INT >= 31) {
            if (!audio.setCommunicationDevice(selected)) {
                throw new IllegalStateException("Android rejected the communication device");
            }
            if (audio.getCommunicationDevice() != null
                    && audio.getCommunicationDevice().getId() == selected.getId()) {
                connected.countDown();
            }
        } else {
            // API <31 cannot select an HFP address; Android owns its active headset.
            if (deviceId != 0 && devices().size() != 1) {
                throw new IllegalStateException("This Android version cannot select between headsets");
            }
            audio.startBluetoothSco();
            // app_process is not an AMS-registered application and cannot register
            // a Context BroadcastReceiver. Older AudioManager exposes no route
            // listener, so bound this wait and poll only while a route is held.
            long deadline = android.os.SystemClock.elapsedRealtime() + 8000;
            while (!audio.isBluetoothScoOn()
                    && android.os.SystemClock.elapsedRealtime() < deadline) {
                Thread.sleep(100);
            }
            if (!audio.isBluetoothScoOn()) throw new IllegalStateException("Bluetooth SCO timed out");
            connected.countDown();
        }
        if (!connected.await(8, TimeUnit.SECONDS) || lost != null) {
            throw new IllegalStateException(lost != null ? lost : "Bluetooth route timed out");
        }
        if (audio.getMode() != AudioManager.MODE_IN_COMMUNICATION) {
            throw new IllegalStateException("Android did not grant communication mode");
        }
        if (Build.VERSION.SDK_INT >= 31 && (audio.getCommunicationDevice() == null
                || audio.getCommunicationDevice().getId() != selected.getId())) {
            throw new IllegalStateException("Android selected a different communication device");
        }
        reportReady("audio-manager");
    }

    private void enableHeadsetProfile() throws Exception {
        adapter = BluetoothAdapter.getDefaultAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            throw new IllegalStateException("Bluetooth is disabled");
        }
        CountDownLatch profileReady = new CountDownLatch(1);
        if (!adapter.getProfileProxy(context, new BluetoothProfile.ServiceListener() {
            @Override public void onServiceConnected(int profile, BluetoothProfile proxy) {
                headset = (BluetoothHeadset) proxy;
                profileReady.countDown();
            }
            @Override public void onServiceDisconnected(int profile) {
                routeLost("Bluetooth headset service disconnected");
            }
        }, BluetoothProfile.HEADSET) || !profileReady.await(5, TimeUnit.SECONDS)) {
            throw new IllegalStateException("Bluetooth headset profile service unavailable");
        }
        List<BluetoothDevice> connectedDevices = headset.getConnectedDevices();
        if (connectedDevices.size() != 1) {
            throw new IllegalStateException("Legacy profile routing requires exactly one connected headset");
        }
        headsetDevice = connectedDevices.get(0);
        if (Build.VERSION.SDK_INT >= 28 && !selected.getAddress().equals(headsetDevice.getAddress())) {
            throw new IllegalStateException("Android's active headset differs from the selected device");
        }
        if (headset.isAudioConnected(headsetDevice)) {
            throw new IllegalStateException("Headset audio is already in use");
        }
        if (!headset.startVoiceRecognition(headsetDevice)) {
            throw new IllegalStateException("Headset rejected the voice-recognition audio connection");
        }
        requestedVoiceRecognition = true;
        long deadline = android.os.SystemClock.elapsedRealtime() + 8000;
        while ((!headset.isAudioConnected(headsetDevice) || !audio.isBluetoothScoOn())
                && android.os.SystemClock.elapsedRealtime() < deadline) {
            Thread.sleep(100);
        }
        if (!headset.isAudioConnected(headsetDevice) || !audio.isBluetoothScoOn()) {
            throw new IllegalStateException("Headset audio connection or SCO recording route timed out");
        }
        reportReady("headset-voice-recognition");
    }

    private void reportReady(String backend) throws Exception {
        ready = true;
        send(status().put("event", "ready").put("backend", backend)
                .put("selected_device", describe(selected)));
        if (Build.VERSION.SDK_INT < 31) {
            new Thread(() -> {
                try {
                    while (ready) {
                        Thread.sleep(250);
                        int expectedMode = requestedMode ? AudioManager.MODE_IN_COMMUNICATION
                                : AudioManager.MODE_NORMAL;
                        if (ready && (!audio.isBluetoothScoOn() || audio.getMode() != expectedMode
                                || (requestedVoiceRecognition
                                    && !headset.isAudioConnected(headsetDevice)))) {
                            routeLost("Android ended or replaced the Bluetooth call route");
                            return;
                        }
                    }
                } catch (Exception error) {
                    routeLost("Bluetooth route monitor failed: " + error);
                }
            }, "livecd-route-monitor").start();
        }
    }

    private void cleanup() {
        ready = false;
        if (requestedVoiceRecognition && headset != null) {
            try { headset.stopVoiceRecognition(headsetDevice); } catch (Exception ignored) { }
        }
        if (headset != null && adapter != null) {
            try { adapter.closeProfileProxy(BluetoothProfile.HEADSET, headset); } catch (Exception ignored) { }
        }
        // These release this AudioManager's Binder token, not another app's request.
        if (requestedRoute) {
            try {
                if (Build.VERSION.SDK_INT >= 31) audio.clearCommunicationDevice();
                else audio.stopBluetoothSco();
            } catch (Exception ignored) { }
        }
        if (requestedMode) {
            try { audio.setMode(AudioManager.MODE_NORMAL); } catch (Exception ignored) { }
        }
    }

    private void serve() {
        try {
            socket.setSoTimeout(15000);
            BufferedReader input = new BufferedReader(
                    new InputStreamReader(socket.getInputStream(), "UTF-8"));
            String line = input.readLine();
            if (line == null) return;
            JSONObject request = new JSONObject(line);
            if ("devices".equals(request.getString("command"))) {
                send(status().put("event", "devices"));
                return;
            }
            if (!"enable".equals(request.getString("command"))) {
                throw new IllegalArgumentException("Unknown route command");
            }
            enable(request.optInt("device_id", 0));
            socket.setSoTimeout(0);
            input.readLine(); // stop or EOF: the native controller owns this session.
        } catch (Exception error) {
            try {
                send(new JSONObject().put("event", "error").put("error", error.toString()));
            } catch (Exception ignored) { }
        } finally {
            cleanup();
            try { socket.close(); } catch (Exception ignored) { }
            System.exit(0);
        }
    }

    private static void run(String[] args) throws Exception {
        if (Process.myUid() != 2000) throw new SecurityException("Run through ADB/Shizuku shell");
        if (args.length != 2) throw new IllegalArgumentException("Expected loopback port and one-use token");
        Looper.prepareMainLooper();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context system = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        Socket socket = new Socket("127.0.0.1", Integer.parseInt(args[0]));
        socket.getOutputStream().write((args[1] + "\n").getBytes("US-ASCII"));
        AudioRoute route = new AudioRoute(new ShellContext(system), socket);
        new Thread(route::serve, "android-pulseaudio-route").start();
        Looper.loop();
    }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Throwable error) {
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
