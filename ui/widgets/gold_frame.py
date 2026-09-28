# -*- coding: utf-8 -*-
"""إطارٌ ذهبي واقعي — للوحة الدخول وحواف الشاشة.

**لماذا يبدو المعدن معدناً**: الذهب المصقول لا لون له ثابت، بل
انعكاساتٌ متتالية لما حوله: ظلٌّ بني عميق، ثم ذهبٌ مشبع، ثم وميضٌ
أبيض ضيّق حيث يلتقي الضوء بالحافة، ثم ذهبٌ أدكن في الجهة الأخرى.
التدرّج بمحطّاتٍ كثيرة غير منتظمة (`METAL`) هو ما يصنع هذا الإحساس؛
ولونان فقط يعطيان «أصفر» لا «ذهباً».

وفوقه ثلاث طبقات تصنع العمق:
* **حافة بارزة (bevel)**: خطٌّ فاتح على الحافة العليا وداكن على
  السفلى — فتبدو الحافة مرفوعةً تحت ضوءٍ من الأعلى.
* **إطارٌ مزدوج**: شريطٌ عريض وخيطٌ رفيع داخله بفاصلٍ داكن — كإطار
  لوحةٍ حقيقي لا خطٍّ مرسوم.
* **زخارف الأركان**: ماسةٌ ذهبية وخطّا زخرفة في كل ركن.

كل الرسم هنا دوالّ صافية على `QPainter` — تُستعمل على اللوحة وعلى
طبقة حواف الشاشة (تُرسم مرةً في صورةٍ مخبّأة ثم تُلصق كل إطار).
"""
import math

from PyQt5 import QtCore, QtGui, QtWidgets

# محطّات الذهب المصقول: ظلّ · ذهب · وميض · ذهب · ظلّ · ذهب · وميض · ظلّ
METAL = (
    (0.00, "#4A300A"), (0.10, "#9C6F1E"), (0.22, "#E9C35A"),
    (0.30, "#FFF4C4"), (0.36, "#F3D475"), (0.48, "#B8862B"),
    (0.60, "#7A5413"), (0.72, "#D6AA45"), (0.80, "#FBE7A0"),
    (0.88, "#C9982F"), (1.00, "#5E3E0E"),
)


def metal_brush(rect, phase=0.0, angle=35.0):
    """فرشاة ذهبٍ مصقول على مستطيل — `phase` تُزيح الانعكاس (لمعة تمرّ)."""
    r = QtCore.QRectF(rect)
    c = r.center()
    d = max(r.width(), r.height()) * 0.75
    a = math.radians(angle)
    dx, dy = math.cos(a) * d, math.sin(a) * d
    g = QtGui.QLinearGradient(c.x() - dx, c.y() - dy, c.x() + dx, c.y() + dy)
    g.setSpread(QtGui.QGradient.ReflectSpread)
    shift = (phase % 1.0) * 0.5
    for pos, col in METAL:
        g.setColorAt(min(1.0, max(0.0, (pos + shift) % 1.0)), QtGui.QColor(col))
    # حدّا التدرّج ثابتان فلا يقفز اللون عند الالتفاف
    g.setColorAt(0.0, QtGui.QColor(METAL[0][1]))
    g.setColorAt(1.0, QtGui.QColor(METAL[-1][1]))
    return QtGui.QBrush(g)


def _rounded(rect, radius):
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(rect), radius, radius)
    return path


