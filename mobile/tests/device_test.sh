#!/usr/bin/env bash
# يثبّت نسخة الاختبار على المحاكي ويشغّل device.mjs — يُستدعى من android.yml
set -u
OUT="${OUT:-device-out}"
mkdir -p "$OUT"
APK=mobile/android/app/build/outputs/apk/debug/app-debug.apk
if ! adb install -r "$APK" > "$OUT/install.txt" 2>&1; then
  echo '{"failed":1,"results":[{"name":"install","ok":false}]}' > "$OUT/result.json"
  cat "$OUT/install.txt"
  exit 1
fi
# إذن الإشعارات (أندرويد 13) يُمنح مسبقاً كما لو ضغط صاحبه «سماح»؛ ومجلد Documents
# هو حيث تفتح نافذة اختيار مجلد الحفظ التلقائي
adb shell pm grant com.jadeite.mobile android.permission.POST_NOTIFICATIONS || true
adb shell mkdir -p /sdcard/Documents
export APK
# تجربة التنزيل: الملف غير الموقّع الذي نُشر للتوّ وبصمته
export UNSIGNED_URL="https://github.com/${GITHUB_REPOSITORY:-wwwrag80-create/gold_erp}/releases/download/mobile-unsigned/jadeite-mobile-unsigned.apk"
export UNSIGNED_SHA="$(cut -d' ' -f1 jadeite-mobile-unsigned.apk.sha256 2>/dev/null)"
adb logcat -c
adb shell am start -W -n com.jadeite.mobile/.MainActivity
sleep 8
adb exec-out screencap -p > "$OUT/01_launch.png"
PID=$(adb shell pidof com.jadeite.mobile | tr -d '\r')
adb forward tcp:9222 "localabstract:webview_devtools_remote_$PID"
node mobile/tests/device.mjs "$OUT"
RC=$?
adb logcat -d > "$OUT/logcat.txt"
# الانهيار الحقيقي وحده — «I AndroidRuntime: VM exiting» سطرٌ عادي من أوامر adb
grep -E "FATAL EXCEPTION| E AndroidRuntime" "$OUT/logcat.txt" > "$OUT/crashes.txt" || true
grep -E "SecurityException.*com\.jadeite" "$OUT/logcat.txt" > "$OUT/security.txt" || true
grep -E "chromium.*(Uncaught|ERROR:CONSOLE)" "$OUT/logcat.txt" > "$OUT/js_errors.txt" || true
if [ -s "$OUT/crashes.txt" ]; then echo "crash in logcat"; RC=1; fi
if [ -s "$OUT/security.txt" ]; then echo "permission denial in logcat"; cat "$OUT/security.txt"; RC=1; fi
exit $RC
