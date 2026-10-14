# -*- coding: utf-8 -*-
"""المسرح السينمائي (4.68) — خلفية بوابة الدخول مقطعٌ مصوَّر لا رسم.

**لماذا تغيّر المسرح**: الرسم بـ`QPainter` (غبارٌ وخواتمُ وأشعّة) مهما
أُتقن يبقى أشكالاً مرسومة — كرتونيةً بجانب ما يراه الناس في إعلانات
المجوهرات. الآن الخلفية **مشهدٌ ثلاثيّ الأبعاد صُيِّر بمحرّك تتبّع
الأشعّة الفيزيائي** (Blender Cycles): سبائكُ ذهبٍ مصبوبة بختمها، وخاتمٌ
مصقول، على سطحٍ أسود لامع يعكسها — بإضاءة استوديو منتجات حقيقية،
وعمقِ ميدانٍ كعدسة 80 مم، وكاميرا تدور ببطءٍ شديد، وشريطِ ضوءٍ يعبر
السبائك فيمرّ لمعانُه عليها **انعكاساً حقيقياً** لا رسماً فوقها.

**الملفّان** (في `assets/gate`):
  · `gold_loop.webp` — حلقةٌ متحرّكة (WebP) ثماني ثوانٍ بـ30 إطاراً في
    الثانية بدقّة 1920×1080 (منذ 4.70)، صامتةٌ بطبيعتها، وحركتها دوريةٌ
    رياضياً (جيوبٌ تامّة الدورة) فآخر إطارٍ يتّصل بأولها بلا قفزة.
    لماذا 30 لا 24: الشاشات 60 هرتز — الإطار يبقى مسحتين بالضبط، أمّا
    24 فيتناوب مسحتين وثلاثاً (اهتزازٌ خفيف في الحركة البطيئة).
  · `gold_poster.jpg` — صورةٌ ساكنة من المشهد نفسه: البديل الثابت.

**البديل الثابت** يُعرض في كل حالةٍ لا تليق فيها الحركة:
  · إعداد «تقليل الحركة» في ويندوز (إظهار الحركات في ويندوز = مطفأ)،
    أو إطفاء الحركة في النظام (`animations_on`).
  · تعذّر تشغيل المقطع (ملفٌ مفقود أو مكتبة WebP غائبة).
  · جهازٌ بطيء: إن طال تجهيز الإطار عن حدٍّ معلوم تتوقّف الحركة على
    الإطار الظاهر نفسه — فلا قفزة، والمشهد يبقى جميلاً ساكناً.
  وإن غاب الملفّان معاً: ليلٌ متدرّج داكن — بلا أيّ رسمٍ بديل.

**سلسٌ وخفيف (4.70)**: لا `QMovie` بعد الآن — كان يفكّ الإطار على خيط
الواجهة نفسه بمؤقّتٍ تقريبي، فإن انشغلت الواجهة لحظةً تأخّر الإطار،
وإن انشغل هو بالفكّ تثاقلت الكتابة في الحقول. الآن (`_Loop`):
  · خيطٌ خلفي يفكّ الإطار التالي ويقصّه ويحجّمه بمقاس الشاشة ويضع عليه
    التعتيم — ولا يبقى لخيط الواجهة إلا لصقُ صورةٍ جاهزة.
  · العرض بالساعة: الإطار n يظهر عند n × مدّته بمؤقّتٍ دقيق، فلا يتراكم
    انحراف؛ وتأخّرٌ عابر يُلحَق بإسقاط إطارٍ لا بإبطاء الحركة كلها.
  · ثلاثة إطاراتٍ جاهزة في الطابور تمتصّ أي انشغالٍ عابر.
وتتوقّف الحركة متى خفيت البوابة، ويسكن الخيط بلا عمل.

**الانتقالات هادئة**: ظهورٌ من العتمة مع استقرارٍ بطيءٍ للكاميرا
(تقريبٌ خفيفٌ يرتدّ إلى مكانه)، وخروجٌ بتعتيمٍ واقترابٍ قليل — لا
أكثر. فالواجهة يفتحها صاحبها كل صباح: تُبهج أول مرة ولا تُزعج بعدها.
"""
import collections
import math
import os
import sys
import threading
import time
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