def draw_frame(p, rect, radius=16.0, band=5.0, phase=0.0, ornaments=True,
               inner_line=True):
    """إطارٌ ذهبي مزدوج ببروز وزخارف أركان داخل `rect`."""
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    r = QtCore.QRectF(rect)
    # ── ظلّ خارجي رفيع يفصل المعدن عمّا خلفه ──
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 150), 1.2))
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawPath(_rounded(r.adjusted(-0.6, -0.6, 0.6, 0.6), radius + 0.6))
    # ── الشريط المعدني: حلقةٌ بين مستطيلين ──
    outer = _rounded(r, radius)
    inner_r = r.adjusted(band, band, -band, -band)
    ring = outer.subtracted(_rounded(inner_r, max(2.0, radius - band)))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(metal_brush(r, phase))
    p.drawPath(ring)
    # ── البروز: ضوءٌ على الحافة العليا وظلّ على السفلى ──
    bev = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
    bev.setColorAt(0.0, QtGui.QColor(255, 250, 225, 170))
    bev.setColorAt(0.5, QtGui.QColor(255, 250, 225, 0))
    bev.setColorAt(1.0, QtGui.QColor(40, 24, 4, 150))
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QBrush(bev), 1.1))
    p.drawPath(_rounded(r.adjusted(0.8, 0.8, -0.8, -0.8), radius - 0.8))
    # الحافة الداخلية للشريط: عكس الضوء (تبدو غائرة نحو الداخل)
    bev2 = QtGui.QLinearGradient(inner_r.topLeft(), inner_r.bottomLeft())
    bev2.setColorAt(0.0, QtGui.QColor(40, 24, 4, 170))
    bev2.setColorAt(1.0, QtGui.QColor(255, 244, 205, 150))
    p.setPen(QtGui.QPen(QtGui.QBrush(bev2), 1.0))
    p.drawPath(_rounded(inner_r, max(2.0, radius - band)))
    # ── الخيط الداخلي: إطارٌ ثانٍ رفيع بفاصلٍ داكن ──
    if inner_line:
        il = inner_r.adjusted(4.0, 4.0, -4.0, -4.0)
        p.setPen(QtGui.QPen(metal_brush(il, phase + 0.25), 1.4))
        p.drawPath(_rounded(il, max(2.0, radius - band - 4)))
    if ornaments:
        _corner_ornaments(p, r, radius, band, phase)
    p.restore()


def _diamond(p, cx, cy, s, phase):
    """ماسةٌ ذهبية بوجهين: نصفٌ مضيء ونصفٌ في الظل — فتبدو مجسّمة."""
    top = QtCore.QPointF(cx, cy - s)
    right = QtCore.QPointF(cx + s, cy)
    bottom = QtCore.QPointF(cx, cy + s)
    left = QtCore.QPointF(cx - s, cy)
    rect = QtCore.QRectF(cx - s, cy - s, 2 * s, 2 * s)
    p.setPen(QtGui.QPen(QtGui.QColor(40, 24, 4, 200), 0.9))
    p.setBrush(metal_brush(rect, phase, angle=60))
    p.drawPolygon(QtGui.QPolygonF([top, right, bottom, left]))
    # الوجه المضيء
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(255, 248, 215, 120))
    p.drawPolygon(QtGui.QPolygonF([top, QtCore.QPointF(cx, cy), left]))
    # وميض الحجر
    p.setBrush(QtGui.QColor(255, 255, 245, 230))
    p.drawEllipse(QtCore.QPointF(cx - s * 0.28, cy - s * 0.30),
                  s * 0.16, s * 0.16)


def _corner_ornaments(p, r, radius, band, phase):
    """في كل ركن: ماسةٌ على الإطار وخطّا زخرفةٍ يمتدّان على الضلعين."""
    s = max(5.5, band * 1.7)
    arm = max(26.0, radius * 2.6)
    inset = band / 2.0
    for sx, sy, x, y in ((1, 1, r.left(), r.top()),
                         (-1, 1, r.right(), r.top()),
                         (1, -1, r.left(), r.bottom()),
                         (-1, -1, r.right(), r.bottom())):
        cx = x + sx * (inset + radius * 0.30)
        cy = y + sy * (inset + radius * 0.30)
        # خطّا الزخرفة: يخرجان من الماسة على الضلعين ويتلاشيان
        for dx, dy in ((sx, 0), (0, sy)):
            ex, ey = cx + dx * arm, cy + dy * arm
            g = QtGui.QLinearGradient(cx, cy, ex, ey)
            g.setColorAt(0.0, QtGui.QColor(255, 236, 170, 230))
            g.setColorAt(1.0, QtGui.QColor(201, 162, 39, 0))
            p.setPen(QtGui.QPen(QtGui.QBrush(g), 1.6))
            p.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(ex, ey))
        _diamond(p, cx, cy, s, phase)


