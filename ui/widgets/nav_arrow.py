# -*- coding: utf-8 -*-
"""سهمٌ ذهبيٌّ بارز بجانب كل مجموعةٍ في القائمة الجانبية تحتها شاشات.

السهم الافتراضي للشجرة صغيرٌ باهت ويضيع بين الأيقونات، فلا يُعرف أن
«الإدارة والتقارير» مثلاً تفتح على شاشاتٍ تحتها. هنا يُرسم بدلاً منه
سهمٌ داخل دائرةٍ بلون الهوية في طرف البند:
  ◂ المجموعة مطويّة (اضغط لتفتح)   ▾ مفتوحة (اضغط لتطوي)
يُرسم لأي بندٍ له أبناء — مجموعةً، أو شاشةً في داخلها شاشات (5.2.4)،
ولو صنعه المستخدم بالسحب والإفلات — والنقر على السهم نفسه يفتح ما تحته
أو يطويه، والنقر على اسم الشاشة يفتحها كالعادة. ولا
يُكتب في نص البند، فلا يدخل اسمَه ولا ملفَّ ترتيب القائمة المحفوظ.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import theme

BADGE = 24        # قطر الدائرة
GAP = 10          # بُعدها عن حافة البند
RESERVE = BADGE + GAP + 6


def _has_children(index):
    try:
        return bool(index.model().hasChildren(index))
    except Exception:
        return False


class NavArrowDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self._view = view

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if not _has_children(index) or not option.text:
            return
        # مكانٌ محجوز للسهم: يُختصر الاسم الطويل قبل أن يبلغه
        icon_w = option.decorationSize.width() + 8 if not option.icon.isNull() else 0
        avail = option.rect.width() - 24 - 16 - icon_w - RESERVE
        if avail > 20:
            option.text = option.fontMetrics.elidedText(
                option.text, QtCore.Qt.ElideRight, avail)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not _has_children(index):
            return
        try:
            expanded = self._view.isExpanded(index)
        except Exception:
            expanded = False
        tk = theme.palette(theme.current_theme())
        gold = QtGui.QColor(tk.get("gold", "#9A7B22"))
        rtl = option.direction == QtCore.Qt.RightToLeft
        r = option.rect
        # طرف نهاية القراءة: اليسار في العربية
        cx = (r.left() + 8 + GAP + BADGE / 2) if rtl else (r.right() - 8 - GAP - BADGE / 2)
        cy = r.center().y() + 0.5
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        # الدائرة: ممتلئةٌ بالذهب حين تُفتح، وإطارٌ ذهبي حين تُطوى
        fill = QtGui.QColor(gold)
        fill.setAlpha(255 if expanded else 38)
        painter.setPen(QtGui.QPen(gold, 1.6))
        painter.setBrush(fill)
        painter.drawEllipse(QtCore.QPointF(cx, cy), BADGE / 2, BADGE / 2)
        # السهم
        ink = QtGui.QColor("#FFFFFF") if expanded else gold
        if expanded and theme.is_dark():
            ink = QtGui.QColor("#1B1609")
        pen = QtGui.QPen(ink, 2.6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap,
                         QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        s = 4.6
        path = QtGui.QPainterPath()
        if expanded:                          # ▾
            path.moveTo(cx - s, cy - s / 2)
            path.lineTo(cx, cy + s / 2 + 0.5)
            path.lineTo(cx + s, cy - s / 2)
        else:
            d = -1 if rtl else 1              # ◂ بالعربية · ▸ بالإنجليزية
            path.moveTo(cx - d * s / 2, cy - s)
            path.lineTo(cx + d * (s / 2 + 0.5), cy)
            path.lineTo(cx - d * s / 2, cy + s)
        painter.drawPath(path)
        painter.restore()

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        if _has_children(index):
            sz.setHeight(max(sz.height(), BADGE + 14))
        return sz


def arrow_rect(view, index):
    """مكان السهم في البند (للنقر) — أوسع قليلاً من الدائرة نفسها."""
    r = view.visualRect(index)
    rtl = view.layoutDirection() == QtCore.Qt.RightToLeft
    pad = 6
    left = (r.left() + 8 + GAP - pad) if rtl \
        else (r.right() - 8 - GAP - BADGE - pad)
    return QtCore.QRect(int(left), r.top(), BADGE + 2 * pad, r.height())


class _ArrowClicks(QtCore.QObject):
    """النقر على السهم يفتح ما تحته أو يطويه — ولا يفتح الشاشة نفسها.
    (النقر على اسم الشاشة يفتحها كالعادة، وعلى اسم المجموعة يفتحها.)"""

    def __init__(self, view):
        super().__init__(view)
        self._view = view

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QtCore.QEvent.MouseButtonPress,
                     QtCore.QEvent.MouseButtonRelease,
                     QtCore.QEvent.MouseButtonDblClick):
            return False
        try:
            if ev.button() != QtCore.Qt.LeftButton:
                return False
            v = self._view
            idx = v.indexAt(ev.pos())
            if not idx.isValid() or not _has_children(idx):
                return False
            if not arrow_rect(v, idx).contains(ev.pos()):
                return False
            if t == QtCore.QEvent.MouseButtonPress:
                v.setExpanded(idx, not v.isExpanded(idx))
            return True
        except Exception:
            return False


def install(tree):
    """يركّب السهم على الشجرة ويُخفي سهمها الافتراضي الصغير، ويعيد
    الرسم فور الفتح أو الطيّ، ويجعل السهم نفسه زرّاً."""
    tree.setItemDelegate(NavArrowDelegate(tree))
    tree.setRootIsDecorated(False)
    upd = lambda *_: tree.viewport().update()
    tree.itemExpanded.connect(upd)
    tree.itemCollapsed.connect(upd)
    f = _ArrowClicks(tree)
    tree.viewport().installEventFilter(f)
    tree._nav_arrow_clicks = f
    return tree
