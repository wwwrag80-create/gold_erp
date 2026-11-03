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

## النسختان القصيرتان

من لقطات الدليل الكامل نفسها: تبدآن بشعار التطبيق واسمه ÀUR، ثم لوحة
«ماذا تستفيد من النظام؟»، ثم الدخول، ولوحات الرئيسية لوحةً لوحة. ولكل عمليةٍ تظهر لوحتها في
الرئيسية أولاً، ثم خطواتها بطريقتيها: البضاعة (بالوزن والأجور مع صورة فاتورة المصنع، أو باسم
الطقم)، والبيع والمرتجع (بالوزن مباشرة، أو طقمٌ من الأطقم التي معك)؛ ومن كشف الحساب معاينة
أي فاتورةٍ كما سُجّلت.

    python3 mobile/tools/video/shorts.py $S/shots $S/silent $S/voice      # الخطوات ونصوصها
    TTS_STYLE=natural python3 mobile/tools/video/tts.py $S/voice VOICE_DIR
    node mobile/tools/video/render.js $S/silent $S/out_s/video.mp4 --jobs 4 --fps 25   # ≈ دقيقتان ونصف
    node mobile/tools/video/render.js $S/voice  $S/out_v/video.mp4 --jobs 4 --fps 25   # ≈ ثلاث دقائق
    python3 mobile/tools/video/music.py $S/out_s ; python3 mobile/tools/video/music.py $S/out_v

- `TTS_STYLE`: بلا قيمة = هادئ (الدليل الكامل)، `lively` = مفعم، `natural` = إيقاعٌ وتنغيمٌ أقرب
  للكلام البشري مع قصّ الصمت الزائد. `TTS_LENGTH` يضبط السرعة، و`TTS_TAG=x` يكتب صوتاً بديلاً
  في `voice_x/` للمقارنة.
- الأصوات المولَّدة محلياً تبقى آلية بعض الشيء؛ أفضل نتيجة: تسجيلٌ بشري للنصوص نفسها
  (`say` في shorts.py) بأسماء ملفات `voice/<المفتاح>.wav`، ثم كتابة `voice.json` بالمدد.
