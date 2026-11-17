// Print every MediaCodec's run-time capabilities as JSON lines.
// Build: javac -source 8 -target 8 -classpath $ANDROID_HOME/platforms/android-36/android.jar CodecInfo.java
//        d8 --min-api 29 --lib $ANDROID_HOME/platforms/android-36/android.jar CodecInfo.class
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
                if (!t.startsWith("video/") && !t.startsWith("image/")) continue;
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
                // Added 2026-11-16 for the Adreno parity matrix; older dumps lack these keys.
                for (String f : new String[]{"partial-frame", "frame-parsing", "multiple-frames", "dynamic-timestamp", "intra-refresh"})
                    s.append(",\"" + f + "\":" + c.isFeatureSupported(f));
                s.append(",\"vendor\":" + i.isVendor() + ",\"softwareOnly\":" + i.isSoftwareOnly() + ",\"alias\":" + i.isAlias()
                    + ",\"canonical\":\"" + i.getCanonicalName() + "\",\"maxInstances\":" + c.getMaxSupportedInstances());
                if (v != null) {
                    s.append(",\"fps1080\":" + (v.isSizeSupported(1920, 1080) ? r(v.getSupportedFrameRatesFor(1920, 1080)) : "null")
                        + ",\"achievable1080\":" + (v.isSizeSupported(1920, 1080) ? r(v.getAchievableFrameRatesFor(1920, 1080)) : "null")
                        + ",\"achievable2160\":" + (v.isSizeSupported(3840, 2160) ? r(v.getAchievableFrameRatesFor(3840, 2160)) : "null")
                        + ",\"performancePoints\":[");
                    java.util.List<MediaCodecInfo.VideoCapabilities.PerformancePoint> pp = v.getSupportedPerformancePoints();
                    if (pp != null) for (int k = 0; k < pp.size(); k++) s.append(k > 0 ? "," : "").append("\"" + pp.get(k) + "\"");
                    s.append("]");
                }
                MediaCodecInfo.EncoderCapabilities e = c.getEncoderCapabilities();
                if (e != null) s.append(",\"cbr\":" + e.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR)
                    + ",\"vbr\":" + e.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR)
                    + ",\"cq\":" + e.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CQ)
                    + ",\"complexity\":" + r(e.getComplexityRange()) + ",\"quality\":" + r(e.getQualityRange()));
                System.out.println(s.append("}"));
            }
        }
    }
}
