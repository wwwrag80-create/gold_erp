# -*- coding: utf-8 -*-
"""عرض الأرقام بمنزلتين عشريتين — تقريباً «نصفياً للأعلى» (4.99).

طلب صاحب النظام: كل رقمٍ يُعرض — في الحسابات وكشوف الحساب والعمليات
والخانات والطباعة ورابط المدير — بمنزلتين بعد الفاصلة لا ثلاث،
والمنزلة الثالثة إن بلغت ٥ رفعت الثانية: 0.005 ← 0.01، و0.004 ← 0.00.
فلا يظهر رصيدٌ «0.001» بعد اليوم.

**لماذا لا يكفي `f"{v:.2f}"`**: بايثون يقرّب القيمة الثنائية لا العشرية
وبقاعدة «الأقرب زوجيّاً» عند التعادل: ‎10.125 ← 10.12، و2.675 ← 2.67
(لأن 2.675 مخزَّنة 2.67499…). والأوزان تُحفظ بثلاث منازل فالتعادل
عندها كثير — فكان الرقم نفسه يُقرَّب مرةً للأعلى ومرةً للأسفل.
هنا يُقرأ الرقم بصورته العشرية القصيرة ثم يُقرَّب نصفياً للأعلى.

**العرض وحده**: القيود تبقى بدقّتها المخزَّنة. تقريب كل سطرٍ عند
الحفظ يُخرج القيد عن توازنه (سطرٌ 10.005 مقابل سطرين 5.0025)، أما
تقريب الناتج عند العرض فلا يمسّ حساباً.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_Q2 = Decimal("0.01")


def _dec(v):
    """الرقم بصورته العشرية — بعد إزالة غبار الفاصلة العائمة.

    ‎10.124999999999998 ناتجُ جمعٍ لا قيمةٌ مقصودة: تقريبه إلى تسع
    منازل أولاً يعيده 10.125 فيُرفع إلى 10.13 كما يتوقّع القارئ."""
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v if v.is_finite() else None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    try:
        return Decimal(repr(round(f, 9)))
    except InvalidOperation:
        return None


def q2(v):
    """`Decimal` بمنزلتين نصفياً للأعلى — بلا «‎-0.00»."""
    d = _dec(v)
    if d is None:
        return None
    q = d.quantize(_Q2, rounding=ROUND_HALF_UP)
    return q.copy_abs() if q == 0 else q


def r2(v):
    """الرقم مقرَّباً إلى منزلتين نصفياً للأعلى — `float`."""
    q = q2(v)
    return 0.0 if q is None else float(q)


def f2(v, sep=True, sign=False):
    """نصّ العرض: ‎1,234.57 — بفواصل الآلاف (`sep`) وبإشارة + (`sign`).

    ما ليس رقماً يُعاد نصّه كما هو، فلا ينكسر جدولٌ بخليةٍ شاذّة."""
    q = q2(v)
    if q is None:
        return "" if v is None else str(v)
    spec = ("+" if sign else "") + ("," if sep else "") + ".2f"
    return format(q, spec)


def txt(v):
    """نصّ خلية جدول: الكسريّ بمنزلتين، وغيره كما هو (`str`)."""
    return f2(v) if isinstance(v, float) else str(v)
