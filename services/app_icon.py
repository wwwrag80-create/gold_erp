# -*- coding: utf-8 -*-
"""أيقونة التطبيق — بمسار موثوق وهوية ويندوز صحيحة.

**لماذا لم تظهر الأيقونة**: سببان مستقلان:

1. **مسار الأصول داخل الـexe**: PyInstaller بوضع `--onefile` يفكّ
   الملفات في مجلد مؤقّت، ومساره في `sys._MEIPASS` لا في مجلد
   التطبيق. البحث في `BASE_DIR` وحده يفشل داخل الـexe.

2. **هوية شريط المهام**: ويندوز يجمع النوافذ في شريط المهام بحسب
   `AppUserModelID`. بلا ضبطه يرث التطبيق هوية مُفسّر بايثون، فيعرض
   شريط المهام أيقونة بايثون مهما ضبطنا أيقونة النافذة.
"""
import os
import sys
from pathlib import Path

APP_ID = "TreeSoft.Jadeite.GoldERP.1"
ICON_NAMES = ("logo.ico", "logo.png", "logo.jpg")


def _roots():
    """كل الأماكن المحتملة للأصول — بترتيب الأولوية."""
    out = []
    # 1) مجلد فكّ الـexe (onefile)
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        out.append(Path(mei))
    # 2) مجلد الملف التنفيذي (onedir أو بجواره)
    try:
        out.append(Path(sys.executable).parent)
    except Exception:
        pass
    # 3) مجلد المشروع
    try:
        import config
        out.append(Path(config.BASE_DIR))
    except Exception:
        pass
    # 4) مجلد هذا الملف
    out.append(Path(__file__).resolve().parent.parent)
    return out


def icon_path():
    """أول أيقونة موجودة فعلاً — أو None."""
    for root in _roots():
        for sub in ("assets", ""):
            for name in ICON_NAMES:
                p = root / sub / name if sub else root / name
                try:
                    if p.exists():
                        return p
                except Exception:
                    continue
    return None


def set_windows_app_id(app_id=APP_ID):
    """يضبط هوية التطبيق في ويندوز — بدونها يعرض شريط المهام أيقونة
    بايثون بدل أيقونتنا."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            app_id)
        return True
    except Exception:
        return False


def apply(app=None, window=None):
    """يضبط الأيقونة على التطبيق والنافذة معاً.

    ضبطها على التطبيق وحده لا يكفي: بعض النوافذ (الحوارات ونافذة
    الدخول) تُنشأ قبل ذلك أو تتجاهله، فنضبطها على النافذة أيضاً.
    """
    set_windows_app_id()
    p = icon_path()
    if p is None:
        return None
    try:
        from PyQt5 import QtGui
        ico = QtGui.QIcon(str(p))
        if ico.isNull():
            return None
        if app is not None:
            app.setWindowIcon(ico)
        if window is not None:
            window.setWindowIcon(ico)
        return str(p)
    except Exception:
        return None
