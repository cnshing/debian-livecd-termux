package org.livecd.dexfullscreen;

public final class WindowPolicyTest {
    static void require(boolean condition) { if (!condition) throw new AssertionError(); }
    static boolean eligible(String dump, int display) {
        return WindowState.eligible(dump, display, 0, 0, 1920, 1080);
    }
    static final class Fake implements WindowPolicy.Target {
        int bits;
        boolean alive = true;
        boolean failApply;
        boolean failRead;
        Fake(int bits) { this.bits = bits; }
        public boolean alive() { return alive; }
        public int flags() throws Exception {
            if (failRead) throw new java.io.IOException("Incomplete root view dump");
            return bits;
        }
        public void apply(int value, int mask) throws Exception {
            if (failApply) throw new java.io.IOException("Window callback temporarily unavailable");
            bits = (bits & ~mask) | (value & mask);
        }
    }
    public static void main(String[] args) throws Exception {
        WindowPolicy policy = new WindowPolicy();
        Fake first = new Fake(0x700);
        policy.update(first);
        require(first.bits == 0x1702);
        first.bits |= 0x4000; // An unrelated app flag changed while active.
        policy.update(null);
        require(first.bits == 0x4700 && !policy.active());

        Fake partial = new Fake(2); // Preserve a pre-existing navigation-hide bit.
        policy.update(partial);
        partial.bits = 2; // App reset; the next poll reapplies the missing sticky bit.
        policy.update(partial);
        require(partial.bits == 0x1002);
        Fake replacement = new Fake(0);
        policy.update(replacement);
        require(partial.bits == 2 && replacement.bits == 0x1002);
        replacement.alive = false; // A destroyed window must not prevent a new one.
        policy.update(first);
        require(first.bits == 0x5702);
        policy.restore();
        require(first.bits == 0x4700);

        Fake original = new Fake(0x1002);
        policy.update(original);
        policy.restore();
        require(original.bits == 0x1002);

        WindowPoller poller = new WindowPoller(policy);
        Fake focused = new Fake(0);
        require(poller.poll(() -> focused));
        // A focus transition can race a root-view dump or window inspection.
        require(!poller.poll(() -> { throw new java.io.IOException("Incomplete root dump"); }));
        require(!policy.active() && focused.bits == 0);
        require(!poller.poll(() -> { throw new java.util.concurrent.TimeoutException(); }));
        require(poller.poll(() -> focused));
        require(policy.active() && focused.bits == 0x1002);
        // A failed restore must retain ownership and block switching targets.
        focused.failApply = true;
        Fake next = new Fake(0);
        require(!poller.poll(() -> next));
        require(policy.active() && next.bits == 0);
        focused.failApply = false;
        require(poller.poll(() -> next));
        require(focused.bits == 0 && next.bits == 0x1002);
        require(poller.poll(() -> null));
        require(next.bits == 0 && !policy.active());
        next.failRead = true;
        require(!poller.poll(() -> next));
        require(!policy.active() && next.bits == 0);
        next.failRead = false;
        for (int i = 0; i < 100; i++) {
            require(poller.poll(() -> next));
            require(next.bits == 0x1002);
            require(poller.poll(() -> null));
            require(next.bits == 0);
        }
        // Permission/framework errors still surface instead of silently looping.
        try {
            poller.poll(() -> { throw new SecurityException("Permission revoked"); });
            throw new AssertionError("Permission failure was hidden");
        } catch (SecurityException expected) { }

        String window = "  Window #0 Window{abcd u0 com.termux.x11/com.termux.x11.MainActivity}:\n"
            + "    mDisplayId=2 rootTaskId=806\n"
            + "    mOwnerUid=10312 showForAllUsers=false package=com.termux.x11 appop=NONE\n"
            + "    mAttrs={(0,0)(fillxfill) ty=BASE_APPLICATION\n      fl=81810500\n      pfl=12020000}\n"
            + "    mFrame=[0,0][1920,1080] last=[0,0][1920,1080]\n"
            + "    mViewVisibility=0x0 mHaveFrame=true\n"
            + "    mFullConfiguration={winConfig={mWindowingMode=fullscreen mDisplayWindowingMode=freeform} desktop/e dc/d}\n";
        require(eligible(window, 2));
        require(!eligible(window, 0));
        require(!eligible(window, 3));
        require(!eligible(window.replace("81810500", "81810100"), 2));
        require(!eligible(window.replace("desktop/e", "desktop/d"), 2));
        require(!eligible(window.replace("mWindowingMode=fullscreen", "mWindowingMode=freeform"), 2));
        require(!eligible(window.replace("mViewVisibility=0x0", "mViewVisibility=0x8"), 2));
        require(!eligible(window.replace("com.termux.x11", "other.package"), 2));
        require(!eligible(window.replace("fl=81810500", "fl=unknown"), 2));
        require(!eligible(window + window.replace("#0", "#1"), 2));
        require(!eligible("", 2));
        require(!WindowState.eligible(window, 2, 300, 200, 1200, 900));
        System.out.println("Window policy and Samsung eligibility checks passed");
    }
}
