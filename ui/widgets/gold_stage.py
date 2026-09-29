# -*- coding: utf-8 -*-
"""المسرح الذهبي — خلفيةٌ متحرّكة تُرسم ولا تُستورد.

**لماذا رسمٌ لا فيديو ولا صور**: النظام يُسلَّم ملفاً تنفيذياً واحداً،
وكل صورةٍ أو مقطعٍ يُضاف يُثقل الملف ويُفقد إن نُقل بجوار الـexe.
الرسم بـ`QPainter` لا يحتاج أصلاً خارجياً، ويخرج حادّاً على أي دقة
شاشة — والحجم صفر.

**الجيل الثاني من المسرح** — ما تغيّر ولماذا:

  · **ستون إطاراً في الثانية بزمنٍ حقيقي**: كان كل إطارٍ يُقدّم الزمن
    ثابتاً (١/٣٠ ثانية) فيبطؤ المشهد على الجهاز المشغول ويتقطّع. الآن
    يُقاس الزمن الفعلي بين الإطارين، فالحركة بسرعتها نفسها على كل
    جهاز — والإطارات تتضاعف فتنعم.
  · **طبقاتٌ تُرسم مرةً لا كل إطار**: الخلفية المتدرّجة والإطار الداكن
    والوهج تُحسب عند تغيّر المقاس وحده، ثم تُنسخ نسخاً. بهذا صارت
    الستون إطاراً أرخص من الثلاثين القديمة.
  · **حبيباتٌ تمنع التشرّط**: التدرّج الداكن على شاشات ٨ بت يظهر
    أشرطةً متدرّجة؛ طبقةُ حبيباتٍ خافتة (dithering) تذيبها فيبدو الليل
    ناعماً كالمخمل — تقنيةُ استوديوهات الصورة نفسها.
  · **عمقٌ بثلاث طبقات**: غبارٌ بعيدٌ دقيق، ووسطٌ، وقريبٌ كبيرٌ ضبابيّ
    (bokeh) — كلٌّ بسرعته، وتُرسم بمزجٍ ضوئيّ جمعيّ فتتوهّج حيث تتلاقى.
  · **منظورٌ يتبع اليد**: تحريكُ الفأرة يُزيح الطبقات بمقاديرَ مختلفة
    (parallax) فيشعر الناظر بعمقٍ حقيقي — بلا أن يُطلب منه شيء.
  · **أشعّةٌ خلف الشعار** تدور ببطءٍ شديد، و**خواتمُ تُرسم نفسها** عند
    الظهور ثم تلمع بتدرّجٍ معدنيّ يدور حولها، ووميضُ نجمةٍ على حجرٍ
    بين حين وآخر.
  · **هالةٌ حول لوحة الدخول** ونقطةُ ضوءٍ تطوف حافّتها — تُرسم على
    المسرح خلف اللوحة، فلا مؤثّر فوق الحقول يعيد رسمها مع كل نبضة مؤشّر.
  · **الخروج قفزةٌ ضوئية**: عند الدخول ينطلق الغبار شعاعياً خطوطاً من
    المركز وتتّسع الموجة الذهبية — ثم يظهر النظام.
  · **وعيٌ بالأداء**: إن طال رسمُ الإطار على جهازٍ ضعيف ينزل المسرح
    وحده إلى ثلاثين إطاراً، ويعود للستين حين يخفّ الحمل.

**والحركة هادئة بقصد**: هذه واجهةُ محاسبةٍ يفتحها صاحبُها كل صباح،
فالإيقاع بطيء — تُرى أول مرة فتُبهج، وتُنسى بعدها فلا تُزعج. وتتوقّف
المؤقّتات عند الإخفاء — فلا تدور حركةٌ لا يراها أحد.
"""
import math
import os
import random

from PyQt5 import QtCore, QtGui, QtWidgets

# لوحة المسرح: ليلٌ دافئ يتدرّج إلى ذهبٍ معتّق
NIGHT = QtGui.QColor("#17120C")
NIGHT2 = QtGui.QColor("#241B10")
GLOW = QtGui.QColor("#4A3616")
GOLD = QtGui.QColor("#C9A227")
GOLD_HI = QtGui.QColor("#F0D98A")
GOLD_DIM = QtGui.QColor("#8A6F1E")
PEARL = QtGui.QColor("#FFF6DC")

FPS = 60                    # الهدف — وينزل وحده إلى LOW_FPS إن ثقل الرسم
LOW_FPS = 30
_SLOW_MS = 13.0             # متوسّط رسمٍ فوقه يُخفَّف الإيقاع
_FAST_MS = 6.0              # ودونه يعود للستّين