LOOP = "gold_loop.webp"
POSTER = "gold_poster.jpg"
# المشهد مؤلَّف ليقع الذهب في ثلثه الأيسر: إن ضاقت الشاشة عن نسبة
# المقطع (16:10 أو 4:3) يُقصّ من حول هذه النقطة فيبقى الذهب ظاهراً
ANCHOR_X = 0.36
ANCHOR_Y = 0.52
REVEAL_MS = 1300            # الظهور من العتمة
SETTLE_MS = 3200            # استقرار الكاميرا بعده
SETTLE_ZOOM = 0.045         # تقريبٌ يبدأ به المشهد ثم يرتدّ
EXIT_ZOOM = 0.06            # اقترابٌ خفيف عند الخروج
SLOW_MS = 45.0              # متوسّط تأخّر الإطار فوقه تتوقّف الحركة
SLOW_FRAMES = 90            # على كم إطاراً يُقاس (ثلاث ثوانٍ متّصلة)
SKIP_MS = 66.0              # كلفة إطارٍ أُسقط — فيسكن ما دون ~11 إطاراً/ث
QUEUE = 3                   # إطاراتٌ جاهزة تنتظر موعدها
GIL_SWITCH = 0.002          # مهلة تناوب الخيوط على قفل بايثون أثناء العرض


_GIL = {"n": 0, "old": None}


def _gil_fast(on):
    """تناوبٌ أسرع على قفل بايثون ما دامت الحلقة تدور.

    الخيط الخلفي يمسك القفل في شرائح الرسم القصيرة؛ وخيط الواجهة ينتظره
    — افتراضاً — حتى 5 م.ث في كل مرة، وقد يحتاجه مراراً في الدورة الواحدة
    (مؤقّتٌ ورسمٌ وحدث) فيتراكم الانتظار. 2 م.ث تكفي لتبقى الكتابة في
    الحقول فوريةً أثناء الحركة. ويُعاد كما كان متى توقّفت.
    """
    if on:
        if _GIL["n"] == 0:
            _GIL["old"] = sys.getswitchinterval()
            sys.setswitchinterval(min(_GIL["old"], GIL_SWITCH))
        _GIL["n"] += 1
    elif _GIL["n"] > 0:
        _GIL["n"] -= 1
        if _GIL["n"] == 0 and _GIL["old"]:
            sys.setswitchinterval(_GIL["old"])
WARMUP_MS = 6000            # لا قياس في أول ثوانٍ: الإقلاع ثقيلٌ بطبعه


def asset(name):
    """مسار أصل البوابة: من التحديث المثبَّت أو الحزمة أو المستودع."""
    try:
        import config
        p = Path(config.BUNDLE_DIR) / "assets" / "gate" / name
        if p.exists():
            return p
    except Exception:
        pass
    p = Path(__file__).resolve().parents[2] / "assets" / "gate" / name
    return p if p.exists() else None


def reduced_motion():
    """هل طلب الجهاز تقليل الحركة؟

    ويندوز: «إظهار الحركات في ويندوز» (إعدادات ← تسهيل الوصول ← تأثيرات
    مرئية) — يُقرأ بـSPI_GETCLIENTAREAANIMATION. ومتغيّر بيئة صريح
    للاختبار وللأجهزة الخاصة.
    """
    v = os.environ.get("GOLD_ERP_REDUCE_MOTION", "").strip()
    if v:
        return v not in ("0", "false", "no")
    if sys.platform.startswith("win"):
        try:
            import ctypes
            on = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(
                    0x1042, 0, ctypes.byref(on), 0):
                return not bool(on.value)
        except Exception:
            pass
    return False


def motion_allowed():
    try:
        from ui.widgets.gold_stage import animations_on
        if not animations_on():
            return False
    except Exception:
        pass
    return not reduced_motion()


