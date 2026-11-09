# -*- coding: utf-8 -*-
"""لون العملية (5.2.2): أخضر لما يدخل وأحمر لما يخرج — فيُعرف من أول نظرة.

* **المبيعات والقبض** ← أخضر: فاتورة بيع · سند قبض (نستلم).
* **المرتجع والصرف** ← أحمر: مرتجع بيع · سند صرف (ندفع).

يُلوَّن به أمران: خانة «نوع العملية» نفسها، وشريط عنوان الشاشة في الأعلى
(`MainWindow.set_page_tone`) — فلا يُكتب مرتجعٌ والمستخدم يظنه بيعاً.
والألوان من لوحة المظهر الحالية (فاتح أو ليلي) فتُقرأ في الحالين.
"""
from ui import theme

IN, OUT = "in", "out"


def colors(tone):
    """(لون النص، الخلفية الخفيفة، الحدّ القوي) للعملية — بحسب المظهر."""
    dark = False
    try:
        dark = theme.is_dark()
    except Exception:
        pass
    if tone == IN:
        return ("#8FE6A8", "#173322", "#2EA05A") if dark else \
               ("#0F5A24", "#E4F4E9", "#1F8A4C")
    if tone == OUT:
        return ("#FFB3B3", "#3A1E1E", "#CC5C5C") if dark else \
               ("#9A1414", "#FBE7E7", "#C0392B")
    return None


def style_combo(combo, tone):
    """خانة نوع العملية بلونها: خلفيةٌ خفيفة وحدٌّ قوي ونصٌّ عريض."""
    c = colors(tone)
    if combo is None:
        return
    if c is None:
        combo.setStyleSheet("")
        return
    fg, bg, edge = c
    combo.setStyleSheet(
        f"QComboBox {{ background: {bg}; color: {fg}; font-weight: bold;"
        f" border: 2px solid {edge}; border-radius: 6px; padding: 2px 8px; }}"
        f" QComboBox:focus {{ border: 2px solid {edge}; }}")


def notify_window(widget):
    """يُخبر النافذة الرئيسية أن لون عملية هذه الشاشة تغيّر."""
    try:
        w = widget.window()
        fn = getattr(w, "refresh_page_tone", None)
        if callable(fn):
            fn(widget)
    except RuntimeError:
        pass