def animations_on():
    """هل تُشغَّل الحركة؟

    تُطفأ في ثلاث حالات: متغيّر بيئة صريح (`GOLD_ERP_NO_ANIM`)، أو
    إعدادٌ في `config`، أو تشغيلٌ بلا شاشة حقيقية (اختبارات offscreen)
    — فلا يدور مؤقّتٌ في خادمٍ لا شاشة له.
    """
    # الإطفاء الصريح يغلب كل شيء: من أطفأها أطفأها
    if os.environ.get("GOLD_ERP_NO_ANIM", "").strip() not in ("", "0"):
        return False
    try:
        import config
        if getattr(config, "SPLASH_ANIMATION", True) is False:
            return False
    except Exception:
        pass
    # تجاوزٌ صريح: لالتقاط اللقطات والمعاينة بلا شاشةٍ حقيقية
    if os.environ.get("GOLD_ERP_FORCE_ANIM", "").strip() not in ("", "0"):
        return True
    if os.environ.get("QT_QPA_PLATFORM", "").strip().startswith("offscreen"):
        return False
    return True


def _ink(color, alpha):
    """لونٌ بشفافية — يصلح قلماً وفرشاةً معاً."""
    c = QtGui.QColor(color)
    c.setAlphaF(max(0.0, min(1.0, float(alpha))))
    return c


def _smooth(x):
    """منحنى دخولٍ وخروجٍ ناعم (smoothstep) بين 0 و1."""
    x = max(0.0, min(1.0, float(x)))
    return x * x * (3.0 - 2.0 * x)


_SPRITES = {}


def glow_sprite(radius, core=GOLD_HI, soft=0.55):
    """نقطةُ ضوءٍ ناعمة (قلبٌ ساطع وهالةٌ تذوب) — تُرسم مرةً وتُنسخ.

    الرسم بنسخ صورةٍ صغيرةٍ جاهزة أرخص بكثير من تدرّجٍ دائريٍّ لكل
    ذرّةٍ في كل إطار — وهو ما يسمح بمئة ذرّةٍ متوهّجة بستّين إطاراً.
    """
    key = (int(radius), core.rgba(), round(soft, 2))
    pix = _SPRITES.get(key)
    if pix is not None:
        return pix
    r = max(2, int(radius))
    img = QtGui.QImage(2 * r, 2 * r, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    g = QtGui.QRadialGradient(r, r, r)
    g.setColorAt(0.0, _ink(PEARL, 1.0))
    g.setColorAt(0.18, _ink(core, 0.95))
    g.setColorAt(soft, _ink(core, 0.28))
    g.setColorAt(1.0, _ink(core, 0.0))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QBrush(g))
    p.drawEllipse(QtCore.QRectF(0, 0, 2 * r, 2 * r))
    p.end()
    pix = QtGui.QPixmap.fromImage(img)
    _SPRITES[key] = pix
    return pix


_GRAIN = []


def _grain_tile(size=96, strength=7, seed=1809):
    """بلاطة حبيباتٍ خافتة — تُذيب أشرطة التدرّج على الشاشات الداكنة."""
    if _GRAIN:
        return _GRAIN[0]
    rnd = random.Random(seed)
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.transparent)
    for y in range(size):
        for x in range(size):
            v = rnd.random()
            if v < 0.5:
                a = int(strength * (0.5 - v) * 2)
                img.setPixel(x, y, QtGui.qRgba(0, 0, 0, a))
            else:
                a = int(strength * (v - 0.5) * 2)
                img.setPixel(x, y, QtGui.qRgba(a, a, a, a))
    _GRAIN.append(QtGui.QPixmap.fromImage(img))
    return _GRAIN[0]