class _Loop(QtCore.QObject):
    """مشغّل الحلقة: فكٌّ وتحجيمٌ في خيطٍ خلفي، وعرضٌ بالساعة.

    يحاكي من `QMovie` ما تسأل عنه البوابة واختباراتها (`state` ·
    `currentFrameNumber` · `loopCount` · `nextFrameDelay` · `start` ·
    `stop` · `setPaused`) — فهو بديلٌ في مكانه.

    `spec_fn` يُسأل على خيط الواجهة عند كل نبضة: ما مقاس الشاشة وتقريبها
    وتعتيمها الآن — فيجهّز الخيط الخلفي الإطار التالي على ذلك.
    `on_frame(n)` يُنادى عند ظهور إطارٍ جديد، و`on_lag(ms)` بتأخّره.
    """

    def __init__(self, path, spec_fn, on_frame, on_lag, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._spec_fn, self._on_frame, self._on_lag = spec_fn, on_frame, on_lag
        rd = QtGui.QImageReader(self._path)
        ok = rd.canRead() and rd.supportsAnimation()
        first = rd.read() if ok else QtGui.QImage()
        self.valid = bool(ok and not first.isNull())
        self.count = max(1, rd.imageCount()) if self.valid else 0
        # مدّة الإطار تُعرف بعد قراءة أوّله — قبلها يعيد Qt صفراً
        d = rd.nextImageDelay() if self.valid else 0
        d = float(d) if d and d > 0 else 1000.0 / 30
        # WebP يحفظ المدّة بأجزاءٍ صحيحة من الألف (33 لا 33.3): تُردّ إلى
        # معدّلها الحقيقي فلا تنزلق الحلقة عن مسحات الشاشة مع الوقت
        fps = round(1000.0 / d)
        self.delay = 1000.0 / fps if fps and abs(1000.0 / fps - d) < 1 else d
        self.loops = rd.loopCount() if self.valid else 0
        self.size = first.size()
        self.image = None           # الإطار الظاهر — جاهزٌ بمقاس الشاشة
        self.failed = False         # تعذّر الفكّ مراراً: يسكن المسرح
        self.seq = -1               # رقمه المتسلسل (يتجاوز طول الحلقة)
        self._cv = threading.Condition()
        self._q = collections.deque()
        self._spec = None
        self._want = 0
        self._quit = threading.Event()
        self._thread = None
        self._state = QtGui.QMovie.NotRunning
        self._fast = False          # تناوبٌ أسرع على القفل مطلوبٌ الآن؟
        self._clock = QtCore.QElapsedTimer()
        self._base = 0.0            # ما مضى من الحلقة قبل آخر إيقاف
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        q = self._quit
        self.destroyed.connect(lambda *_a: q.set())
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    # ── واجهة QMovie
    def isValid(self):
        return self.valid

    def state(self):
        return self._state

    def currentFrameNumber(self):
        return max(0, self.seq) % max(1, self.count)

    def frameCount(self):
        return self.count

    def loopCount(self):
        return self.loops

    def nextFrameDelay(self):
        return int(round(self.delay))

    def _set_fast(self, on):
        if on != self._fast:
            self._fast = on
            _gil_fast(on)

    def start(self):
        if self._state == QtGui.QMovie.Running or not self.valid:
            return
        if self._state == QtGui.QMovie.Paused:
            self.setPaused(False)
            return
        self._quit.clear()
        self._clock.invalidate()
        self._base, self._want, self.seq = 0.0, 0, -1
        with self._cv:
            self._q.clear()
        self._spec = self._spec_fn()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="gate-loop")
        self._state = QtGui.QMovie.Running
        self._set_fast(True)
        self._thread.start()
        self._timer.start(4)

    def setPaused(self, on):
        if on and self._state == QtGui.QMovie.Running:
            if self._clock.isValid():
                self._base += self._clock.elapsed()
                self._clock.invalidate()
            self._timer.stop()
            self._state = QtGui.QMovie.Paused
            self._set_fast(False)
        elif not on and self._state == QtGui.QMovie.Paused:
            self._state = QtGui.QMovie.Running
            self._set_fast(True)
            if self.seq >= 0:
                self._clock.start()
            self._timer.start(1)

    def stop(self):
        """يوقف الخيط ويُفرغ الطابور — الإطار الظاهر يبقى."""
        self._timer.stop()
        self._state = QtGui.QMovie.NotRunning
        self._set_fast(False)
        self._quit.set()
        with self._cv:
            self._q.clear()
            self._cv.notify_all()
        th, self._thread = self._thread, None
        if th is not None and th is not threading.current_thread():
            th.join(0.5)

    # ── خيط الواجهة: إطارٌ في موعده
    def _tick(self):
        if self._state != QtGui.QMovie.Running:
            return
        if self.failed:
            self._timer.stop()
            self._on_frame(-1)          # المسرح يرى `failed` فيسكن
            return
        self._spec = self._spec_fn()
        if not self._clock.isValid():
            # الحلقة تبدأ مع أول إطارٍ جاهز — لا قبله فيُلحق بما فات
            with self._cv:
                item = self._q.popleft() if self._q else None
                self._cv.notify_all()
            if item is None:
                self._timer.start(4)
                return
            self._show(item)
            self._base = item[0] * self.delay
            self._clock.start()
            self._timer.start(int(self.delay))
            return
        t = self._base + self._clock.elapsed()
        want = int(t // self.delay)
        got = None
        with self._cv:
            self._want = want
            while self._q and self._q[0][0] <= want:
                got = self._q.popleft()
            if got is not None:
                self._cv.notify_all()
        if got is not None:
            gap = got[0] - self.seq - 1 if self.seq >= 0 else 0
            self._show(got)
            # التأخّر: كم تأخّر هذا الإطار عن موعده، وما أُسقط قبله
            for _ in range(max(0, gap)):
                self._on_lag(SKIP_MS)
            self._on_lag(max(0.0, t - got[0] * self.delay))
        if self.seq >= want:
            nxt = (want + 1) * self.delay - t
        else:
            nxt = 4.0               # إطارٌ حان ولم يجهز — يُنتظر قليلاً
        self._timer.start(max(1, int(math.ceil(nxt))))

    def _show(self, item):
        self.seq, self.image = item
        self._on_frame(self.currentFrameNumber())

    # ── الخيط الخلفي: فكٌّ وتجهيز
    #
    # تنبيه: في PyQt5 لا يُطلق قفلُ بايثون (GIL) إلا في نداءاتٍ معلومة —
    # `QImageReader.read` منها، أمّا الرسم بـ`QPainter` فيمسكه طوال النداء،
    # فيتجمّد خيط الواجهة معه. لذا:
    #   · القصّ والتحجيم يجريان **داخل** `read` نفسه (خيارا القارئ
    #     `setClipRect`/`setScaledSize`) — بلا قفل، وبتحجيمٍ ناعم.
    #   · وما لا بدّ فيه من الرسم (التعتيم، والتقريب العشري أثناء استقرار
    #     الكاميرا والخروج) يُرسم شرائح قصيرة، وبين كل شريحتين يُترك
    #     القفل لخيط الواجهة.
    #   · التقريب أثناء الحركة بإحداثياتٍ عشرية لا صحيحة: التقريب إلى
    #     أقرب بكسل يجعل الصورة «ترتجف» بكسلاً هنا وهناك.
    def _run(self):
        if sys.platform.startswith("win"):
            # أعلى قليلاً من العادي: جهازٌ مشغولٌ ببرامج أخرى (مضادّ فيروسات
            # بعد الإقلاع) لا يؤخّر الإطار التالي — والعمل نفسه خفيف
            try:
                import ctypes
                k32 = ctypes.windll.kernel32
                k32.SetThreadPriority(k32.GetCurrentThread(), 1)
            except Exception:
                pass
        rd, idx, seq, fails = None, 0, 0, 0
        quit_, cv, q = self._quit, self._cv, self._q
        while not quit_.is_set():
            with cv:
                while not quit_.is_set() and len(q) >= QUEUE:
                    cv.wait(0.5)
                if quit_.is_set():
                    break
                spec, want = self._spec, self._want
            if rd is None or idx >= self.count:
                rd, idx = QtGui.QImageReader(self._path), 0
            s = seq
            late = s < want - 1         # فات موعده: يُفكّ فقط (ما بعده يبنى عليه)
            plan = None if late else self._plan(spec)
            rd.setClipRect(plan[0] if plan and plan[0] else QtCore.QRect())
            rd.setScaledSize(plan[1] if plan and plan[1] else QtCore.QSize())
            img = rd.read()
            if img.isNull():
                fails += 1
                rd = None
                if fails > 3:
                    self.failed = True
                    break
                continue
            fails, idx, seq = 0, idx + 1, seq + 1
            if late:
                continue
            out = self._compose(img, spec, plan[2])
            with cv:
                if quit_.is_set():
                    break
                q.append((s, out))

    def _cover(self, W, H, z):
        """المستطيل المقصوص من الإطار (بإحداثيات الإطار) ليغطّي W×H حول الذهب."""
        iw, ih = self.size.width(), self.size.height()
        s = max(W / float(iw), H / float(ih)) * z
        vw, vh = W / s, H / s
        sx = min(max(0.0, iw * ANCHOR_X - vw * ANCHOR_X), iw - vw)
        sy = min(max(0.0, ih * ANCHOR_Y - vh * ANCHOR_Y), ih - vh)
        return sx, sy, vw, vh

    def _plan(self, spec):
        """(قصّ القارئ، تحجيمه، قصٌّ عشري يُرسم) — حسب المقاس والتقريب."""
        if spec is None or spec[0] <= 0 or spec[1] <= 0:
            return (None, None, None)
        W, H, _dpr, z, _sh = spec
        iw, ih = self.size.width(), self.size.height()
        if abs(z - 1.0) > 1e-4:
            return (None, None, self._cover(W, H, z))   # تقريبٌ يتحرّك
        sx, sy, vw, vh = self._cover(W, H, 1.0)
        clip = QtCore.QRect(int(round(sx)), int(round(sy)),
                            int(round(vw)), int(round(vh)))
        if clip == QtCore.QRect(0, 0, iw, ih):
            clip = None
        size = None if (W, H) == (iw, ih) and clip is None else QtCore.QSize(W, H)
        return (clip, size, None)

    @staticmethod
    def _compose(img, spec, src):
        """الإطار الجاهز: (تقريبٌ عشري إن لزم) ثم التعتيم — شرائح قصيرة."""
        W, H, dpr, _z, shade = spec
        if W <= 0 or H <= 0:
            return img
        out = QtGui.QImage(W, H, QtGui.QImage.Format_RGB32)
        p = QtGui.QPainter(out)
        if src is not None:
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            n, target, source = 8, QtCore.QRectF(0, 0, W, H), QtCore.QRectF(*src)
        else:
            n = 4
        for k in range(n):
            y0, y1 = H * k // n, H * (k + 1) // n
            band = QtCore.QRect(0, y0, W, y1 - y0)
            if src is not None:
                p.setClipRect(band)
                p.drawImage(target, img, source)
            else:
                p.drawImage(band, img, band)
            if shade is not None:
                p.drawImage(QtCore.QRectF(band), shade, QtCore.QRectF(band))
            time.sleep(0)           # يُترك القفل لخيط الواجهة
        p.end()
        out.setDevicePixelRatio(dpr)
        return out


class CinemaStage(QtWidgets.QWidget):
    """خلفية البوابة: المقطع الذهبي يملأ الشاشة، ومعه بديله الساكن.

    يحمل خصائص المسرح القديم نفسها (`intro` · `exit` · `card_rect` …)
    فتعمل البوابة معه كما هي؛ وما لا معنى له هنا (الموجة والأشعّة)
    يُقبل ويُتجاهل.
    """

    uses_overlay = False        # الحواف يرسمها بنفسه: تعتيمٌ ناعم بلا إطار
    # أول إطارٍ يُرسم فعلاً: المسرح يغطّي البوابة كلها فلا تُرسم هي —
    # فيُعلن هو أول رسمٍ نيابةً عنها (شاشة بدء الـexe تُغلق عليه)
    first_paint = QtCore.pyqtSignal()

    def __init__(self, parent=None, animate=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        # خصائص المسرح القديم — تقبلها البوابة وتضبطها
        self.intro = 0.0
        self.exit = 0.0
        self.ripple = -1.0
        self.focus_y = 0.5
        self.logo_center = None
        self.card_rect = None
        self.card_k = 0.0
        self.overlay = None
        self.calm = True
        self.side = "right"         # موضع لوحة الدخول — يُعتَّم خلفها قليلاً

        self._animate = motion_allowed() if animate is None else bool(animate)
        self._frame = None          # الصورة الساكنة (QImage)
        self._scaled = None         # الصورة نفسها بمقاس الشاشة (QPixmap)
        self._scaled_key = None
        self._shade = None          # التعتيم والحواف — مرةً لكل مقاس
        self._shade_key = None
        self._cost = []             # تأخّر الإطارات الأخيرة عن مواعيدها
        self._still = None          # إطارٌ جاهز سكن عليه المقطع (مع تقريبه)
        self.mode = "plain"         # movie · poster · plain
        self.reveal = 1.0
        self.settle = 0.0

        p = asset(POSTER)
        img = QtGui.QImage(str(p)) if p else QtGui.QImage()
        self._poster = None if img.isNull() else img
        self._movie = None
        if self._animate:
            self._movie = self._open_movie()
        if self._movie is not None:
            self.mode = "movie"
        elif self._poster is not None:
            self.mode = "poster"
        # الصورة الساكنة هي أول إطارٍ في الحلقة نفسها: تُعرض حتى يجهز
        # أول إطارٍ من الخيط الخلفي — فلا سوادَ ولا قفزة عند البدء
        self._frame = self._poster

        self._reveal_anim = QtCore.QVariantAnimation(self)
        self._reveal_anim.setStartValue(0.0)
        self._reveal_anim.setEndValue(1.0)
        self._reveal_anim.setDuration(REVEAL_MS)
        self._reveal_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._reveal_anim.valueChanged.connect(self._on_reveal)
        self._settle_anim = QtCore.QVariantAnimation(self)
        self._settle_anim.setStartValue(1.0)
        self._settle_anim.setEndValue(0.0)
        self._settle_anim.setDuration(SETTLE_MS)
        self._settle_anim.setEasingCurve(QtCore.QEasingCurve.OutQuart)
        self._settle_anim.valueChanged.connect(self._on_settle)

    # ─────────────────────────────── المقطع
    def _open_movie(self):
        p = asset(LOOP)
        if p is None:
            return None
        try:
            mv = _Loop(p, self._loop_spec, self._on_frame, self._watch, self)
        except Exception:
            return None
        return mv if mv.isValid() else None

    def _loop_spec(self):
        """ما يحتاجه الخيط الخلفي ليجهّز الإطار التالي: المقاس الفعلي
        (بنقاط الشاشة) والتقريب الآن والتعتيم مرسوماً."""
        w, h = self.width(), self.height()
        dpr = self._dpr()
        return (max(0, int(w * dpr)), max(0, int(h * dpr)), dpr,
                self._zoom(), self._shade_for(w, h) if w > 0 and h > 0 else None)

    def _on_frame(self, _n=0):
        if self._movie is not None and self._movie.failed:
            self.freeze()
        self.update()

    def _watch(self, ms):
        """جهازٌ لا يلحق بالمقطع: تتوقّف الحركة على الإطار الظاهر.

        `ms` تأخّر الإطار عن موعده (وكل إطارٍ أُسقط يُحسب `SKIP_MS`) —
        فإن زاد المتوسّط على `SLOW_MS` طوال `SLOW_FRAMES` فالجهاز مشغول،
        والسكون أكرم من حركةٍ متقطّعة.
        """
        if not hasattr(self, "_clock"):
            self._clock = QtCore.QElapsedTimer()
            self._clock.start()
        if self._clock.elapsed() < WARMUP_MS:
            # الثواني الأولى ثقيلةٌ بطبعها (الإقلاع وبناء اللوحة)، وويندوز
            # نفسه مشغولٌ بعد الإقلاع — تأخّرٌ عابر لا يُحكم به على الجهاز
            return
        self._cost.append(float(ms))
        if len(self._cost) > SLOW_FRAMES:
            self._cost.pop(0)
            if sum(self._cost) / len(self._cost) > SLOW_MS:
                self.freeze()

    def freeze(self):
        """يوقف المقطع ويُبقي إطاره الأخير — بديلٌ ساكن بلا قفزة."""
        mv = self._movie
        if mv is not None:
            if mv.image is not None:
                self._still = (mv.image, self._zoom())
            try:
                mv.stop()
            except Exception:
                pass
        self.mode = "poster" if (self._frame is not None
                                 or self._still is not None) else "plain"
        self._movie = None

    # ─────────────────────────────── التشغيل
    def start(self):
        """يبدأ المشهد: ظهورٌ من العتمة واستقرارٌ للكاميرا ثم الحلقة."""
        if self._movie is not None \
                and self._movie.state() != QtGui.QMovie.Running:
            self._movie.start()
        if self._animate and self.reveal >= 1.0 and self.intro <= 0.0 \
                and not getattr(self, "_revealed", False):
            self._revealed = True
            self.reveal, self.settle = 0.0, 1.0
            self._reveal_anim.start()
            self._settle_anim.start()
        self.update()

    def stop(self):
        if self._movie is not None:
            self._movie.setPaused(True)

    def showEvent(self, e):
        super().showEvent(e)
        if self._movie is not None and \
                self._movie.state() == QtGui.QMovie.Paused:
            self._movie.setPaused(False)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.stop()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._still is not None:
            im = self._still[0]
            d = im.devicePixelRatio() or 1.0
            if (round(im.width() / d), round(im.height() / d)) != \
                    (self.width(), self.height()):
                self._still = None      # مقاسٌ آخر: يُعرض البديل الساكن
        # يُحجَّم عند الحاجة إليه في الرسم لا هنا: في وضع المقطع لا يُحتاج
        # البديل الساكن غالباً (الإطار الأول يصل قبل أن ينقشع السواد)
        self._scaled = None

    def _playing(self):
        """الحلقة تدور وإطاراتها تصل: كل إطارٍ يعيد الرسم بنفسه."""
        mv = self._movie
        return (mv is not None and mv.image is not None
                and mv.state() == QtGui.QMovie.Running)

    def _on_reveal(self, v):
        self.reveal = float(v)
        if not self._playing():         # وإلا فالإطار التالي يرسم العتمة
            self.update()

    def _on_settle(self, v):
        self.settle = float(v)
        if self.mode != "movie":        # الساكن لا يُعاد تحجيمه بإطاراته
            self._rescale()
        if not self._playing():         # التقريب يُجهَّز مع كل إطار
            self.update()

    # ─────────────────────────────── الرسم
    def _dpr(self):
        try:
            return max(1.0, float(self.devicePixelRatioF()))
        except Exception:
            return 1.0

    def _zoom(self):
        return 1.0 + SETTLE_ZOOM * self.settle + EXIT_ZOOM * self.exit

    def _rescale(self):
        """الإطار بمقاس الشاشة «يغطّيها» — مرةً لكل إطارٍ جديد."""
        img = self._frame
        w, h = self.width(), self.height()
        if img is None or w <= 0 or h <= 0:
            self._scaled = None
            return
        dpr = self._dpr()
        W, H = max(1, int(w * dpr)), max(1, int(h * dpr))
        z = self._zoom()
        key = (img.cacheKey(), W, H, round(z, 4))
        if key == self._scaled_key and self._scaled is not None:
            return
        iw, ih = img.width(), img.height()
        s = max(W / float(iw), H / float(ih)) * z
        vw, vh = W / s, H / s
        sx = min(max(0.0, iw * ANCHOR_X - vw * ANCHOR_X), iw - vw)
        sy = min(max(0.0, ih * ANCHOR_Y - vh * ANCHOR_Y), ih - vh)
        src = QtCore.QRectF(sx, sy, vw, vh)
        pm = QtGui.QPixmap(W, H)
        pm.fill(QtGui.QColor("#050403"))
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        p.drawImage(QtCore.QRectF(0, 0, W, H), img, src)
        p.end()
        pm.setDevicePixelRatio(dpr)
        self._scaled, self._scaled_key = pm, key

    def _shade_for(self, w, h):
        key = (w, h, self.side, round(self._dpr(), 2))
        if self._shade is None or self._shade_key != key:
            self._shade, self._shade_key = self._build_shade(w, h), key
        return self._shade

    def _build_shade(self, w, h):
        """تعتيم الحواف، وظلٌّ أعمق خلف لوحة الدخول يُبقي حقولها واضحة.

        صورةٌ (`QImage`) لا `QPixmap`: يرسمها الخيط الخلفي على كل إطار."""
        dpr = self._dpr()
        img = QtGui.QImage(int(w * dpr), int(h * dpr),
                           QtGui.QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rg = QtGui.QRadialGradient(w * 0.42, h * 0.5, max(w, h) * 0.78)
        rg.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
        rg.setColorAt(0.62, QtGui.QColor(0, 0, 0, 0))
        rg.setColorAt(1.0, QtGui.QColor(0, 0, 0, 150))
        p.fillRect(QtCore.QRectF(0, 0, w, h), QtGui.QBrush(rg))
        if self.side == "right":
            lg = QtGui.QLinearGradient(w * 0.46, 0, w, 0)
            lg.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
            lg.setColorAt(0.55, QtGui.QColor(0, 0, 0, 70))
            lg.setColorAt(1.0, QtGui.QColor(0, 0, 0, 120))
            p.fillRect(QtCore.QRectF(0, 0, w, h), QtGui.QBrush(lg))
        else:
            p.fillRect(QtCore.QRectF(0, 0, w, h), QtGui.QColor(0, 0, 0, 70))
        p.end()
        return img

    def paintEvent(self, _e):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QtGui.QPainter(self)
        # الظهور من العتمة والخروج إليها — طبقةٌ سوداء تخفّ وتشتدّ
        dark = (1.0 - self.reveal) + 0.88 * self.exit
        if dark >= 0.999:
            p.fillRect(self.rect(), QtCore.Qt.black)     # لا شيء يُرى بعد
            p.end()
            self._announce()
            return
        ready, z0 = None, None
        if self._movie is not None and self._movie.image is not None:
            ready = self._movie.image           # جاهزٌ بمقاسه وعليه التعتيم
        elif self._still is not None:
            ready, z0 = self._still
        if ready is None and self._movie is not None \
                and self._movie.state() == QtGui.QMovie.Running:
            # أول إطارٍ يُجهَّز الآن — والمشهد ما زال في عتمة ظهوره، فلا
            # يُحجَّم البديل الساكن على خيط الواجهة لأجل أجزاءٍ من الثانية
            p.fillRect(self.rect(), QtGui.QColor("#050403"))
            p.end()
            self._announce()
            return
        if ready is not None:
            r = QtCore.QRectF(0, 0, w, h)
            if z0 is not None and abs(self._zoom() - z0) > 1e-4:
                # الساكن يقترب مع الخروج حول نقطة الذهب نفسها
                k = self._zoom() / z0
                ax, ay = w * ANCHOR_X, h * ANCHOR_Y
                r = QtCore.QRectF(ax - ax * k, ay - ay * k, w * k, h * k)
            dpr = ready.devicePixelRatio() or 1.0
            if r == QtCore.QRectF(0, 0, ready.width() / dpr,
                                  ready.height() / dpr):
                p.drawImage(0, 0, ready)        # لصقٌ بلا تحجيم
            else:
                p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
                p.drawImage(r, ready)
        else:
            if self._scaled is None and self._frame is not None:
                self._rescale()
            if self._scaled is not None:
                p.drawPixmap(0, 0, self._scaled)
            else:
                g = QtGui.QLinearGradient(0, 0, 0, h)
                g.setColorAt(0.0, QtGui.QColor("#0B0906"))
                g.setColorAt(1.0, QtGui.QColor("#020201"))
                p.fillRect(self.rect(), QtGui.QBrush(g))
            p.drawImage(0, 0, self._shade_for(w, h))
        if dark > 0.004:
            p.fillRect(self.rect(),
                       QtGui.QColor(0, 0, 0, int(255 * min(1.0, dark))))
        p.end()
        self._announce()

    def _announce(self):
        if not getattr(self, "_announced", False):
            self._announced = True
            self.first_paint.emit()

    def set_exit(self, v):
        """يضبط الخروج: تعتيمٌ واقترابٌ خفيف (يُعاد التحجيم مع الاقتراب)."""
        self.exit = float(v)
        if self.mode != "movie":
            self._rescale()
        self.update()
