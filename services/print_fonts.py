# -*- coding: utf-8 -*-
"""خطّ الأوراق المطبوعة — الخطّ نفسه الذي تعرض به الشاشات.

**لماذا**: كانت الشاشات بخطّ IBM Plex Sans Arabic المرفق، والورقة
المطبوعة بـ«Segoe UI» أو ما يجده المتصفح على الجهاز — فتخرج الفاتورة
بشكلٍ على جهاز المحاسب وبآخر على جهاز المدير، وأرقامها أقلّ تمايزاً
مما على الشاشة.

**كيف**: يُضمَّن الخطّ **داخل صفحة الطباعة نفسها** (`@font-face` بصيغة
data URI) لا رابطاً إلى ملفه على القرص: المتصفّحات الحديثة ترفض تحميل
خطٍّ من ملفٍّ محليّ لصفحةٍ محلية (سياسة الأصل الواحد)، فيسقط الرابط
بصمت ويعود الخطّ القديم. المضمَّن يظهر على كل جهاز وكل متصفح وفي ملف
الـPDF المحفوظ — وزنان فقط (عادي وعريض) لأنهما كل ما تستعمله القوالب،
فتبقى الصفحة خفيفة.

**المقاسات لا تتغيّر**: الخطّ يتبدّل وحده، وكل مقاسٍ في القوالب كما كان.
ومن اختار «كلاسيكي — Segoe UI» من «عرض ← الخط» تُطبع أوراقه به أيضاً.
"""
import base64
from pathlib import Path

FAMILY = "IBM Plex Sans Arabic"
_FALLBACK = "'Segoe UI', 'Cairo', Tahoma, sans-serif"
_WEIGHTS = (("IBMPlexSansArabic-Regular.ttf", 400),
            ("IBMPlexSansArabic-Bold.ttf", 700))
_css = None


def _font_dir():
    try:
        from ui import fonts
        return Path(fonts.font_dir())
    except Exception:
        return Path(__file__).resolve().parent.parent / "assets" / "fonts"


def modern():
    """هل الخطّ الحديث هو المختار؟ (الافتراضي نعم)."""
    try:
        from ui import fonts
        return fonts.current_choice() == "modern"
    except Exception:
        return True


def face_css():
    """قواعد `@font-face` المضمَّنة — تُبنى مرةً ثم من الذاكرة."""
    global _css
    if _css is None:
        parts = []
        d = _font_dir()
        for name, weight in _WEIGHTS:
            p = d / name
            try:
                data = base64.b64encode(p.read_bytes()).decode("ascii")
            except OSError:
                continue
            parts.append(
                "@font-face { font-family: '%s'; font-style: normal; "
                "font-weight: %d; font-display: block; "
                "src: local('%s'), url(data:font/ttf;base64,%s) "
                "format('truetype'); }" % (FAMILY, weight, FAMILY, data))
        _css = "\n".join(parts)
    return _css


def family_css():
    """قيمة `font-family` للورقة — الحديث أولاً إن كان مختاراً."""
    if modern() and face_css():
        return f"'{FAMILY}', {_FALLBACK}"
    return _FALLBACK


def style_block():
    """كتلة <style> بالخط المضمَّن — أو فارغة للخط الكلاسيكي."""
    if not modern():
        return ""
    css = face_css()
    return f"<style>{css}</style>" if css else ""