class GoldStage(QtWidgets.QWidget):
    """خلفية البوابة: غبارٌ بعمق · أشعّة · خواتم معدنية · هالة · قفزة ضوء."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, False)
        # لا `WA_OpaquePaintEvent` هنا عمداً: المسرح يغطّي البوابة كلها،
        # فلو أُعلن معتماً لأسقط Qt رسمَ البوابة نفسها — وأولُ رسمٍ لها
        # هو الإشارة التي تُغلق شاشة بدء الـexe في لحظتها.
        self.setAutoFillBackground(False)
        self.t = 0.0                    # الزمن بالثواني
        self.intro = 0.0                # 0←1 مع دخول الشاشة
        self.exit = 0.0                 # 0←1 عند التسليم للنظام
        self.ripple = -1.0              # <0 = ساكن، 0←1 = موجةٌ تنتشر
        self.focus_y = 0.44             # مركز الموجة نسبةً من الارتفاع
        # موضع الشعار (لمركز الأشعّة) ولوحة الدخول (لهالتها) — يضعهما
        # من يستضيف المسرح؛ وبدونهما يرسم المسرح نفسه كاملاً بلا نقص.
        self.logo_center = None         # QPointF
        self.card_rect = None           # QRectF
        self.card_k = 0.0               # ظهور اللوحة 0←1
        # ══ الوضع الهادئ (4.31) ══ بلا أشعّة، ولا مذنّبٍ يطوف اللوحة،
        # ولا لمعةٍ تدور على الخواتم ولا وميض نجوم — حلقاتٌ رفيعة ساكنة
        # الضوء وغبارٌ بطيء فقط. شاشةٌ تُفتح كل صباح: تُريح ولا تُبهر.
        self.calm = False
        self._par = QtCore.QPointF(0.0, 0.0)     # إزاحة المنظور الحالية
        self._dust = []
        self._seed()
        self._bg = None                 # الخلفية الثابتة المخبّأة
        self._breath = None             # الوهج المتنفّس المخبّأ
        self._halo = None               # هالة اللوحة المخبّأة
        self._halo_key = None
        self._halo_pad = 0
        self._frame_ms = 0.0            # متوسّط زمن الرسم (للإيقاع الذكي)
        self._clock = QtCore.QElapsedTimer()
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._tick)

    # ─────────────────────────────── الحياة
    def _seed(self):
        rnd = random.Random(20260921)
        # (العدد · نصف القطر · السرعة · الشدّة · عمق المنظور)
        layers = ((70, (0.7, 1.6), (0.004, 0.012), (0.25, 0.65), 0.25),
                  (38, (1.6, 3.0), (0.010, 0.024), (0.35, 0.85), 0.55),
                  (14, (5.0, 11.0), (0.016, 0.034), (0.10, 0.28), 1.0))
        self._dust = []
        for n, rr, vv, ss, depth in layers:
            for _ in range(n):
                self._dust.append({
                    "x": rnd.random(), "y": rnd.random(),
                    "r": rnd.uniform(*rr), "v": rnd.uniform(*vv),
                    "s": rnd.uniform(*ss), "w": rnd.uniform(0.4, 1.6),
                    "p": rnd.uniform(0, 6.283), "d": depth})

    def start(self):
        if animations_on() and not self._timer.isActive():
            self._clock.restart()
            self._timer.start()

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self.start()

    def hideEvent(self, e):
        # لا تدور حركةٌ لا يراها أحد
        self.stop()
        super().hideEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg = self._breath = None      # تُعاد بمقاسها الجديد

    def _tick(self):
        # الزمن الحقيقي بين إطارين — لا خطوةٌ ثابتة تبطؤ مع الحمل
        dt = self._clock.restart() / 1000.0 if self._clock.isValid() \
            else 1.0 / FPS
        dt = max(0.0, min(0.05, dt))
        self.t += dt
        for d in self._dust:
            d["y"] -= d["v"] * dt
            if d["y"] < -0.05:
                d["y"] = 1.05
        # منظورٌ يتبع الفأرة بليونة
        try:
            w, h = max(1, self.width()), max(1, self.height())
            m = self.mapFromGlobal(QtGui.QCursor.pos())
            tx = max(-1.0, min(1.0, (m.x() / w - 0.5) * 2))
            ty = max(-1.0, min(1.0, (m.y() / h - 0.5) * 2))
            k = min(1.0, dt * 2.5)
            self._par = QtCore.QPointF(
                self._par.x() + (tx - self._par.x()) * k,
                self._par.y() + (ty - self._par.y()) * k)
        except Exception:
            pass
        self.update()

    def _pace(self, ms):
        """إيقاعٌ يتكيّف: ستّون إطاراً ما احتمل الجهاز، وإلا ثلاثون."""
        self._frame_ms = ms if self._frame_ms <= 0 \
            else self._frame_ms * 0.9 + ms * 0.1
        want = None
        if self._frame_ms > _SLOW_MS and self._timer.interval() < 30:
            want = int(1000 / LOW_FPS)
        elif self._frame_ms < _FAST_MS and self._timer.interval() > 20:
            want = int(1000 / FPS)
        if want is not None:
            self._timer.setInterval(want)

    # ─────────────────────────────── الطبقات المخبّأة
    def _dpr(self):
        try:
            return max(1.0, float(self.devicePixelRatioF()))
        except Exception:
            return 1.0

    def _canvas(self, w, h):
        dpr = self._dpr()
        pix = QtGui.QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pix.setDevicePixelRatio(dpr)
        return pix

    def _build_bg(self, w, h):
        """الليل الدافئ + الوهج الأساسي + الإطار الداكن + الحبيبات."""
        pix = self._canvas(w, h)
        pix.fill(NIGHT)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        g = QtGui.QLinearGradient(0, 0, w * 0.35, h)
        g.setColorAt(0.0, NIGHT)
        g.setColorAt(0.55, NIGHT2)
        g.setColorAt(1.0, NIGHT)
        p.fillRect(0, 0, w, h, QtGui.QBrush(g))
        cx, cy = w * 0.5, h * 0.44
        rg = QtGui.QRadialGradient(cx, cy, max(w, h) * 0.46)
        rg.setColorAt(0.0, _ink(GLOW, 0.40))
        rg.setColorAt(0.6, _ink(GLOW, 0.14))
        rg.setColorAt(1.0, _ink(GLOW, 0.0))
        p.fillRect(0, 0, w, h, QtGui.QBrush(rg))
        # الإطار الداكن: يُبقي النظر في الوسط حيث الكلامُ والحقول
        vg = QtGui.QRadialGradient(w * 0.5, h * 0.5, max(w, h) * 0.75)
        vg.setColorAt(0.55, QtGui.QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QtGui.QColor(0, 0, 0, 130))
        p.fillRect(0, 0, w, h, QtGui.QBrush(vg))
        p.fillRect(0, 0, w, h, QtGui.QBrush(_grain_tile()))
        p.end()
        return pix

    def _build_breath(self, w, h):
        """وهجٌ إضافيّ يُمزج بشفافيةٍ متنفّسة — فوق الخلفية الثابتة."""
        r = max(w, h) * 0.34
        pix = self._canvas(2 * r, 2 * r)
        pix.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pix)
        g = QtGui.QRadialGradient(r, r, r)
        g.setColorAt(0.0, _ink(GOLD, 0.16))
        g.setColorAt(0.45, _ink(GLOW, 0.14))
        g.setColorAt(1.0, _ink(GLOW, 0.0))
        p.fillRect(QtCore.QRectF(0, 0, 2 * r, 2 * r), QtGui.QBrush(g))
        p.end()
        return pix

    def _build_halo(self, rect):
        """هالةٌ ناعمة حول لوحة الدخول — حوافٌ متتالية تذوب للخارج."""
        pad = 46
        w, h = rect.width() + 2 * pad, rect.height() + 2 * pad
        pix = self._canvas(w, h)
        pix.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setBrush(QtCore.Qt.NoBrush)
        steps = 22
        for i in range(steps):
            f = i / float(steps)
            grow = pad * (1.0 - f)
            a = 0.10 * (f ** 2.2)
            pen = QtGui.QPen(_ink(GOLD, a))
            pen.setWidthF(pad / steps + 1.2)
            p.setPen(pen)
            p.drawRoundedRect(QtCore.QRectF(pad - grow, pad - grow,
                                            rect.width() + 2 * grow,
                                            rect.height() + 2 * grow),
                              16 + grow, 16 + grow)
        p.end()
        return pix, pad

    # ─────────────────────────────── الرسم
    def paintEvent(self, _e):
        timer = QtCore.QElapsedTimer()
        timer.start()
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        if self._bg is None or self._bg.size() != QtCore.QSize(
                int(w * self._dpr()), int(h * self._dpr())):
            self._bg = self._build_bg(w, h)
            self._breath = self._build_breath(w, h)
        p.drawPixmap(0, 0, self._bg)
        self._breathe(p, w, h)
        self._rays(p, w, h)
        self._rings(p, w, h)
        self._card_glow(p)
        self._ripple(p, w, h)
        self._dust_layer(p, w, h)
        # حواف الشاشة: تعتيمٌ وإطارٌ ذهبي — صورةٌ مخبّأة تُلصق كما هي
        ov = getattr(self, "overlay", None)
        if ov is not None and not ov.isNull():
            p.drawPixmap(0, 0, ov)
        if self.exit > 0.001:
            self._flash(p, w, h)
        p.end()
        if self._timer.isActive():
            self._pace(timer.elapsed())

    def _breathe(self, p, w, h):
        """الوهج يتنفّس ببطء — شفافيةٌ تتغيّر، لا تدرّجٌ يُعاد حسابه."""
        if self._breath is None:
            return
        b = 0.5 + 0.5 * math.sin(self.t * 0.45)
        dpr = self._dpr()
        bw = self._breath.width() / dpr
        bh = self._breath.height() / dpr
        p.save()
        p.setOpacity(0.35 + 0.65 * b)
        p.drawPixmap(QtCore.QPointF(w * 0.5 - bw / 2, h * 0.44 - bh / 2),
                     self._breath)
        p.restore()

    def _center(self, w, h):
        c = self.logo_center
        if c is not None:
            return QtCore.QPointF(c)
        return QtCore.QPointF(w * 0.5, h * 0.30)

    def _rays(self, p, w, h):
        """أشعّةٌ رفيعة خلف الشعار تدور دورةً كل أربع دقائق.

        **طبقةٌ تُرسم بضع مراتٍ في الثانية لا ستّين**: دورانها درجةٌ
        ونصف في الثانية، فإعادة رسمها كل سُدس ثانية تكفي العين تماماً
        — والإطارات بينها نسخٌ للطبقة الجاهزة. هكذا نزلت كلفتها من
        أثقل طبقات المسرح إلى أخفّها.
        """
        fade = _smooth(self.intro) * (1.0 - self.exit)
        if fade <= 0.01 or self.calm:
            return
        c = self._center(w, h) + self._par * 5
        key = (int(self.t * 6), int(c.x()), int(c.y()), w, h)
        if getattr(self, "_rays_key", None) != key:
            self._rays_pix = self._build_rays(c, w, h)
            self._rays_key = key
        p.save()
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Plus)
        p.setOpacity(fade)
        p.drawPixmap(0, 0, self._rays_pix)
        p.restore()

    def _build_rays(self, c, w, h):
        pix = self._canvas(w, h)
        pix.fill(QtCore.Qt.transparent)
        q = QtGui.QPainter(pix)
        q.setRenderHint(QtGui.QPainter.Antialiasing, True)
        length = max(w, h) * 0.55
        # خافتةٌ بقصد: تُحَسّ ولا تُرى — شاشةٌ تُفتح كل صباح لا تُبهر
        # العين بل تريحها
        g = QtGui.QRadialGradient(c, length)
        g.setColorAt(0.0, _ink(GOLD_HI, 0.11))
        g.setColorAt(0.30, _ink(GOLD, 0.035))
        g.setColorAt(1.0, _ink(GOLD, 0.0))
        q.setPen(QtCore.Qt.NoPen)
        q.setBrush(QtGui.QBrush(g))
        n = 12
        spin = self.t * 1.5
        for i in range(n):
            a0 = math.radians(spin + i * 360.0 / n)
            wid = math.radians(3.2 + 1.6 * math.sin(self.t * 0.7 + i))
            path = QtGui.QPainterPath(c)
            path.lineTo(c.x() + length * math.cos(a0 - wid),
                        c.y() + length * math.sin(a0 - wid))
            path.lineTo(c.x() + length * math.cos(a0 + wid),
                        c.y() + length * math.sin(a0 + wid))
            path.closeSubpath()
            q.drawPath(path)
        q.end()
        return pix

    def _rings(self, p, w, h):
        """خواتم تدور: تُرسم نفسها عند الظهور ثم تلمع بتدرّجٍ معدنيّ.

        الحلقة اختصارُ الصنعة كلِّها — خاتمٌ وسوارٌ وطوق، ودورانُها
        البطيء يُعطي عمقاً بلا أن يسرق النظر من العنوان.
        """
        cx = w * 0.5 + self._par.x() * 9
        cy = h * 0.44 + self._par.y() * 7
        base = min(w, h)
        ease = self.intro ** 0.6
        grow = 0.86 + 0.14 * ease + 0.35 * (self.exit ** 2)
        fade = ease * (1.0 - self.exit)
        if fade <= 0.01:
            return
        p.save()
        p.translate(cx, cy)
        specs = ((0.30, 1.0, 16, 0.9), (0.42, -0.62, 24, 0.55),
                 (0.55, 0.38, 32, 0.32))
        for i, (frac, speed, gems, alpha) in enumerate(specs):
            # كل حلقةٍ تُرسم نفسها قوساً يكتمل — بتتابعٍ بين الثلاث
            draw = _smooth((self.intro - i * 0.12) / 0.7)
            if draw <= 0.002:
                continue
            r = base * frac * grow
            ang = self.t * 6.0 * speed          # ستّ درجاتٍ في الثانية
            p.save()
            p.rotate(ang)
            if self.calm:
                # خيطٌ شمبانيّ ساكن الضوء — بلا لمعةٍ تدور ولا أحجار
                pen = QtGui.QPen(_ink(GOLD_HI, alpha * 0.30 * fade),
                                 max(1.0, base * 0.0016))
                p.setPen(pen)
                p.setBrush(QtCore.Qt.NoBrush)
                rect = QtCore.QRectF(-r, -r, 2 * r, 2 * r)
                span = draw * 360.0
                if span >= 359.5:
                    p.drawEllipse(rect)
                else:
                    p.drawArc(rect, 90 * 16, int(-span * 16))
                p.restore()
                continue
            # قلمٌ معدنيّ: تدرّجٌ مخروطيّ يدور فيلمع جانبٌ ويخبو آخر
            cg = QtGui.QConicalGradient(0, 0, -ang * 2.0 + self.t * 20)
            cg.setColorAt(0.00, _ink(GOLD_DIM, alpha * 0.45 * fade))
            cg.setColorAt(0.20, _ink(GOLD_HI, alpha * 0.95 * fade))
            cg.setColorAt(0.28, _ink(PEARL, alpha * 1.00 * fade))
            cg.setColorAt(0.40, _ink(GOLD, alpha * 0.60 * fade))
            cg.setColorAt(0.70, _ink(GOLD_DIM, alpha * 0.35 * fade))
            cg.setColorAt(1.00, _ink(GOLD_DIM, alpha * 0.45 * fade))
            pen = QtGui.QPen(QtGui.QBrush(cg), max(1.2, base * 0.0021))
            pen.setCapStyle(QtCore.Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            rect = QtCore.QRectF(-r, -r, 2 * r, 2 * r)
            span = draw * 360.0
            if span >= 359.5:
                p.drawEllipse(rect)
            else:
                p.drawArc(rect, 90 * 16, int(-span * 16))
            # أحجارٌ على المحيط — تظهر حيث وصل القوس، ووميضُها متفاوت
            for k in range(gems):
                a_deg = 360.0 * k / gems
                if a_deg > span:
                    break
                a = math.radians(90.0 - a_deg)
                x, y = r * math.cos(a), -r * math.sin(a)
                tw = 0.45 + 0.55 * abs(math.sin(self.t * 1.1 + k * 0.7 + i))
                s = base * 0.0042 * (0.7 + 0.8 * tw)
                col = GOLD_HI if k % 4 else PEARL
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(_ink(col, alpha * tw * fade))
                p.drawEllipse(QtCore.QRectF(x - s, y - s, 2 * s, 2 * s))
                # وميضُ نجمةٍ على الحجر في ذروة لمعانه
                if tw > 0.985 and i == 0:
                    self._glint(p, x, y, s * 5.5, alpha * fade)
            p.restore()
        p.restore()

    @staticmethod
    def _glint(p, x, y, size, alpha):
        """نجمةٌ رباعية تومض — خطّان يتقاطعان ويذوبان من الطرفين."""
        p.save()
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Plus)
        for dx, dy in ((1, 0), (0, 1)):
            g = QtGui.QLinearGradient(x - dx * size, y - dy * size,
                                      x + dx * size, y + dy * size)
            g.setColorAt(0.0, _ink(PEARL, 0.0))
            g.setColorAt(0.5, _ink(PEARL, 0.85 * alpha))
            g.setColorAt(1.0, _ink(PEARL, 0.0))
            pen = QtGui.QPen(QtGui.QBrush(g), 1.4)
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(x - dx * size, y - dy * size),
                       QtCore.QPointF(x + dx * size, y + dy * size))
        p.restore()

    def _card_glow(self, p):
        """هالة اللوحة ونقطةُ ضوءٍ تطوف حافّتها كل ثماني ثوانٍ."""
        rect = self.card_rect
        k = self.card_k * (1.0 - self.exit)
        if rect is None or k <= 0.01 or rect.width() < 10:
            return
        key = (int(rect.width()), int(rect.height()))
        if self._halo is None or self._halo_key != key:
            self._halo, self._halo_pad = self._build_halo(rect)
            self._halo_key = key
        pad = self._halo_pad
        p.save()
        # الهادئ: هالةٌ خافتة ثابتة لا تتنفّس
        p.setOpacity(k * 0.38 if self.calm
                     else k * (0.75 + 0.25 * math.sin(self.t * 0.9)))
        p.drawPixmap(QtCore.QPointF(rect.x() - pad, rect.y() - pad),
                     self._halo)
        p.restore()
        if self.calm:
            return          # الهالة وحدها — بلا نقطة ضوءٍ تطوف الحافّة
        # المذنّب: رأسٌ ساطع وذيلٌ يخبو على مسار الحافّة
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect.adjusted(-1, -1, 1, 1), 16, 16)
        phase = (self.t / 8.0) % 1.0
        p.save()
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Plus)
        n = 28
        for j in range(n):
            f = (phase - j * 0.0022) % 1.0
            pt = path.pointAtPercent(f)
            a = k * (1.0 - j / float(n)) ** 1.8
            spr = glow_sprite(9 if j == 0 else 6)
            s = (9 if j == 0 else 5) * (1.0 - j / (n * 1.5))
            p.setOpacity(a)
            p.drawPixmap(QtCore.QRectF(pt.x() - s, pt.y() - s, 2 * s, 2 * s),
                         spr, QtCore.QRectF(spr.rect()))
        p.restore()

    def _ripple(self, p, w, h):
        """تموّجٌ ينبثق من موضع البطاقة قبل أن ترتفع.

        **لماذا موجة**: البطاقة كانت تظهر دفعةً واحدة فتبدو مقحمة.
        والموجة تصنع سبباً بصرياً لظهورها: شيءٌ لمس سطح المشهد من
        هنا، فما يخرج من موضع اللمسة يبدو نابعاً لا مُقحماً. ثلاث
        حلقاتٍ متتابعة تتّسع وتخفت، كالحجر يُلقى في ماء ساكن.
        """
        r0 = self.ripple
        if r0 < 0:
            return
        cx, cy = w * 0.5, h * self.focus_y
        base = min(w, h)
        p.save()
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Plus)
        p.setBrush(QtCore.Qt.NoBrush)
        for k in range(3):
            v = r0 - k * 0.16              # الحلقات تتأخّر عن بعضها
            if v <= 0 or v >= 1:
                continue
            rad = base * (0.06 + 0.62 * v)
            fade = (1.0 - v) ** 1.6 * (1.0 - 0.28 * k)
            # حلقةٌ بحافّةٍ ناعمة: خطٌّ عريضٌ خافت تحت خطٍّ رفيعٍ ساطع
            for width, a in ((base * 0.012 * (1.0 - v) + 3.0, 0.16),
                             (max(1.0, base * 0.0042 * (1.0 - v) + 0.6),
                              0.55)):
                pen = QtGui.QPen(_ink(GOLD_HI, a * fade))
                pen.setWidthF(width)
                p.setPen(pen)
                p.drawEllipse(QtCore.QRectF(cx - rad, cy - rad,
                                            2 * rad, 2 * rad))
        p.restore()

    def _dust_layer(self, p, w, h):
        """غبار الذهب بثلاثة أعماق — وعند الخروج ينطلق خطوطاً ضوئية."""
        # في آخر الموجة يخبو الغبار تماماً: يُبنى النظام خلف مشهدٍ هادئ
        # ساكنٍ بطبعه، فلا تُرى لحظةُ البناء توقّفاً في حركة
        fade = (self.intro ** 0.8) * (1.0 - self.exit ** 1.5)
        if fade <= 0.01:
            return
        scale = max(1.0, min(w, h) / 900.0)
        cx, cy = w * 0.5, h * 0.44
        warp = self.exit ** 1.6
        p.save()
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Plus)
        for d in self._dust:
            depth = d["d"]
            x = (d["x"] + 0.012 * math.sin(self.t * 0.5 * d["w"] + d["p"])) * w
            y = d["y"] * h
            x += self._par.x() * 22 * depth
            y += self._par.y() * 14 * depth
            a = d["s"] * fade * (0.35 + 0.65 * abs(
                math.sin(self.t * 0.8 + d["p"])))
            r = d["r"] * scale
            if warp > 0.001:
                # قفزةٌ ضوئية: كل ذرّةٍ تنطلق شعاعياً وتترك خطّاً خلفها
                push = 1.0 + 3.2 * warp * (0.6 + depth)
                nx, ny = cx + (x - cx) * push, cy + (y - cy) * push
                tail = 1.0 + 3.2 * max(0.0, warp - 0.08) * (0.6 + depth)
                tx, ty = cx + (x - cx) * tail, cy + (y - cy) * tail
                g = QtGui.QLinearGradient(tx, ty, nx, ny)
                g.setColorAt(0.0, _ink(GOLD_HI, 0.0))
                g.setColorAt(1.0, _ink(PEARL, min(1.0, a * 1.4)))
                pen = QtGui.QPen(QtGui.QBrush(g), max(1.0, r * 0.9))
                pen.setCapStyle(QtCore.Qt.RoundCap)
                p.setPen(pen)
                p.drawLine(QtCore.QPointF(tx, ty), QtCore.QPointF(nx, ny))
                continue
            # القريب ضبابيٌّ واسع الهالة (bokeh)، والبعيد نقطةٌ حادّة
            spr = glow_sprite(max(3, int(r * (3.2 if depth < 1 else 1.6))),
                              soft=0.35 if depth < 1 else 0.8)
            s = r * (3.2 if depth < 1 else 1.6)
            p.setOpacity(min(1.0, a * (0.9 if depth < 1 else 0.55)))
            p.drawPixmap(QtCore.QRectF(x - s, y - s, 2 * s, 2 * s), spr,
                         QtCore.QRectF(spr.rect()))
        p.restore()

    def _flash(self, p, w, h):
        """التسليم: موجةٌ ذهبية تتّسع ثم يبيضّ المسرح ويُسلِّم."""
        e = self.exit
        cx, cy = w * 0.5, h * 0.44
        rad = max(w, h) * (0.15 + 1.1 * e)
        g = QtGui.QRadialGradient(cx, cy, max(1.0, rad))
        edge = QtGui.QColor(GOLD_HI)
        edge.setAlpha(int(200 * min(1.0, e * 1.6) * (1.0 - e * 0.35)))
        mid = QtGui.QColor(GOLD)
        mid.setAlpha(int(90 * (1.0 - e)))
        clear = QtGui.QColor(GOLD)
        clear.setAlpha(0)
        g.setColorAt(max(0.0, 1.0 - 0.18), edge)
        g.setColorAt(max(0.0, 1.0 - 0.45), mid)
        g.setColorAt(0.0, clear)
        p.fillRect(0, 0, w, h, QtGui.QBrush(g))

    @staticmethod
    def _ink(color, alpha):
        """لونٌ بشفافية — يصلح قلماً وفرشاةً معاً."""
        return _ink(color, alpha)


class ShineLabel(QtWidgets.QLabel):
    """عنوانٌ تعبره لمعةٌ ذهبية كل بضع ثوانٍ — ويحيطه توهّجٌ خافت.

    **اللمعة في حبر الحرف لا فوقه**: النصّ يُرسم هنا بقلمٍ فرشاتُه
    تدرّجٌ متحرّك، فتمرّ اللمعة داخل الحروف نفسها. والمحاولة الأولى
    كانت طبقةً تُرسم فوق اللافتة بوضع تركيبٍ (`SourceAtop`)، فطلَت
    مستطيلَ اللافتة كلَّه لا حروفَها — لأن اللافتة شفافة الخلفية،
    فالتركيب يقع على ما خلفها من مسرحٍ لا على حبرها. الرسم بالقلم
    يجعل اللمعة محصورةً في الحرف مهما كان خلفه.

    **والتوهّج رسمٌ لا مؤثّر**: نسخٌ خافتة من النصّ حوله على دائرةٍ
    صغيرة تصنع هالةً ذهبية ناعمة — بلا `QGraphicsEffect` يرسم اللافتة
    في صورةٍ وسيطة ويشوّهها إن تغيّر مقاسها.
    """

    def __init__(self, text="", parent=None, period=6.0):
        super().__init__(text, parent)
        self.period = float(period)
        self._phase = -0.35
        self.glow = True
        self.setAlignment(QtCore.Qt.AlignCenter)
        self._clock = QtCore.QElapsedTimer()
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._tick)

    def start(self):
        if animations_on() and not self._timer.isActive():
            self._clock.restart()
            self._timer.start()

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self.start()

    def hideEvent(self, e):
        self.stop()
        super().hideEvent(e)

    def _tick(self):
        dt = self._clock.restart() / 1000.0 if self._clock.isValid() \
            else 1.0 / FPS
        dt = max(0.0, min(0.05, dt))
        self._phase += dt / self.period
        if self._phase > 1.35:
            self._phase = -0.35
        self.update()

    def paintEvent(self, _e):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setFont(self.font())
        base = self.palette().color(QtGui.QPalette.WindowText)
        flags = int(self.alignment())
        if self.wordWrap():
            flags |= int(QtCore.Qt.TextWordWrap)
        rect = QtCore.QRectF(self.rect())
        # الهالة: ثماني نسخٍ خافتة على دائرةٍ نصف قطرها ٢ بكسل
        if self.glow and base.alphaF() > 0.05:
            halo = _ink(GOLD, 0.10 * base.alphaF())
            p.setPen(halo)
            for i in range(8):
                a = i * math.pi / 4
                p.drawText(rect.translated(2.0 * math.cos(a),
                                           2.0 * math.sin(a)),
                           flags, self.text())
        if self._timer.isActive():
            x = self._phase * w
            band = max(60.0, w * 0.26)
            g = QtGui.QLinearGradient(x - band, 0, x + band, 0)
            g.setColorAt(0.0, base)
            g.setColorAt(0.5, _ink(PEARL, base.alphaF()))
            g.setColorAt(1.0, base)
            p.setPen(QtGui.QPen(QtGui.QBrush(g), 1))
        else:
            p.setPen(base)
        p.drawText(rect, flags, self.text())
        p.end()
