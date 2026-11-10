#!/data/data/com.termux/files/usr/bin/bash
# Reports, feature by feature, which Android app or permission the desktop is missing.
#   bash src/preflight.sh           check only
#   bash src/preflight.sh --grant   first grant what Shizuku can, as install.sh does
# STOP means the desktop cannot run, and the exit status is 2. WARN leaves the named feature off;
# the rest of the desktop still works.
set -uo pipefail
pm=${LIVECD_PREFLIGHT_PM:-/system/bin/pm}
sdcard=${LIVECD_PREFLIGHT_SDCARD:-/sdcard}
gpu=${LIVECD_PREFLIGHT_GPU:-/dev/kgsl-3d0}
shizuku=$HOME/.local/lib/shizuku
grant=
case ${1:-} in
    --grant) grant=1;;
    '') ;;
    *) echo 'Usage: bash preflight.sh [--grant]' >&2; exit 2;;
esac

rish() { RISH_APPLICATION_ID=com.termux RISH_PRESERVE_ENV=0 timeout 30 "$shizuku/rish" -c "$*" </dev/null; }
installed() { "$pm" path "$1" >/dev/null 2>&1; }
storage() { test -r "$sdcard/Android" && test -w "$sdcard/"; }

# Shizuku's rish is exported to shared storage, so finding it needs storage access first.
if test -n "$grant" && ! test -f "$shizuku/rish_shizuku.dex"; then
    if ! storage && command -v termux-setup-storage >/dev/null; then
        echo 'Allow storage access in the Android prompt.' >&2
        termux-setup-storage || true
        for _ in $(seq 60); do storage && break; sleep 1; done
    fi
    # find reports Android's unreadable app directories as a failure.
    exported=$(find "$sdcard/" -maxdepth 3 -name rish_shizuku.dex -printf '%h\n' 2>/dev/null | head -n 1 || true)
    if test -n "$exported" && test -f "$exported/rish"; then
        install -d -m 700 "$shizuku"
        install -m 700 "$exported/rish" "$shizuku/rish"
        install -m 400 "$exported/rish_shizuku.dex" "$shizuku/rish_shizuku.dex"
    fi
fi

# Shizuku answers as Android's shell user, which can grant permissions and read them back.
if ! installed moe.shizuku.privileged.api; then
    shell='Shizuku is not installed. Install Shizuku (or Shizuku+), start it, and run install.sh again.'
elif ! test -f "$shizuku/rish"; then
    shell='In Shizuku, choose "Use Shizuku in terminal apps", export the files to shared storage, and run install.sh again.'
else
    shell='Start Shizuku, allow Termux under its authorized applications, and run install.sh again.'
    # Shizuku+ may print a waiting notice first, and its first calls after a pause can return nothing.
    for _ in $(seq 10); do
        case $(rish id 2>/dev/null || true) in *uid=2000\(shell\)*) shell=; break;; esac
        sleep 2
    done
fi

if test -z "$shell" && test -n "$grant"; then
    # Termux:API shares Termux's user ID, so its permissions cover every desktop process.
    rish pm grant com.termux.api android.permission.RECORD_AUDIO
    rish pm grant com.termux.api android.permission.CAMERA
    # Android can withdraw the storage read permission on its own, as the app-op, so set both.
    for permission in READ_EXTERNAL_STORAGE WRITE_EXTERNAL_STORAGE; do
        rish pm grant com.termux android.permission.$permission
        rish appops set com.termux $permission allow
    done
    rish dumpsys deviceidle whitelist +com.termux >/dev/null
fi
if test -z "$shell"; then
    api=$(rish dumpsys package com.termux.api 2>/dev/null || true)
    idle=$(rish dumpsys deviceidle whitelist 2>/dev/null || true)
fi

stops=0 warnings=0
report() {  # LEVEL FEATURE [WHAT IS MISSING]
    case $1 in
        ok) printf '  ok    %s\n' "$2";;
        *) printf '  %-5s %s\n        %s\n' "$1" "$2" "$3"
           if test "$1" = STOP; then stops=$((stops + 1)); else warnings=$((warnings + 1)); fi;;
    esac
}
# FEATURE PERMISSION [SETTINGS NAME]: a Termux:API runtime permission, read back through Shizuku.
api_permission() {
    if ! installed com.termux.api; then
        report WARN "$1" 'needs the Termux:API app, from the same source as Termux.'
    elif test -n "$shell"; then
        report WARN "$1" "needs Termux:API's $2 permission, which Shizuku grants. $shell"
    elif ! grep -q "android.permission.$2: granted=true" <<<"$api"; then
        report WARN "$1" "needs Termux:API's $2 permission. Allow it in Android Settings > Apps > Termux:API > Permissions > $3."
    else
        report ok "$1"
    fi
}

echo 'Android requirements, by feature:'
if installed com.termux.x11; then
    report ok 'Desktop display (Termux:X11)'
else
    report STOP 'Desktop display' 'needs the Termux:X11 app, from the same source as Termux.'
fi
if test -e "$gpu"; then
    report ok 'GPU rendering and hardware video (Qualcomm Adreno)'
else
    report WARN 'GPU rendering and hardware video' 'need a Qualcomm Adreno GPU, which was not found; the desktop renders in software.'
fi
api_permission 'Phone microphone' RECORD_AUDIO Microphone
if test -n "$shell"; then
    report WARN 'Bluetooth headset microphone' "needs Shizuku, which routes Android's call audio. $shell"
elif ! grep -q 'android.permission.RECORD_AUDIO: granted=true' <<<"$api"; then
    report WARN 'Bluetooth headset microphone' "needs Termux:API's RECORD_AUDIO permission, as the phone microphone does."
else
    report ok 'Bluetooth headset microphone (pair the headset in Android with Calls enabled)'
fi
api_permission 'Front and rear cameras' CAMERA Camera
if installed com.termux.api; then
    report ok 'Battery status'
else
    report WARN 'Battery status' 'needs the Termux:API app, from the same source as Termux.'
fi
if storage; then
    report ok 'Internal storage, SD card and USB drives in Files'
else
    report WARN 'Internal storage, SD card and USB drives in Files' \
        "need Termux's storage permission. Run termux-setup-storage and allow access, or run install.sh again with Shizuku."
fi
if test -n "$shell"; then
    report WARN 'Whole-device CPU and processes in Mission Center' "needs Shizuku. $shell"
else
    report ok 'Whole-device CPU and processes in Mission Center'
fi
if test -n "$shell"; then
    report WARN 'Desktop keeps running in the background' "needs Termux exempt from battery optimization, which Shizuku sets. $shell"
elif ! grep -q ',com\.termux,' <<<"$idle"; then
    report WARN 'Desktop keeps running in the background' \
        'needs Termux exempt from battery optimization. Set Android Settings > Apps > Termux > Battery to Unrestricted.'
else
    report ok 'Desktop keeps running in the background'
fi
if test "$stops" -gt 0; then
    echo "The desktop cannot run until the STOP item above is fixed."
    exit 2
elif test "$warnings" -gt 0; then
    echo "$warnings feature(s) stay off until fixed; the rest of the desktop works. Check again: bash src/preflight.sh"
fi
