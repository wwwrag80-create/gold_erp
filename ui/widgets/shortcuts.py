# -*- coding: utf-8 -*-
"""اختصاراتٌ إلى شاشاتٍ أخرى (5.3.2) — أزرارٌ صغيرة في الشريط العلوي
بجوار «إغلاق الشاشة»، لا داخل الشاشة: فلا تزاحم محتواها ولا تشوّهه.

كل اختصار: (الأيقونة والاسم، عنوان الشاشة في القائمة، ما يُفعل بعد
فتحها — اختياري). الضغط يفتح الشاشة نفسها كما لو اختيرت من القائمة،
والرجوع بزر «رجوع» المعتاد."""
from PyQt5 import QtCore, QtWidgets


def _main_window(widget):
    w = widget.window() if widget is not None else None
    if w is not None and hasattr(w, "open_by_title"):
        return w
    for top in QtWidgets.QApplication.topLevelWidgets():
        if hasattr(top, "open_by_title"):
            return top
    return None


def buttons(owner, items):
    """[(النص, عنوان الشاشة, التلميح, بعد_الفتح أو None)] ← أزرار."""
    out = []
    for text, title, tip, after in items:
        b = QtWidgets.QToolButton()
        b.setObjectName("ghost")
        b.setText(text)
        b.setToolTip(tip or f"فتح «{title}»")
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.setAutoRaise(True)
        b.setFocusPolicy(QtCore.Qt.NoFocus)

        def go(_=False, t=title, a=after):
            mw = _main_window(owner)
            if mw is not None:
                mw.open_by_title(t, a)
        b.clicked.connect(go)
        out.append(b)
    return out


def receipt_mode(screen):
    """بعد فتح «سندات قبض/صرف»: على «سند قبض»."""
    k = getattr(screen, "kind", None)
    if k is not None and hasattr(k, "findData"):
        i = k.findData("receipt")
        if i >= 0:
            k.setCurrentIndex(i)


def scrap_panel(screen):
    """بعد فتح لوحة التحكم: على لوحة «صندوق الكسر» (18 · 21 · 22 · 24)."""
    panels = getattr(screen, "panels", None) or []
    idx = next((i for i, p in enumerate(panels) if p.get("key") == "scrap"),
               None)
    if idx is None:                   # لوحةٌ أُعيدت تسميتها: بعنوانها
        idx = next((i for i, p in enumerate(panels)
                    if "كسر" in str(p.get("title") or "")), None)
    fn = getattr(screen, "_select_soon", None)
    if idx is not None and callable(fn):
        fn(idx)


SUPPLY = (("📒 القيود اليومية", "القيود اليومية", None, None),
          ("🖼 دليل الموديلات", "دليل الموديلات", None, None),
          ("📄 كشف حساب", "كشف حساب", None, None))
SALES = (("📄 كشف حساب", "كشف حساب", None, None),
         ("🧾 سند قبض", "سندات قبض/صرف", "فتح سند قبض", receipt_mode),
         ("🖼 دليل الموديلات", "دليل الموديلات", None, None))
RECEIPT = (("🖼 دليل الموديلات", "دليل الموديلات", None, None),
           ("⚖ صناديق الكسر", "لوحة التحكم",
            "لوحة صناديق الكسر — 18 · 21 · 22 · 24", scrap_panel),
           ("🛒 المبيعات", "مبيعات/مرتجعات", "فاتورة مبيعات/مرتجعات", None))
