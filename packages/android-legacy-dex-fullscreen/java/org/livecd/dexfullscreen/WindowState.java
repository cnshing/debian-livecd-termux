package org.livecd.dexfullscreen;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Parse the verified API-30 Samsung window dump; missing/ambiguous data refuses eligibility. */
final class WindowState {
    private static final Pattern DISPLAY = Pattern.compile("mDisplayId=(\\d+)\\b");
    private static final Pattern FLAGS = Pattern.compile("(?m)^\\s+fl=([0-9a-fA-F]+)\\s*$");
    private static final Pattern CONFIG = Pattern.compile("(?m)^\\s+mFullConfiguration=([^\\n]+)");
    private static final Pattern FRAME = Pattern.compile("(?m)^\\s+mFrame=\\[(-?\\d+),(-?\\d+)\\]\\[(-?\\d+),(-?\\d+)\\]");
    private static final String APP = "com.termux.x11";

    static boolean eligible(String dump, int display, int left, int top, int right, int bottom) {
        if (display <= 0 || right <= left || bottom <= top) return false;
        int matches = 0;
        boolean result = false;
        for (String block : dump.split("(?m)^  Window #")) {
            Matcher d = DISPLAY.matcher(block);
            Matcher f = FLAGS.matcher(block);
            Matcher c = CONFIG.matcher(block);
            Matcher frame = FRAME.matcher(block);
            if (!block.contains("package=" + APP + " ") || !block.contains("ty=BASE_APPLICATION")
                    || !block.contains("mViewVisibility=0x0 ") || !d.find()
                    || Integer.parseInt(d.group(1)) != display) continue;
            matches++;
            if (!f.find() || !c.find() || !frame.find()) continue;
            if (Integer.parseInt(frame.group(1)) != left || Integer.parseInt(frame.group(2)) != top
                    || Integer.parseInt(frame.group(3)) != right || Integer.parseInt(frame.group(4)) != bottom) continue;
            String config = c.group(1);
            long flags = Long.parseLong(f.group(1), 16);
            result = (flags & 0x400) != 0 && config.contains("mWindowingMode=fullscreen")
                && config.contains("desktop/e");
        }
        return matches == 1 && result;
    }
}
