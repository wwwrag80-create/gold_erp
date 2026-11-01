# -*- coding: utf-8 -*-
"""أيقونةٌ لكل شاشة (5.1) — مجموعةٌ واحدة أحادية اللون بلون الهوية.

**لماذا أيقونات Fluent لا الرموز التعبيرية**: الرموز (🧾 💎 📊) تُرسم
ملوّنةً بخط ويندوز، فتُدخل على الواجهة ألواناً ليست من هويتها وتختلف من
جهازٍ لجهاز. أيقونات Fluent خطٌّ واحد بسماكةٍ واحدة، وتُلوَّن هنا بالذهب
الداكن (`goldDim`) من لوحة النظام نفسها — فلا لون جديد.

المفتاح **الاسم الافتراضي** للشاشة (`NAV_KEY_ROLE`) لا اسمها الظاهر:
المستخدم يعيد تسمية بنود القائمة، والأيقونة تتبع الشاشة لا النصّ.
"""
from PyQt5 import QtGui

ICONS = {
    # ── العمل اليومي ──
    "لوحة التحكم": "TILES",
    "دليل الموديلات": "PHOTO",
    "حركة الطقم": "HISTORY",
    "كشف حساب": "DOCUMENT",
    "الوارد من التصنيع": "DOWNLOAD",
    "مبيعات/مرتجعات": "SHOPPING_CART",
    "المبيعات والمرتجعات": "SHOPPING_CART",
    "المبيعات الضريبية": "QRCODE",
    "سندات قبض/صرف": "SYNC",
    "العملاء — المبيعات والسداد": "PEOPLE",
    "مجموعات العملاء": "FOLDER",
    "التسكيرات": "PIN",
    "المشتريات": "MARKET",
    "القيود اليومية": "EDIT",
    "تقارير مبيعات وإنتاج المصنع": "LAYOUT",
    "التحليل والدراسات": "VIEW",
    # ── الإدارة والتقارير ──
    "الإدارة والتقارير": "SETTING",
    "الإغلاق اليومي": "CALENDAR",
    "دليل الحسابات (شجرة الحسابات)": "DICTIONARY",
    "التكويد الموحّد لجهات التعامل": "TAG",
    "أرصدة الأستاذ المساعد": "BOOK_SHELF",
    "الأرصدة الافتتاحية المخزنية": "FOLDER_ADD",
    "تسوية فواقد الورشة": "BROOM",
    "حسابات الورشة": "DEVELOPER_TOOLS",
    "الجرد الفعلي": "CHECKBOX",
    "إدارة وتحويل العمليات": "MOVE",
    "سجل العمليات": "SCROLL",
    "سلامة السجل (بصمة القيود)": "FINGERPRINT",
    "صحة النظام": "HEART",
    "مطابقة كشف البنك": "CONNECT",
    "أرشيف المستندات والطباعة": "PRINT",
    "من عدّل ماذا بعد الترحيل": "PENCIL_INK",
    "رواتب العمال والإدارة": "DATE_TIME",
    "الإقرار الضريبي (VAT)": "CERTIFICATE",
    "القوائم المالية": "LIBRARY",
    "تحليل مبيعات العملاء": "PIE_SINGLE",
    "إنتاج خزينة التصنيع (مطابقة)": "ALIGNMENT",
    "تهيئة أرصدة أول المدة (تاريخ القطع)": "FLAG",
    "الإقفال السنوي": "SAVE",
    # ── الإدارة العليا ──
    "الإدارة العليا": "GLOBE",
    "الحسابات وإيقاف المصانع": "POWER_BUTTON",
}
GROUP_PREFIX = "::group::"
_CACHE = {}


def _color():
    try:
        from ui import theme
        return theme.palette(theme.current_theme()).get("goldDim", "#5E4A0C")
    except Exception:
        return "#5E4A0C"


def icon_for(key):
    """أيقونة الشاشة باسمها الافتراضي — أو أيقونة فارغة إن لم تُعرف."""
    key = str(key or "")
    if key.startswith(GROUP_PREFIX):
        key = key[len(GROUP_PREFIX):]
    name = ICONS.get(key)
    if not name:
        return QtGui.QIcon()
    color = _color()
    ck = (name, color)
    ic = _CACHE.get(ck)
    if ic is not None:
        return ic
    try:
        from ui import kit
        if not kit.ACTIVE:
            return QtGui.QIcon()
        fi = getattr(kit.qf.FluentIcon, name)
        ic = fi.icon(color=QtGui.QColor(color))
    except Exception:
        ic = QtGui.QIcon()
    _CACHE[ck] = ic
    return ic


def clear():
    """بعد تبديل المظهر: الأيقونات تُرسم بلون الوضع الجديد."""
    _CACHE.clear()
