package org.livecd.dexfullscreen;

import java.io.IOException;
import java.util.concurrent.TimeoutException;

/** A window can disappear between enumeration, inspection, and its callback. */
final class WindowPoller {
    interface Lookup { WindowPolicy.Target candidate() throws Exception; }
    private final WindowPolicy policy;

    WindowPoller(WindowPolicy policy) { this.policy = policy; }

    static boolean retryable(Exception error) {
        Throwable cause = error;
        while (cause.getCause() != null) cause = cause.getCause();
        return cause instanceof IOException || cause instanceof TimeoutException;
    }

    boolean poll(Lookup lookup) throws Exception {
        try {
            policy.update(lookup.candidate());
            return true;
        } catch (Exception error) {
            if (!retryable(error)) throw error;
            // An unreadable window is ineligible until a fresh lookup succeeds.
            // If restoration also fails, retain ownership and retry next poll.
            try { policy.restore(); }
            catch (Exception restore) { if (!retryable(restore)) throw restore; }
            return false;
        }
    }
}
