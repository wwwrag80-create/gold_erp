# -*- coding: utf-8 -*-
"""المسرح الذهبي — خلفيةٌ متحرّكة تُرسم ولا تُستورد.

**لماذا رسمٌ لا فيديو ولا صور**: النظام يُسلَّم ملفاً تنفيذياً واحداً،
وكل صورةٍ أو مقطعٍ يُضاف يُثقل الملف ويُفقد إن نُقل بجوار الـexe.
الرسم بـ`QPainter` لا يحتاج أصلاً خارجياً، ويخرج حادّاً على أي دقة
شاشة — والحجم صفر.

**والحركة هادئة بقصد**: هذه واجهةُ محاسبةٍ يفتحها صاحبُها كل صباح،
فحركةٌ صاخبة تُضجر في الأسبوع الأول. الإيقاع هنا بطيء: غبارٌ ذهبي
يرتفع، وخواتمُ تدور دورةً كاملة في دقيقة، ولمعةٌ تعبر العنوان كل
ستّ ثوانٍ. تُرى أول مرة فتُبهج، وتُنسى بعدها فلا تُزعج.

**والكلفة محسوبة**: ثلاثون إطاراً في الثانية، وكل إطارٍ رسمُ أشكالٍ
معدودة بلا ضبابٍ ولا شفافياتٍ متراكبة (فمرشّح الضباب على شاشةٍ
كاملة يُقيم وحده نصف وحدة المعالجة). وتتوقّف المؤقّتات عند الإخفاء
— فلا تدور حركةٌ لا يراها أحد.
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

FPS = 30


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


class GoldStage(QtWidgets.QWidget):
    """خلفية البوابة: غبار ذهب · خواتم دائرة · وهجٌ يتنفّس."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.t = 0.0                    # الزمن بالثواني
        self.intro = 0.0                # 0←1 مع دخول الشاشة
        self.exit = 0.0                 # 0←1 عند التسليم للنظام
        self._dust = []
        self._seed(90)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._tick)

    # ─────────────────────────────── الحياة
    def _seed(self, n):
        rnd = random.Random(20260921)
        self._dust = [{
            "x": rnd.random(), "y": rnd.random(),
            "r": rnd.uniform(0.8, 2.8),
            "v": rnd.uniform(0.006, 0.030),     # سرعة الصعود
            "s": rnd.uniform(0.25, 1.0),        # شدّة اللمعان
            "w": rnd.uniform(0.4, 1.6),         # تذبذب أفقي
            "p": rnd.uniform(0, 6.283),
        } for _ in range(n)]

    def start(self):
        if animations_on() and not self._timer.isActive():
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

    def _tick(self):
        self.t += 1.0 / FPS
        for d in self._dust:
            d["y"] -= d["v"] / FPS
            if d["y"] < -0.05:
                d["y"] = 1.05
        self.update()

    # ─────────────────────────────── الرسم
    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        self._bg(p, w, h)
        self._rings(p, w, h)
        self._dust_layer(p, w, h)
        self._vignette(p, w, h)
        if self.exit > 0.001:
            self._flash(p, w, h)
        p.end()

    def _bg(self, p, w, h):
        """ليلٌ دافئ، وفي وسطه وهجٌ يتنفّس ببطء."""
        g = QtGui.QLinearGradient(0, 0, w * 0.35, h)
        g.setColorAt(0.0, NIGHT)
        g.setColorAt(0.55, NIGHT2)
        g.setColorAt(1.0, NIGHT)
        p.fillRect(0, 0, w, h, QtGui.QBrush(g))

        breathe = 0.5 + 0.5 * math.sin(self.t * 0.45)
        cx, cy = w * 0.5, h * 0.44
        rad = max(w, h) * (0.42 + 0.03 * breathe)
        rg = QtGui.QRadialGradient(cx, cy, rad)
        c0 = QtGui.QColor(GLOW)
        c0.setAlpha(int(95 + 35 * breathe))
        c1 = QtGui.QColor(GLOW)
        c1.setAlpha(0)
        rg.setColorAt(0.0, c0)
        rg.setColorAt(1.0, c1)
        p.fillRect(0, 0, w, h, QtGui.QBrush(rg))

    def _rings(self, p, w, h):
        """خواتم تدور: ثلاث حلقاتٍ بأحجارٍ صغيرة على محيطها.

        الحلقة هنا اختصارُ الصنعة كلِّها — خاتمٌ وسوارٌ وطوق، ودورانُها
        البطيء يُعطي عمقاً بلا أن يسرق النظر من العنوان.
        """
        cx, cy = w * 0.5, h * 0.44
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
            r = base * frac * grow
            ang = self.t * 6.0 * speed          # ستّ درجاتٍ في الثانية
            p.save()
            p.rotate(ang)
            pen = QtGui.QPen(self._ink(GOLD_DIM, alpha * 0.55 * fade))
            pen.setWidthF(max(1.0, base * 0.0016))
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QRectF(-r, -r, 2 * r, 2 * r))
            # أحجارٌ على المحيط — وميضُها متفاوت فتبدو حيّة
            for k in range(gems):
                a = 2 * math.pi * k / gems
                x, y = r * math.cos(a), r * math.sin(a)
                tw = 0.45 + 0.55 * abs(math.sin(self.t * 1.1 + k * 0.7 + i))
                s = base * 0.0042 * (0.7 + 0.8 * tw)
                col = GOLD_HI if k % 4 else PEARL
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(self._ink(col, alpha * tw * fade))
                p.drawEllipse(QtCore.QRectF(x - s, y - s, 2 * s, 2 * s))
            p.restore()
        p.restore()

    def _dust_layer(self, p, w, h):
        """غبار الذهب: ذرّاتٌ ترتفع وتتمايل — أثرُ الورشة لا زينةَ شاشة."""
        fade = (self.intro ** 0.8) * (1.0 - self.exit * 0.8)
        if fade <= 0.01:
            return
        p.setPen(QtCore.Qt.NoPen)
        for d in self._dust:
            x = (d["x"] + 0.012 * math.sin(self.t * 0.5 * d["w"] + d["p"])) * w
            y = d["y"] * h
            a = d["s"] * fade * (0.35 + 0.65 * abs(
                math.sin(self.t * 0.8 + d["p"])))
            r = d["r"] * max(1.0, min(w, h) / 900.0)
            p.setBrush(self._ink(GOLD_HI, a * 0.75))
            p.drawEllipse(QtCore.QRectF(x - r, y - r, 2 * r, 2 * r))

    def _vignette(self, p, w, h):
        """حوافُّ داكنة تُبقي النظر في الوسط حيث الكلامُ والحقول."""
        g = QtGui.QRadialGradient(w * 0.5, h * 0.5, max(w, h) * 0.75)
        c0 = QtGui.QColor(0, 0, 0, 0)
        c1 = QtGui.QColor(0, 0, 0, 120)
        g.setColorAt(0.55, c0)
        g.setColorAt(1.0, c1)
        p.fillRect(0, 0, w, h, QtGui.QBrush(g))

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
        c = QtGui.QColor(color)
        c.setAlphaF(max(0.0, min(1.0, float(alpha))))
        return c


