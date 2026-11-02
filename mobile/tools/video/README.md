# الفيديو التعليمي للمناديب

فيديو عمودي (1080×1920، H.264) يشرح التطبيق خطوةً بخطوة: لقطاتٌ حقيقية من
التطبيق داخل إطار جوال، وإبرازٌ للزرّ ولمسته، وتقريبٌ هادئ، وشرحٌ عربي لكل
خطوة، وفصولٌ ومقدّمةٌ وختام، وموسيقى هادئة مُولَّدة (بلا ملفات خارجية).

يُعاد إنتاجه بعد أي تغييرٍ في الواجهة:

    S=/tmp/video                                   # أي مجلد عمل
    node    mobile/tools/video/capture.js $S/shots      # 1) اللقطات والشرح (Playwright)
    python3 mobile/tools/video/tts.py     $S/shots VOICE_DIR   # 2) الصوت الشارح (Piper)
    node    mobile/tools/video/render.js  $S/shots $S/video.mp4 --jobs 3   # 3) الإطارات ← MP4
    python3 mobile/tools/video/music.py   $S            # 4) الموسيقى والصوت (numpy) من timeline.json
    ffmpeg -i $S/video.mp4 -i $S/music.wav -c:v copy -af loudnorm=I=-16:TP=-1.5 \
           -c:a aac -b:a 192k -shortest -movflags +faststart "دليل-المندوب.mp4"
    python3 mobile/tools/video/chapters.py "دليل-المندوب.mp4" $S/timeline.json فصول/   # 5) مقطعٌ لكل فصل

- `capture.js`: الخطوات، والعنوان، ونصّ الصوت مشكولاً (`say`) — وتحت الصورة يظهر بلا تشكيل.
  التشكيل الكامل يحسّن النطق كثيراً.
- `tts.py`: صوت Piper العربي «كريم» (مفتوح المصدر، يعمل محلياً). VOICE_DIR من إصدارات
  sherpa-onnx على GitHub: `tts-models/vits-piper-ar_JO-kareem-medium.tar.bz2`.
- `player.html`: المسرح وحركته (`renderAt(t)`)؛ الألوان من لوحة التطبيق.
- `render.js --preview 3.5,40` يرسم لحظاتٍ بعينها صوراً للمراجعة قبل الإنتاج الكامل.
