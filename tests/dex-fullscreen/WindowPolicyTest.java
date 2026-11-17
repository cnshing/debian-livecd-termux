package org.livecd.dexfullscreen;

public final class WindowPolicyTest {
    static void require(boolean condition) { if (!condition) throw new AssertionError(); }
    static boolean eligible(String dump, int display) {
        return WindowState.eligible(dump, display, 0, 0, 1920, 1080);
    }
    static final class Fake implements WindowPolicy.Target {
        int bits;
        boolean alive = true;
        Fake(int bits) { this.bits = bits; }
        public boolean alive() { return alive; }
        public int flags() { return bits; }
        public void apply(int value, int mask) { bits = (bits & ~mask) | (value & mask); }
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
