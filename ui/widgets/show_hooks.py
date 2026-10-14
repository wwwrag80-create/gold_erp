# -*- coding: utf-8 -*-
"""مرشّحٌ واحد للتطبيق كلّه لأحداث «الظهور» (4.71).

طيّ فقرات الشرح (`declutter`) وظلال البطاقات (`effects`) يعملان عند ظهور
الملصق أو الإطار — وكان لكلٍّ منهما مرشّحٌ على التطبيق كلّه. والمرشّح
على التطبيق يُستدعى في بايثون مع **كل حدث** في البرنامج (رسمٌ وتحريكٌ
وتغيّر حجمٍ وتهيئة…) — آلاف الأحداث عند بناء كل شاشة. فصار مرشّحاً
واحداً يمرّر أحداث الظهور وحدها لمن سجّل لها، فيُستدعى بايثون مرةً
لكل حدثٍ بدل مرّتين.
"""
from PyQt5 import QtCore

_HANDLERS = []                  # (أصناف، دالّة)
_installed = None


class _ShowHooks(QtCore.QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Show:
            for types, fn in _HANDLERS:
                if isinstance(obj, types):
                    try:
                        fn(obj)
                    except Exception:
                        pass
        return False


def register(app, types, fn):
    """يسجّل `fn(widget)` لظهور كل مكوّنٍ من `types` — مرةً لكل دالّة."""
    global _installed
    if not any(f is fn for _t, f in _HANDLERS):
        _HANDLERS.append((types, fn))
    if _installed is None:
        _installed = _ShowHooks(app)
        app.installEventFilter(_installed)
    return _installed
