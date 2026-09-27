# -*- coding: utf-8 -*-
"""خط النظام — IBM Plex Sans Arabic مرفقاً مع البرنامج.

**لماذا خطٌّ مرفق**: «Segoe UI» خطُّ ويندوز العام، عربيّته مقبولة لا
أكثر، ويختلف شكله من جهازٍ لجهاز بحسب إصدار النظام. وخطٌّ يُرفق مع
البرنامج يظهر واحداً على كل جهاز، ويُصمَّم للشاشات لا للطباعة.

**لماذا IBM Plex Sans Arabic**:
  · صُمّم للواجهات والبيانات: فتحاتٌ واسعة وارتفاعُ سطرٍ مريح، فيُقرأ
    الجدول الطويل بلا إجهاد.
  · أرقامه اللاتينية (التي يعرض بها النظام كل رقم) واضحةٌ متمايزة:
    لا يلتبس 1 بـ7 ولا 3 بـ8 ولا 0 بـO — وهو ما يهمّ في دفترٍ بالجرام.
  · أربعة أوزان (عادي · متوسط · شبه عريض · عريض) فتتدرّج العناوين
    والأرقام بلا تقليد الوزن بالرسم.
  · رخصة SIL المفتوحة (assets/fonts/OFL.txt): يُرفق ويُوزَّع بلا قيد.

والمستخدم يعود إلى «Segoe UI» من قائمة «عرض ← الخط» إن شاء؛ والمقاس
لا يتغيّر بتغيّر الخط — فمعامل «مقاس الخط» هو نفسه في الاثنين.
"""
from pathlib import Path

PREF_FAMILY = "ui_font_family"
MODERN = "IBM Plex Sans Arabic"
CLASSIC = "Segoe UI"
CHOICES = (("modern", "✨ حديث — IBM Plex عربي"),
           ("classic", "كلاسيكي — Segoe UI"))

_FILES = ("IBMPlexSansArabic-Regular.ttf", "IBMPlexSansArabic-Medium.ttf",
          "IBMPlexSansArabic-SemiBold.ttf", "IBMPlexSansArabic-Bold.ttf")
_loaded = None


def font_dir():
    try:
        import config
        base = Path(getattr(config, "BUNDLE_DIR", "") or "")
        d = base / "assets" / "fonts"
        if d.exists():
            return d
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent / "assets" / "fonts"


def load_bundled():
    """يسجّل الخطوط المرفقة مرةً واحدة — ويعيد اسم العائلة أو None.

    فشل التسجيل (ملفٌ ناقص، نظامٌ لا يقبل الخط) لا يوقف شيئاً: يعود
    النظام إلى الخط الكلاسيكي بصمت.
    """
    global _loaded
    if _loaded is not None:
        return _loaded or None
    fams = set()
    try:
        from PyQt5 import QtGui
        for name in _FILES:
            p = font_dir() / name
            if not p.exists():
                continue
            fid = QtGui.QFontDatabase.addApplicationFont(str(p))
            if fid >= 0:
                fams.update(QtGui.QFontDatabase.applicationFontFamilies(fid))
    except Exception:
        fams = set()
    _loaded = MODERN if MODERN in fams else (sorted(fams)[0] if fams else "")
    return _loaded or None


def current_choice():
    try:
        from ui.widgets.common import load_pref
        v = str(load_pref(PREF_FAMILY, "modern")).strip().lower()
        return v if v in {k for k, _l in CHOICES} else "modern"
    except Exception:
        return "modern"


def set_choice(key, username=None):
    from ui.widgets.common import save_pref
    save_pref(PREF_FAMILY, str(key), username)


def family(choice=None):
    """عائلة الخط الفعّالة: الحديث إن اختير وأمكن تحميله، وإلا الكلاسيكي."""
    if (choice or current_choice()) == "modern":
        fam = load_bundled()
        if fam:
            return fam
    return CLASSIC