class ShineLabel(QtWidgets.QLabel):
    """عنوانٌ تعبره لمعةٌ ذهبية كل بضع ثوانٍ.

    **اللمعة في حبر الحرف لا فوقه**: النصّ يُرسم هنا بقلمٍ فرشاتُه
    تدرّجٌ متحرّك، فتمرّ اللمعة داخل الحروف نفسها. والمحاولة الأولى
    كانت طبقةً تُرسم فوق اللافتة بوضع تركيبٍ (`SourceAtop`)، فطلَت
    مستطيلَ اللافتة كلَّه لا حروفَها — لأن اللافتة شفافة الخلفية،
    فالتركيب يقع على ما خلفها من مسرحٍ لا على حبرها. الرسم بالقلم
    يجعل اللمعة محصورةً في الحرف مهما كان خلفه.
    """

    def __init__(self, text="", parent=None, period=6.0):
        super().__init__(text, parent)
        self.period = float(period)
        self._phase = -0.35
        self.setAlignment(QtCore.Qt.AlignCenter)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._tick)

    def start(self):
        if animations_on() and not self._timer.isActive():
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
        self._phase += 1.0 / (FPS * self.period)
        if self._phase > 1.35:
            self._phase = -0.35
        self.update()

    def paintEvent(self, _e):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        p.setFont(self.font())
        base = self.palette().color(QtGui.QPalette.WindowText)
        if self._timer.isActive():
            x = self._phase * w
            band = max(60.0, w * 0.26)
            g = QtGui.QLinearGradient(x - band, 0, x + band, 0)
            g.setColorAt(0.0, base)
            g.setColorAt(0.5, PEARL)
            g.setColorAt(1.0, base)
            p.setPen(QtGui.QPen(QtGui.QBrush(g), 1))
        else:
            p.setPen(base)
        flags = int(self.alignment())
        if self.wordWrap():
            flags |= int(QtCore.Qt.TextWordWrap)
        p.drawText(self.rect(), flags, self.text())
        p.end()
