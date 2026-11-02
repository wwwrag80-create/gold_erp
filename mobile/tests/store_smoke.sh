#!/usr/bin/env bash
# نسخة المتاجر (play — ملف APK لمتجر شاومي وغيره): تُوقَّع بمفتاح التجربة، وتُثبَّت وتفتح على المحاكي،
# ويُتحقّق أنها تعمل بلا انهيار، وبلا إذن تثبيت. الشبكة مطفأة طوال التجربة: نسخة الإصدار تحمل
# معرّفات AdMob الحقيقية، فلا يُطلب منها إعلانٌ من جهاز تجربة أبداً. يُستدعى من android.yml.
set -u
OUT="${OUT:-device-out}/store"
mkdir -p "$OUT"
U=mobile/android/app/build/outputs/apk/play/release/app-play-release-unsigned.apk
BT=$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)
KS="$HOME/.android/debug.keystore"
[ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -storepass android -alias androiddebugkey -keypass android \
  -dname "CN=Android Debug,O=Android,C=US" -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$OUT/store-test.apk" "$U" || { echo "✘ store APK: signing for the test failed"; exit 1; }
adb shell svc wifi disable || true
adb shell svc data disable || true
sleep 2
adb uninstall com.jadeite.mobile >/dev/null 2>&1 || true
if ! adb install -r "$OUT/store-test.apk" > "$OUT/install.txt" 2>&1; then
  echo "✘ store APK: install failed"; cat "$OUT/install.txt"; exit 1
fi
adb logcat -c
adb shell am start -W -n com.jadeite.mobile/.MainActivity
sleep 12
adb exec-out screencap -p > "$OUT/launch.png"
PID=$(adb shell pidof com.jadeite.mobile | tr -d '\r')
adb logcat -d > "$OUT/logcat.txt"
grep -E "FATAL EXCEPTION| E AndroidRuntime" "$OUT/logcat.txt" > "$OUT/crashes.txt" || true
adb shell dumpsys package com.jadeite.mobile > "$OUT/package.txt"
RC=0
if [ -n "$PID" ]; then echo "✔ store APK: running (pid $PID)"; else echo "✘ store APK: not running"; RC=1; fi
if [ -s "$OUT/crashes.txt" ]; then echo "✘ store APK: crash"; cat "$OUT/crashes.txt"; RC=1; else echo "✔ store APK: no crash"; fi
if grep -q "REQUEST_INSTALL_PACKAGES" "$OUT/package.txt"; then echo "✘ store APK: install permission"; RC=1; else echo "✔ store APK: no install permission"; fi
if adb shell dumpsys activity activities | grep -E "ResumedActivity" | grep -q "com.jadeite.mobile/.MainActivity"; then
  echo "✔ store APK: MainActivity on screen"
else
  echo "✘ store APK: MainActivity not on screen"; RC=1
fi
adb shell svc wifi enable || true
adb shell svc data enable || true
exit $RC