# ══════════════════════════════════════════════════════════════════
#  لوحة الدخول: زجاجٌ داكن في إطارٍ ذهبي
# ══════════════════════════════════════════════════════════════════

class GoldCard(QtWidgets.QWidget):
    """لوحةٌ تُرسم بيدها: ظلٌّ تحتها، وزجاجٌ داكن، وإطارٌ ذهبي حيّ.

    اللمعة تمرّ على الإطار كل بضع ثوانٍ (دفعةٌ قصيرة ثم سكون) — فلا
    تُعاد اللوحة وحقولها رسماً في كل نبضة بلا داعٍ.
    """

    PERIOD_MS = 7000          # كل كم تمرّ اللمعة
    SWEEP_MS = 1600           # مدّة مرورها
    MARGIN = 14               # مساحة الظلّ حول الإطار

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.phase = 0.0
        self._sweep = QtCore.QVariantAnimation(self)
        self._sweep.setStartValue(0.0)
        self._sweep.setEndValue(1.0)
        self._sweep.setDuration(self.SWEEP_MS)
        self._sweep.setEasingCurve(QtCore.QEasingCurve.InOutSine)
        self._sweep.valueChanged.connect(self._on_sweep)
        self._every = QtCore.QTimer(self)
        self._every.setInterval(self.PERIOD_MS)
        self._every.timeout.connect(self.shine)

    def start_shine(self):
        try:
            from ui.widgets.gold_stage import animations_on
            if not animations_on():
                return
        except Exception:
            return
        self._every.start()
        QtCore.QTimer.singleShot(600, self.shine)

    def stop_shine(self):
        self._every.stop()
        self._sweep.stop()

    def shine(self):
        if self.isVisible() and self._sweep.state() != \
                QtCore.QAbstractAnimation.Running:
            self._sweep.start()

    def _on_sweep(self, v):
        self.phase = float(v)
        m = self.MARGIN
        r = self.rect().adjusted(m, m, -m, -m)
        # الإطار وحده يُعاد رسمه — لا وسط اللوحة ولا حقولها
        band = 16
        region = QtGui.QRegion(r).subtracted(
            QtGui.QRegion(r.adjusted(band, band, -band, -band)))
        self.update(region)

    def frame_rect(self):
        m = self.MARGIN
        return QtCore.QRectF(self.rect()).adjusted(m, m, -m, -m)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = self.frame_rect()
        radius = 18.0
        # ── الظلّ: طبقاتٌ متدرّجة تحت اللوحة (ارتفاعٌ عن المسرح) ──
        # طبقاتٌ كثيرة خفيفة تتراكب — فيذوب الظلّ ولا يُرى له حدّ
        p.setPen(QtCore.Qt.NoPen)
        n = 12
        for i in range(n):
            grow = 1.0 + i * (self.MARGIN - 2) / n
            a = int(22 * (1.0 - i / n) ** 1.6) + 1
            p.setBrush(QtGui.QColor(0, 0, 0, a))
            p.drawRoundedRect(r.adjusted(-grow, -grow + 4, grow, grow + 5),
                              radius + grow, radius + grow)
        # ── الزجاج الداكن ──
        body = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
        body.setColorAt(0.0, QtGui.QColor(44, 34, 20, 238))
        body.setColorAt(0.45, QtGui.QColor(27, 21, 13, 242))
        body.setColorAt(1.0, QtGui.QColor(18, 14, 9, 246))
        p.setBrush(QtGui.QBrush(body))
        p.drawRoundedRect(r, radius, radius)
        # لمعة الزجاج العليا: ضوءٌ ينعكس على ثلث السطح الأعلى
        gloss = QtGui.QLinearGradient(r.topLeft(), QtCore.QPointF(
            r.left(), r.top() + r.height() * 0.38))
        gloss.setColorAt(0.0, QtGui.QColor(255, 236, 180, 30))
        gloss.setColorAt(1.0, QtGui.QColor(255, 236, 180, 0))
        p.setBrush(QtGui.QBrush(gloss))
        p.drawRoundedRect(r.adjusted(6, 6, -6, -6), radius - 4, radius - 4)
        # ظلّ داخلي على الحواف: الزجاج مغروسٌ في الإطار
        for i, a in enumerate((70, 40, 18)):
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, a), 1.0))
            k = 6.5 + i * 1.2
            p.drawRoundedRect(r.adjusted(k, k, -k, -k),
                              radius - k * 0.6, radius - k * 0.6)
        # ── الإطار الذهبي ──
        draw_frame(p, r, radius=radius, band=5.5, phase=self.phase)
        p.end()


