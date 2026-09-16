# -*- coding: utf-8 -*-
"""توحيد صيغة التواريخ — ضابط سلامة أساسي.

**الخلل الذي يعالجه**: التواريخ تُحفظ نصاً (`YYYY-MM-DD`) وتُقارَن نصاً
في كل استعلام. فلو كُتب تاريخ بأرقام عربية (`٢٠٢٦-٠٩-١٦`) بدل الإنجليزية
(`2026-09-16`) اختلّت المقارنة تماماً: رمز `٠` في يونيكود (U+0660) أكبر
من رمز `9` (U+0039)، فيصير

    '٢٠٢٦-٠٩-١٦' <= '2026-12-31'   ←   خطأ

والنتيجة أن القيد **يسقط من كل فلتر تاريخ**: التقارير وكشوف الحسابات
وميزان المراجعة والإقفال السنوي وقفل الفترات. القيد موجود في القاعدة،
لكنه غير مرئي في أي شاشة — وهو أسوأ أنواع الخلل: لا رسالة خطأ، ولا
بيانات.

العلاج طبقتان: تحويل عند الكتابة (هنا)، وإصلاح ما كُتب سابقاً
(`tools/fix_dates.py`).
"""
import datetime as _dt

# الأرقام العربية-الهندية (٠-٩) والفارسية الممتدة (۰-۹)
_DIGITS = {}
for _i in range(10):
    _DIGITS[chr(0x0660 + _i)] = str(_i)     # ٠١٢٣٤٥٦٧٨٩
    _DIGITS[chr(0x06F0 + _i)] = str(_i)     # ۰۱۲۳۴۵۶۷۸۹
# فواصل قد تُكتب بدل الشرطة
_SEPS = {"/": "-", ".": "-", "‐": "-", "‑": "-",
         "‒": "-", "–": "-", "—": "-"}


def normalize_digits(text):
    """يحوّل الأرقام العربية والفارسية إلى إنجليزية، ويوحّد الفواصل."""
    if not text:
        return text
    return "".join(_DIGITS.get(ch, _SEPS.get(ch, ch)) for ch in str(text))


def has_non_ascii_digits(text):
    """هل في النص أرقام غير إنجليزية؟"""
    return any(ch in _DIGITS for ch in str(text or ""))


def normalize_date(value, field="التاريخ"):
    """يعيد تاريخاً بصيغة YYYY-MM-DD بأرقام إنجليزية، أو يرفع ValueError.

    يقبل ما يكتبه المستخدم بأي أرقام، ويرفض ما ليس تاريخاً أصلاً —
    فلا يُحفظ في عمود التاريخ نصٌّ لا يُقارَن.
    """
    if value is None:
        raise ValueError(f"{field} مفقود")
    s = normalize_digits(str(value).strip())
    # نقبل الطابع الزمني الكامل ونأخذ يومه
    core = s[:10]
    try:
        _dt.date.fromisoformat(core)
    except Exception:
        raise ValueError(
            f"{field} غير صالح: «{value}» — الصيغة المطلوبة YYYY-MM-DD")
    return core


def safe_date(value, default=None):
    """كسابقتها لكنها تعيد `default` بدل رفع الخطأ — للعرض والتقارير."""
    try:
        return normalize_date(value)
    except Exception:
        return default


def today():
    return _dt.date.today().isoformat()
