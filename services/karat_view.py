# -*- coding: utf-8 -*-
"""عيار المصنع — وحدة العرض في النظام كله.

**القاعدة التي لا تُكسر**: القيد يُخزَّن بمكافئ عيار 18 دائماً. لا
يغيّر هذا الملف رقماً واحداً في قاعدة البيانات، ولا يمسّ قيداً ولا
رصيداً ولا فاتورة. الميزان لا يتزن إلا بوحدة واحدة، فلو خُزّن كل وزن
بعياره لاستحال جمع الأرصدة أو مقارنتها أو ترحيلها.

**ما يفعله**: يبدّل *وحدة القراءة والكتابة* في الواجهة. المصنع الذي
يتعامل بعيار 21 يقرأ كل أوزانه بـ21 ويُدخلها بـ21، والنظام يحوّلها
عند الحفظ ويعيد تحويلها عند العرض. النتيجة: نفس البيانات، بلغة
المصنع.

    الوزن المعروض  =  الوزن18 × 18 ÷ العيار
    الوزن المخزَّن =  المعروض × العيار ÷ 18

والاثنتان عكس بعضهما تماماً، فلا يُفقد شيء في الذهاب والإياب.

**الأجر للجرام يتحرك عكسياً**: إجمالي الأجور مبلغ نقدي لا يجوز أن
يتغيّر بتغيّر وحدة الوزن. وبما أن  الإجمالي = الأجر × الوزن، فإن
نقصان الوزن بنسبة 18÷العيار يوجب زيادة الأجر بنسبة العيار÷18 ليبقى
الحاصل كما هو. لذلك `rate()` تعكس `g()`.

**ما لا يُحوَّل**: الأوزان الفيزيائية المقيدة بعيارها الخاص — وزن
الكسر في الصب (له عمود `karat`)، وسطر الذهب في السند (له
`gold_karat`)، والوزن المجرود فعلياً. هذه أوزان حقيقية بعيارها لا
مكافئات، وضربها في نسبة تعطي رقماً بلا معنى. المكافئ المشتق منها
(`gold_equiv18`) يُحوَّل لأنه مكافئ.
"""
import threading

from services import gold_math

BASE = gold_math.BASE_KARAT              # 18
KARATS = gold_math.KARATS                # (18, 21, 22, 24)
SETTING_KEY = "factory_karat"

_lock = threading.Lock()
_cache = {"k": None}


# ══════════════════════════════════════════════════════════════════
#  العيار الفعّال
# ══════════════════════════════════════════════════════════════════

def _read_setting():
    """يقرأ العيار من قاعدة بيانات المصنع. الفشل يعني 18."""
    try:
        from database.database import db
        from models import fiscal
        with db(readonly=True) as conn:
            raw = fiscal.get_setting(conn, SETTING_KEY, "")
        k = int(str(raw).strip() or BASE)
        return k if k in KARATS else BASE
    except Exception:
        return BASE


def active():
    """العيار الفعّال للمصنع (18 افتراضاً).

    يُقرأ مرة واحدة ويُحفظ في الذاكرة: العيار يُقرأ في كل خلية من كل
    جدول، فاستعلام لكل خلية يعني آلاف الاستعلامات في الشاشة الواحدة.
    """
    with _lock:
        k = _cache["k"]
    if k is None:
        k = _read_setting()
        with _lock:
            _cache["k"] = k
    return k


def set_active(karat, username=None):
    """يبدّل عيار المصنع ويحفظه. يعيد العيار الجديد."""
    k = int(karat or BASE)
    if k not in KARATS:
        raise ValueError(f"عيار غير مدعوم: {karat} — المتاح {KARATS}")
    from database.database import db
    from models import fiscal
    with db() as conn:
        fiscal.set_setting(conn, SETTING_KEY, k, username)
    with _lock:
        _cache["k"] = k
    return k


def reset_cache():
    """ينسى العيار المحفوظ في الذاكرة — عند تبديل المصنع أو القاعدة."""
    with _lock:
        _cache["k"] = None


def is_base():
    """هل المصنع على عيار 18 (فلا حاجة لأي تحويل)؟"""
    return active() == BASE


# ══════════════════════════════════════════════════════════════════
#  التحويل
# ══════════════════════════════════════════════════════════════════

def g(weight18, karat=None):
    """مكافئ 18 ← وزن العرض بعيار المصنع."""
    return gold_math.from_base_karat(weight18, karat or active())


def store(weight_view, karat=None):
    """وزن أدخله المستخدم بعيار المصنع ← مكافئ 18 للتخزين."""
    k = int(karat or active())
    if k == BASE:
        return round(float(weight_view or 0), gold_math.WEIGHT_DECIMALS)
    return gold_math.to_base_karat(float(weight_view or 0), k)


def rate(rate18, karat=None):
    """أجر الجرام: مكافئ 18 ← عيار العرض (عكس الوزن تماماً).

    الحاصل (الأجر × الوزن) لا يتغيّر — وهو مبلغ نقدي يجب ألا يتأثر
    بوحدة الوزن إطلاقاً.
    """
    k = int(karat or active())
    if k == BASE:
        return round(float(rate18 or 0), 2)
    return round(float(rate18 or 0) * k / BASE, 2)


def rate_store(rate_view, karat=None):
    """أجر الجرام: عيار العرض ← مكافئ 18 للتخزين.

    **ستّ منازل لا منزلتان**: الأجر المخزَّن يُضرب في الوزن فيعطي
    مبلغاً نقدياً. تقريبه إلى منزلتين يضيّع هللات في كل جرام فتتراكم:
    أجر 23 لكل جرام 21 يصير 19.71 بدل 19.714286، فتخرج فاتورة المئة
    جرام 2,299.51 بدل 2,300.00 — نصف ريال من لا شيء.
    """
    k = int(karat or active())
    if k == BASE:
        return round(float(rate_view or 0), 2)
    return round(float(rate_view or 0) * BASE / k, 6)


def fmt(weight18, decimals=3, karat=None):
    """وزن جاهز للعرض بعيار المصنع، بفواصل الآلاف."""
    return f"{g(weight18, karat):,.{decimals}f}"


# ══════════════════════════════════════════════════════════════════
#  المسمّيات
# ══════════════════════════════════════════════════════════════════

def label(karat=None):
    """«عيار 21» — لعناوين الأعمدة والبطاقات."""
    return f"عيار {int(karat or active())}"


def unit(karat=None):
    """«جم 21» — وحدة مختصرة."""
    return f"جم {int(karat or active())}"


# النصوص الجامدة المكتوبة في الشاشات والقوالب: تُعاد كتابتها بالعيار
# الفعّال. القائمة صريحة لا نمطية — الاستبدال الأعمى لكل «18» كان
# ليغيّر تواريخ وأرقام حسابات وأوزاناً حقيقية.
_PATTERNS = ("عيار 18", "عيار ١٨", "جم 18", "جم عيار 18", "(جم 18)",
             "وزن 18", "الوزن 18", "ذهب 18", "بعيار 18", "مكافئ 18",
             "مكافئ عيار 18", "18 قيراط")


def rename(text, karat=None):
    """يعيد كتابة أي نص فيه «عيار 18» بالعيار الفعّال.

    على 18 يُعاد النص كما هو حرفياً — فلا تتبدّل شاشة واحدة عند
    المصانع التي تتعامل بـ18، وهي الحالة الافتراضية.
    """
    k = int(karat or active())
    if k == BASE or not text:
        return text
    out = str(text)
    for pat in _PATTERNS:
        if pat in out:
            out = out.replace(pat, pat.replace("18", str(k))
                              .replace("١٨", str(k)))
    return out