# ══════════════════════════════════════════════════════════════════
#  حواف الشاشة: تعتيمٌ ناعم وإطارٌ رفيع بزخارف أركان
# ══════════════════════════════════════════════════════════════════

def screen_overlay(w, h, dpr=1.0):
    """صورةٌ شفافة بحجم الشاشة: تعتيم الحواف (vignette) + إطارٌ ذهبي.

    تُرسم **مرةً** عند تغيّر المقاس وتُلصق في كل إطار — فالتعتيم
    الشعاعي على شاشة 4K لا يُحسب ستين مرة في الثانية.
    """
    w, h = max(1, int(w)), max(1, int(h))
    # صورةٌ بقناة شفافية صريحة: `QPixmap` على بعض المنصّات يُنشأ بلا
    # قناة ألفا، فيغطّي المسرحَ كلّه بدل أن يعتّم حوافه وحدها
    pm = QtGui.QImage(int(w * dpr), int(h * dpr),
                      QtGui.QImage.Format_ARGB32_Premultiplied)
    pm.setDevicePixelRatio(dpr)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    # ── التعتيم: الضوء في الوسط والحواف تغرق في الظل ──
    rg = QtGui.QRadialGradient(w / 2.0, h * 0.46, max(w, h) * 0.72)
    rg.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
    rg.setColorAt(0.55, QtGui.QColor(0, 0, 0, 0))
    rg.setColorAt(0.85, QtGui.QColor(0, 0, 0, 95))
    rg.setColorAt(1.0, QtGui.QColor(0, 0, 0, 165))
    p.fillRect(QtCore.QRectF(0, 0, w, h), QtGui.QBrush(rg))
    # ── الإطار: رفيعٌ على بُعدٍ من الحافة، بأركانٍ مزخرفة ──
    inset = max(14.0, min(w, h) * 0.018)
    fr = QtCore.QRectF(inset, inset, w - 2 * inset, h - 2 * inset)
    draw_frame(p, fr, radius=10.0, band=3.0, phase=0.15, ornaments=True,
               inner_line=True)
    # زوايا بارزة: قوسا ركنٍ أعرض فوق الإطار الرفيع
    arm = max(46.0, min(w, h) * 0.07)
    for sx, sy, x, y in ((1, 1, fr.left(), fr.top()),
                         (-1, 1, fr.right(), fr.top()),
                         (1, -1, fr.left(), fr.bottom()),
                         (-1, -1, fr.right(), fr.bottom())):
        path = QtGui.QPainterPath()
        path.moveTo(x + sx * arm, y + sy * 0.0)
        path.lineTo(x, y)
        path.lineTo(x, y + sy * arm)
        pen = QtGui.QPen(metal_brush(QtCore.QRectF(
            min(x, x + sx * arm), min(y, y + sy * arm), arm, arm), 0.3), 4.0)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(path)
    p.end()
    return QtGui.QPixmap.fromImage(pm)
