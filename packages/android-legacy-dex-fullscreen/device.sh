#!/system/bin/sh
# Installer and runtime use the same firmware/ABI gate. No privileges required.
getprop=${ANDROID_LEGACY_DEX_GETPROP:-/system/bin/getprop}
test "$("$getprop" ro.product.manufacturer 2>/dev/null | tr '[:upper:]' '[:lower:]')" = samsung &&
    test "$("$getprop" ro.build.version.sdk 2>/dev/null)" = 30 &&
    test "$("$getprop" ro.product.cpu.abi 2>/dev/null)" = arm64-v8a
