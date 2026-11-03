#!/usr/bin/env bash
# أندرويد 15 (API 35): التطبيق بـ targetSdk 36 يُرسم تحت شريطي النظام — يُثبَّت ويُفتح،
# ثم صورٌ للرئيسية ولشاشة إدخالٍ بلوحة المفاتيح، وفحصٌ أن الصفحة لا تبدأ تحت شريط
# الحالة وأن لا انهيار. يُستدعى من android.yml بعد التجربة الكاملة (API 33).
set -u
OUT="${OUT:-device-out}/edge"
mkdir -p "$OUT"
APK=mobile/android/app/build/outputs/apk/direct/debug/app-direct-debug.apk
adb install -r "$APK" > "$OUT/install.txt" 2>&1 || { cat "$OUT/install.txt"; exit 1; }
adb logcat -c
# يُفتح التطبيق (ومن جديد إن أغلقه أندرويد مع إعادة تشغيل خدمات Google على المحاكي)
PID=""
for i in 1 2 3; do
  adb shell am start -W -n com.jadeite.mobile/.MainActivity --ez aurUiTesting true
  sleep 8
  PID=$(adb shell pidof com.jadeite.mobile | tr -d '\r')
  [ -n "$PID" ] && break
done
adb exec-out screencap -p > "$OUT/01_launch.png"
[ -n "$PID" ] || { echo "app not running"; exit 1; }
adb forward tcp:9223 "localabstract:webview_devtools_remote_$PID"
node mobile/tests/edge.mjs "$OUT"
RC=$?
adb logcat -d > "$OUT/logcat.txt"
grep -E "FATAL EXCEPTION| E AndroidRuntime" "$OUT/logcat.txt" > "$OUT/crashes.txt" || true
if [ -s "$OUT/crashes.txt" ]; then echo "crash in logcat"; cat "$OUT/crashes.txt"; RC=1; fi
exit $RC
