#!/usr/bin/env bash
# إحصاءات الاستخدام على جهاز أندرويد حقيقي (محاكٍ): النسخة التجريبية ترسل إلى موقع التجربة فعلاً؟
# يُستدعى من android.yml بعد device_test.sh — للتشخيص فقط، ولا يغيّر نتيجة التجربة.
set -u
OUT="${OUT:-device-out}"
mkdir -p "$OUT"
APK=mobile/android/app/build/outputs/apk/play/trial/app-play-trial.apk
PKG=com.jadeite.mobile.trial
adb install -r "$APK" > "$OUT/stats_install.txt" 2>&1 || { cat "$OUT/stats_install.txt"; exit 0; }
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS || true
adb shell am start -W -n "$PKG/com.jadeite.mobile.MainActivity" >/dev/null
sleep 12
PID=$(adb shell pidof $PKG | tr -d '\r')
adb forward --remove-all
adb forward tcp:9223 "localabstract:webview_devtools_remote_$PID"
PKG=$PKG node mobile/tests/device_stats.mjs "$OUT" || true
exit 0
