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
  · `gold_loop.webp` — حلقةٌ متحرّكة (WebP) ثماني ثوانٍ بـ24 إطاراً،
    صامتةٌ بطبيعتها، وحركتها دوريةٌ رياضياً (جيوبٌ تامّة الدورة) فآخر
    إطارٍ يتّصل بأولها بلا قفزة. نحو 4 ميجابايت لا غير: المشهد داكنٌ
    فيُضغط جيداً.
  · `gold_poster.jpg` — صورةٌ ساكنة من المشهد نفسه: البديل الثابت.

**البديل الثابت** يُعرض في كل حالةٍ لا تليق فيها الحركة:
  · إعداد «تقليل الحركة» في ويندوز (إظهار الحركات في ويندوز = مطفأ)،
    أو إطفاء الحركة في النظام (`animations_on`).
  · تعذّر تشغيل المقطع (ملفٌ مفقود أو مكتبة WebP غائبة).
  · جهازٌ بطيء: إن طال تجهيز الإطار عن حدٍّ معلوم تتوقّف الحركة على
    الإطار الظاهر نفسه — فلا قفزة، والمشهد يبقى جميلاً ساكناً.
  وإن غاب الملفّان معاً: ليلٌ متدرّج داكن — بلا أيّ رسمٍ بديل.

**خفيفٌ على الجهاز**: الإطار يُفكّ ويُحجَّم **مرةً واحدة** عند وصوله ثم
يُلصق لصقاً — فوميض المؤشّر في الحقول لا يعيد التحجيم. ولا يُخزَّن من
المقطع إلا إطارٌ واحد. وتتوقّف الحركة متى خفيت البوابة.

**الانتقالات هادئة**: ظهورٌ من العتمة مع استقرارٍ بطيءٍ للكاميرا
(تقريبٌ خفيفٌ يرتدّ إلى مكانه)، وخروجٌ بتعتيمٍ واقترابٍ قليل — لا
أكثر. فالواجهة يفتحها صاحبها كل صباح: تُبهج أول مرة ولا تُزعج بعدها.
"""
import os
import sys
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
SLOW_FRAMES = 72            # على كم إطاراً يُقاس (ثلاث ثوانٍ متّصلة)
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
        self._frame = None          # آخر إطارٍ فُكّ (QImage)
        self._scaled = None         # الإطار نفسه بمقاس الشاشة (QPixmap)
        self._scaled_key = None
        self._shade = None          # التعتيم والحواف — مرةً لكل مقاس
        self._shade_key = None
        self._cost = []             # أزمنة تجهيز الإطارات الأخيرة
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
        mv = QtGui.QMovie(str(p))
        if not mv.isValid():
            return None
        mv.setCacheMode(QtGui.QMovie.CacheNone)   # إطارٌ واحد في الذاكرة
        mv.frameChanged.connect(self._on_frame)
        return mv

    def _on_frame(self, _n=0):
        t = QtCore.QElapsedTimer()
        t.start()
        img = self._movie.currentImage() if self._movie else QtGui.QImage()
        if img.isNull():
            return
        self._frame = img
        self._rescale()
        self.update()
        self._watch(t.elapsed())

    def _watch(self, ms):
        """جهازٌ لا يلحق بالمقطع: تتوقّف الحركة على الإطار الظاهر.

        يُقاس أمران: كلفة تحجيم الإطار هنا، والفاصل الفعلي بين إطارين
        (فكّ الإطار يجري داخل QMovie قبل وصوله) — فإن تأخّرت الإطارات
        عن موعدها كثيراً فالجهاز مشغول، والسكون أكرم من حركةٍ متقطّعة.
        """
        if not hasattr(self, "_clock"):
            self._clock = QtCore.QElapsedTimer()
            self._clock.start()
            self._last = None
        now = self._clock.elapsed()
        if now < WARMUP_MS:
            # تجهيز القاعدة يجري على خيط الواجهة في الثواني الأولى، وويندوز
            # نفسه مشغولٌ بعد الإقلاع — تأخّرٌ عابر لا يُحكم به على الجهاز
            self._last = now
            return
        gap = None if self._last is None else now - self._last
        self._last = now
        nominal = 42.0
        try:
            nominal = float(self._movie.nextFrameDelay() or 42)
        except Exception:
            pass
        late = 0.0 if gap is None else max(0.0, gap - nominal)
        self._cost.append(float(ms) + late)
        if len(self._cost) > SLOW_FRAMES:
            self._cost.pop(0)
            if sum(self._cost) / len(self._cost) > SLOW_MS:
                self.freeze()

    def freeze(self):
        """يوقف المقطع ويُبقي إطاره الأخير — بديلٌ ساكن بلا قفزة."""
        if self._movie is not None:
            try:
                self._movie.stop()
            except Exception:
                pass
        self.mode = "poster" if self._frame is not None else "plain"
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
        self._rescale()

    def _on_reveal(self, v):
        self.reveal = float(v)
        self.update()

    def _on_settle(self, v):
        self.settle = float(v)
        if self.mode != "movie":        # الساكن لا يُعاد تحجيمه بإطاراته
            self._rescale()
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

    def _build_shade(self, w, h):
        """تعتيم الحواف، وظلٌّ أعمق خلف لوحة الدخول يُبقي حقولها واضحة."""
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
        return QtGui.QPixmap.fromImage(img)

    def paintEvent(self, _e):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QtGui.QPainter(self)
        if self._scaled is None and self._frame is not None:
            self._rescale()
        if self._scaled is not None:
            p.drawPixmap(0, 0, self._scaled)
        else:
            g = QtGui.QLinearGradient(0, 0, 0, h)
            g.setColorAt(0.0, QtGui.QColor("#0B0906"))
            g.setColorAt(1.0, QtGui.QColor("#020201"))
            p.fillRect(self.rect(), QtGui.QBrush(g))
        key = (w, h, self.side, round(self._dpr(), 2))
        if self._shade is None or self._shade_key != key:
            self._shade, self._shade_key = self._build_shade(w, h), key
        p.drawPixmap(0, 0, self._shade)
        # الظهور من العتمة والخروج إليها — طبقةٌ سوداء تخفّ وتشتدّ
        dark = (1.0 - self.reveal) + 0.88 * self.exit
        if dark > 0.004:
            p.fillRect(self.rect(),
                       QtGui.QColor(0, 0, 0, int(255 * min(1.0, dark))))
        p.end()
        if not getattr(self, "_announced", False):
            self._announced = True
            self.first_paint.emit()

    def set_exit(self, v):
        """يضبط الخروج: تعتيمٌ واقترابٌ خفيف (يُعاد التحجيم مع الاقتراب)."""
        self.exit = float(v)
        if self.mode != "movie":
            self._rescale()
        self.update()
