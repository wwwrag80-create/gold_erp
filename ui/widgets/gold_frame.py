# -*- coding: utf-8 -*-
"""إطارات بوابة الدخول — هادئةٌ فاخرة، بلا ذهبٍ لامع ولا لمعةٍ تمرّ.

**الطلب (4.31)**: الإطار الذهبي المصقول ولمعته أُلغيا؛ والمطلوب شيءٌ
مريحٌ هادئ بإطاراتٍ عالية الجودة. فالفخامة هنا من **الدقّة لا البريق**:

* **زجاجٌ داكن** بتدرّجٍ عمودي خفيف ولمعةٍ ساكنة في أعلاه (الضوء من
  فوق) — سطحٌ يُرى عمقه ولا يلمع.
* **إطارٌ مزدوج بخيطين رفيعين** كـ«باسبارتو» اللوحات: خيطٌ خارجيّ
  فاتحٌ شبه شفاف، وخيطٌ شمبانيّ خافت إلى الداخل بفاصلٍ ثابت. ولا شيء
  يتحرّك — العين تستريح على خطوطٍ مستقرّة.
* **ظلٌّ ناعم متعدّد الطبقات** يرفع اللوحة عن المسرح بلا حدٍّ يُرى.
* **حواف الشاشة**: تعتيمٌ ناعم (vignette) وإطارٌ رفيع بخيطين على بُعدٍ
  من الحافة — يؤطّر المشهد كلوحةٍ معلّقة، بلا أركانٍ مزخرفة.

كل الرسم ساكن: لا مؤقّت ولا إعادة رسمٍ دورية — فلا كلفة بعد أول إطار.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

# الشمبانيا: ذهبٌ مُطفأ دافئ — يؤطّر ولا يلمع
CHAMPAGNE = (214, 192, 140)
PEARL = (255, 248, 232)


def _c(rgb, a):
    return QtGui.QColor(rgb[0], rgb[1], rgb[2], int(a))


def _rounded(rect, radius):
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(rect), radius, radius)
    return path


def draw_frame(p, rect, radius=22.0, gap=8.0, strong=1.0):
    """إطارٌ مزدوج بخيطين رفيعين — خارجيّ لؤلؤيّ وداخليّ شمبانيّ."""
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    r = QtCore.QRectF(rect)
    p.setBrush(QtCore.Qt.NoBrush)
    # الخيط الخارجي: أعلاه أفتح من أسفله — ضوءٌ ساكن من فوق
    g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0.0, _c(PEARL, 70 * strong))
    g.setColorAt(1.0, _c(PEARL, 18 * strong))
    p.setPen(QtGui.QPen(QtGui.QBrush(g), 1.0))
    p.drawPath(_rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), radius))
    # الخيط الداخلي: شمبانيّ خافت على بُعدٍ ثابت (باسبارتو)
    inner = r.adjusted(gap, gap, -gap, -gap)
    p.setPen(QtGui.QPen(_c(CHAMPAGNE, 62 * strong), 1.0))
    p.drawPath(_rounded(inner, max(4.0, radius - gap)))
    p.restore()


class GlassCard(QtWidgets.QWidget):
    """لوحة الدخول: زجاجٌ داكن في إطارٍ مزدوج رفيع — ساكنةٌ تماماً."""

    MARGIN = 14               # مساحة الظلّ حول اللوحة
    RADIUS = 22.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)

    # توافقٌ مع من كان يستدعيهما — لا لمعة بعد اليوم
    def start_shine(self):
        return None

    def stop_shine(self):
        return None

    def frame_rect(self):
        m = self.MARGIN
        return QtCore.QRectF(self.rect()).adjusted(m, m, -m, -m)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = self.frame_rect()
        radius = self.RADIUS
        # ── الظلّ: طبقاتٌ كثيرة خفيفة فيذوب ولا يُرى له حدّ ──
        p.setPen(QtCore.Qt.NoPen)
        n = 12
        for i in range(n):
            grow = 1.0 + i * (self.MARGIN - 2) / n
            a = int(20 * (1.0 - i / n) ** 1.7) + 1
            p.setBrush(QtGui.QColor(0, 0, 0, a))
            p.drawRoundedRect(r.adjusted(-grow, -grow + 5, grow, grow + 6),
                              radius + grow, radius + grow)
        # ── الزجاج: دافئٌ في أعلاه أعمق في أسفله ──
        body = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
        body.setColorAt(0.0, QtGui.QColor(40, 33, 24, 236))
        body.setColorAt(0.55, QtGui.QColor(27, 22, 16, 240))
        body.setColorAt(1.0, QtGui.QColor(20, 16, 12, 244))
        p.setBrush(QtGui.QBrush(body))
        p.drawRoundedRect(r, radius, radius)
        # لمعةٌ ساكنة على ثلث السطح الأعلى
        gloss = QtGui.QLinearGradient(r.topLeft(), QtCore.QPointF(
            r.left(), r.top() + r.height() * 0.32))
        gloss.setColorAt(0.0, _c(PEARL, 20))
        gloss.setColorAt(1.0, _c(PEARL, 0))
        p.setBrush(QtGui.QBrush(gloss))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        # ── الإطار المزدوج الرفيع ──
        draw_frame(p, r, radius=radius, gap=8.0)
        p.end()


# الاسم القديم — لمن يستورده
GoldCard = GlassCard


def screen_overlay(w, h, dpr=1.0):
    """حواف الشاشة: تعتيمٌ ناعم وإطارٌ رفيع بخيطين — صورةٌ تُرسم مرة.

    تُرسم عند تغيّر المقاس وتُلصق كل إطار — فالتعتيم الشعاعي على
    شاشة 4K لا يُحسب ستين مرة في الثانية. بقناة شفافية صريحة: الصورة
    بلا ألفا كانت ستغطّي المسرح كلّه بدل حوافه.
    """
    w, h = max(1, int(w)), max(1, int(h))
    img = QtGui.QImage(int(w * dpr), int(h * dpr),
                       QtGui.QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    # ── التعتيم: ضوءٌ في الوسط، والحواف تغرق في ظلٍّ ناعم ──
    rg = QtGui.QRadialGradient(w / 2.0, h * 0.46, max(w, h) * 0.74)
    rg.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
    rg.setColorAt(0.56, QtGui.QColor(0, 0, 0, 0))
    rg.setColorAt(0.86, QtGui.QColor(0, 0, 0, 90))
    rg.setColorAt(1.0, QtGui.QColor(0, 0, 0, 150))
    p.fillRect(QtCore.QRectF(0, 0, w, h), QtGui.QBrush(rg))
    # ── الإطار: خيطان رفيعان على بُعدٍ من الحافة ──
    inset = max(18.0, min(w, h) * 0.024)
    fr = QtCore.QRectF(inset, inset, w - 2 * inset, h - 2 * inset)
    draw_frame(p, fr, radius=18.0, gap=6.0, strong=0.75)
    p.end()
    return QtGui.QPixmap.fromImage(img)
