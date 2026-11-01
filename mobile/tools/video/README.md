# الفيديو التعليمي للمناديب

فيديو عمودي (1080×1920، H.264) يشرح التطبيق خطوةً بخطوة: لقطاتٌ حقيقية من
التطبيق داخل إطار جوال، وإبرازٌ للزرّ ولمسته، وتقريبٌ هادئ، وشرحٌ عربي لكل
خطوة، وفصولٌ ومقدّمةٌ وختام، وموسيقى هادئة مُولَّدة (بلا ملفات خارجية).

يُعاد إنتاجه بعد أي تغييرٍ في الواجهة:

    S=/tmp/video                                   # أي مجلد عمل
    node    mobile/tools/video/capture.js $S/shots      # 1) اللقطات (Playwright)
    node    mobile/tools/video/render.js  $S/shots $S/video.mp4 --jobs 3   # 2) الإطارات ← MP4
    python3 mobile/tools/video/music.py   $S            # 3) الموسيقى (numpy) من timeline.json
    ffmpeg -i $S/video.mp4 -i $S/music.wav -c:v copy -af loudnorm=I=-16:TP=-1.5 \
           -c:a aac -b:a 192k -shortest -movflags +faststart "دليل-المندوب.mp4"

- `capture.js`: الخطوات والشرح (العنوان والسطر الثاني) ومكان كل لمسة — هنا يُعدَّل النص.
- `player.html`: المسرح وحركته (`renderAt(t)`)؛ الألوان من لوحة التطبيق.
- `render.js --preview 3.5,40` يرسم لحظاتٍ بعينها صوراً للمراجعة قبل الإنتاج الكامل.
