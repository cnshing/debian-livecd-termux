// Print every MediaCodec's run-time capabilities as JSON lines.
// Build: javac -source 8 -target 8 -classpath $ANDROID_HOME/platforms/android-36/android.jar CodecInfo.java
//        d8 --min-api 24 --lib $ANDROID_HOME/platforms/android-36/android.jar CodecInfo.class
// Run:   adb push classes.dex /data/local/tmp/codec-info.dex
//        adb shell CLASSPATH=/data/local/tmp/codec-info.dex app_process / CodecInfo
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.util.Range;

public class CodecInfo {
    static String r(Range<?> x) { return x == null ? "null" : "\"" + x.getLower() + "-" + x.getUpper() + "\""; }
    public static void main(String[] a) {
        for (MediaCodecInfo i : new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
            for (String t : i.getSupportedTypes()) {
                if (!t.startsWith("video/")) continue;
                MediaCodecInfo.CodecCapabilities c = i.getCapabilitiesForType(t);
                StringBuilder s = new StringBuilder("{\"name\":\"" + i.getName() + "\",\"type\":\"" + t
                    + "\",\"encoder\":" + i.isEncoder() + ",\"hardware\":" + i.isHardwareAccelerated() + ",\"profiles\":[");
                for (int k = 0; k < c.profileLevels.length; k++)
                    s.append(k > 0 ? "," : "").append("[" + c.profileLevels[k].profile + "," + c.profileLevels[k].level + "]");
                s.append("],\"colorFormats\":[");
                for (int k = 0; k < c.colorFormats.length; k++) s.append(k > 0 ? "," : "").append(c.colorFormats[k]);
                s.append("]");
                MediaCodecInfo.VideoCapabilities v = c.getVideoCapabilities();
                if (v != null) s.append(",\"widths\":" + r(v.getSupportedWidths()) + ",\"heights\":" + r(v.getSupportedHeights())
                    + ",\"fps\":" + r(v.getSupportedFrameRates()) + ",\"bitrate\":" + r(v.getBitrateRange())
                    + ",\"fps2160\":" + (v.isSizeSupported(3840, 2160) ? r(v.getSupportedFrameRatesFor(3840, 2160)) : "null")
                    + ",\"fps4320\":" + (v.isSizeSupported(7680, 4320) ? r(v.getSupportedFrameRatesFor(7680, 4320)) : "null"));
                for (String f : new String[]{"adaptive-playback", "low-latency", "tunneled-playback", "secure-playback"})
                    s.append(",\"" + f + "\":" + c.isFeatureSupported(f));
                System.out.println(s.append("}"));
            }
        }
    }
}
