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
adb logcat -c
adb shell am start -W -n com.jadeite.mobile/.MainActivity
sleep 8
adb exec-out screencap -p > "$OUT/01_launch.png"
PID=$(adb shell pidof com.jadeite.mobile | tr -d '\r')
adb forward tcp:9222 "localabstract:webview_devtools_remote_$PID"
node mobile/tests/device.mjs "$OUT"
RC=$?
adb logcat -d > "$OUT/logcat.txt"
grep -E "FATAL EXCEPTION|AndroidRuntime: " "$OUT/logcat.txt" > "$OUT/crashes.txt" || true
grep -E "chromium.*(Uncaught|ERROR:CONSOLE)" "$OUT/logcat.txt" > "$OUT/js_errors.txt" || true
if [ -s "$OUT/crashes.txt" ]; then echo "crash in logcat"; RC=1; fi
exit $RC
