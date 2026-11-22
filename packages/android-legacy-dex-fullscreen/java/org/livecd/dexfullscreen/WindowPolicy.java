package org.livecd.dexfullscreen;

/** Own only the bits absent before activation; never restore an entire flags word. */
final class WindowPolicy {
    static final int MASK = 0x1002;
    interface Target {
        boolean alive();
        int flags() throws Exception;
        void apply(int value, int mask) throws Exception;
    }
    private Target target;
    private int owned;

    boolean active() { return target != null; }

    void update(Target next) throws Exception {
        if (target != null && !target.equals(next)) restore();
        if (next == null) return;
        if (target == null) {
            int original = next.flags();
            owned = MASK & ~original;
            target = next;
        }
        // A masked callback is a no-op in View when the bits already match.
        target.apply(MASK, MASK);
    }

    void restore() throws Exception {
        Target old = target;
        int mask = owned;
        // Keep ownership until the callback succeeds so a transient Binder failure
        // can be retried before activating another window.
        if (old != null && mask != 0 && old.alive()) old.apply(0, mask);
        target = null;
        owned = 0;
    }
}
