# -*- coding: utf-8 -*-
"""عمقٌ هادئ — ظلٌّ ناعم تحت البطاقات واللوحات.

البطاقات (أرقام الشاشة الكبرى، لوحات الرئيسية، مربعات التحليل) كانت
أسطحاً مسطّحة بحدٍّ رفيع، تذوب في الخلفية على الشاشات الساطعة. ظلٌّ
خفيفٌ تحتها يرفعها عن الصفحة فتُلتقط أولاً — كما في الواجهات الحديثة —
بلا لونٍ جديد ولا حدٍّ أثقل.

يُركَّب **تلقائياً** على كل إطارٍ من الأنواع أدناه لحظة ظهوره الأول
(مرشّح أحداثٍ واحد على التطبيق)، فلا تحتاج أي شاشة سطراً لأجله.
ويُطفأ من «عرض ← التأثيرات الحديثة» للأجهزة القديمة البطيئة.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

PREF = "ui_effects"
# إطاراتٌ محتواها ملصقاتٌ وحدها — فالظلّ يُرسم رخيصاً ولا يمسّ جدولاً
ELEVATED = {"card", "cardSum", "kpi", "kpiAlert", "kpiGood", "tile",
            "statPanel", "goldBar"}
_FLAG = "_elevated"


_on = None          # يُقرأ من التفضيلات مرةً ثم من الذاكرة


def enabled():
    global _on
    if _on is None:
        try:
            from ui.widgets.common import load_pref
            _on = str(load_pref(PREF, "1")).strip() != "0"
        except Exception:
            _on = True
    return _on


def set_enabled(on, username=None):
    global _on
    from ui.widgets.common import save_pref
    save_pref(PREF, "1" if on else "0", username)
    _on = bool(on)


_color = None       # لون الظلّ بحسب المظهر — يُحسب عند كل تطبيقٍ للمظهر


def _shadow_color():
    global _color
    if _color is None:
        try:
            from ui import theme
            dark = theme.is_dark()
        except Exception:
            dark = False
        _color = QtGui.QColor(0, 0, 0, 120 if dark else 34)
    return _color


def elevate(w):
    """يضع الظلّ على إطارٍ واحد — مرةً واحدة."""
    if w.property(_FLAG) or w.graphicsEffect() is not None:
        return
    eff = QtWidgets.QGraphicsDropShadowEffect(w)
    eff.setBlurRadius(18)
    eff.setOffset(0, 2)
    eff.setColor(_shadow_color())
    w.setGraphicsEffect(eff)
    w.setProperty(_FLAG, True)


def flatten_all():
    """يرفع الظلال عن كل ما رُكّبت عليه — حين يطفئها المستخدم."""
    for w in QtWidgets.QApplication.allWidgets():
        if w.property(_FLAG):
            w.setGraphicsEffect(None)
            w.setProperty(_FLAG, False)


def refresh_all():
    """يعيد تلوين الظلال (بعد تبديل الفاتح/الليلي) أو يركّبها إن فُعّلت."""
    global _color
    _color = None
    if not enabled():
        flatten_all()
        return
    c = _shadow_color()
    for w in QtWidgets.QApplication.allWidgets():
        if isinstance(w, QtWidgets.QFrame) and w.objectName() in ELEVATED:
            eff = w.graphicsEffect()
            if isinstance(eff, QtWidgets.QGraphicsDropShadowEffect):
                eff.setColor(c)
            elif w.isVisible():
                elevate(w)


class _Elevator(QtCore.QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Show and isinstance(obj,
                                                          QtWidgets.QFrame):
            try:
                if obj.objectName() in ELEVATED and not obj.property(_FLAG) \
                        and enabled():
                    elevate(obj)
            except Exception:
                pass
        return False


_installed = None


def install(app):
    """يركّب المرشّح على التطبيق — مرةً واحدة."""
    global _installed
    if _installed is None:
        _installed = _Elevator(app)
        app.installEventFilter(_installed)
    return _installed
