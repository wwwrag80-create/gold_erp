# -*- coding: utf-8 -*-
"""خطة الحساب (3.1.0): نوع النظام · الشاشات · مدة الاشتراك · الأجهزة.

يحددها المدير العام لكل حساب من «الحسابات وإيقاف المصانع»، وتُحفظ على
الخادم مع المصنع (`cloud/admin_rpc.sql` ← `auth_plan`). وعند الدخول:

* **انتهى الاشتراك** ← لا دخول حتى يُمدَّد.
* **جهازٌ زائد عن العدد المسموح** ← لا دخول من هذا الجهاز.
* **الشاشات**: لا يظهر في القائمة ولا يُفتح إلا ما حدده المدير.
* **نوع «عميل»**: يبيع ويرتجع أي طقم بوزنه ورقم تشغيله مباشرةً من
  شاشة المبيعات — بلا حاجةٍ إلى شاشة الوارد (`free_sets`).

والخطة تُحفظ على الجهاز مع الحساب فتنطبق بلا إنترنت أيضاً. والمدير
العام والحساب المحلي بلا خطة: يرون كل شيء.
"""
import datetime as _dt
import hashlib
import json

import config

FACTORY, SHOP, CUSTOMER = "factory", "shop", "customer"
TYPES = ((FACTORY, "مصنع"), (SHOP, "محلات"), (CUSTOMER, "عميل"))
TYPE_LABEL = dict(TYPES)

# الشاشات بأسمائها الافتراضية في القائمة (المفتاح الثابت لكل شاشة)
MAIN_SCREENS = (
    "لوحة التحكم", "دليل الموديلات", "حركة الطقم", "كشف حساب",
    "الوارد من التصنيع", "مبيعات/مرتجعات", "المبيعات الضريبية",
    "سندات قبض/صرف", "العملاء — المبيعات والسداد", "مجموعات العملاء",
    "التسكيرات", "المشتريات", "القيود اليومية",
    "تقارير مبيعات وإنتاج المصنع", "التحليل والدراسات",
)
ADMIN_SCREENS = (
    "الإغلاق اليومي", "دليل الحسابات (شجرة الحسابات)",
    "التكويد الموحّد لجهات التعامل", "أرصدة الأستاذ المساعد",
    "الأرصدة الافتتاحية المخزنية", "تسوية فواقد الورشة", "حسابات الورشة",
    "الجرد الفعلي", "إدارة وتحويل العمليات", "سجل العمليات",
    "سلامة السجل (بصمة القيود)", "صحة النظام", "مطابقة كشف البنك",
    "أرشيف المستندات والطباعة", "من عدّل ماذا بعد الترحيل",
    "رواتب العمال والإدارة", "الإقرار الضريبي (VAT)", "القوائم المالية",
    "تحليل مبيعات العملاء", "إنتاج خزينة التصنيع (مطابقة)",
    "تهيئة أرصدة أول المدة (تاريخ القطع)", "الإقفال السنوي",
)
ALL_SCREENS = MAIN_SCREENS + ADMIN_SCREENS

# شاشات التصنيع — لا تلزم المحل ولا العميل
_WORKSHOP = {"تسوية فواقد الورشة", "حسابات الورشة",
             "رواتب العمال والإدارة", "إنتاج خزينة التصنيع (مطابقة)",
             "تقارير مبيعات وإنتاج المصنع"}

PRESETS = {
    FACTORY: ALL_SCREENS,
    SHOP: tuple(s for s in ALL_SCREENS if s not in _WORKSHOP),
    # العميل: يبيع ويرتجع ويقبض ويرى كشوفه — بلا وارد ولا تصنيع
    CUSTOMER: (
        "لوحة التحكم", "دليل الموديلات", "حركة الطقم", "كشف حساب",
        "مبيعات/مرتجعات", "سندات قبض/صرف", "العملاء — المبيعات والسداد",
        "مجموعات العملاء", "التسكيرات", "القيود اليومية",
        "الإغلاق اليومي", "دليل الحسابات (شجرة الحسابات)",
        "التكويد الموحّد لجهات التعامل", "الأرصدة الافتتاحية المخزنية",
        "أرشيف المستندات والطباعة", "القوائم المالية",
    ),
}

# الخطة النافذة في هذه الجلسة — None = بلا قيود (مدير/محلي/خادم قديم)
_current = None


# ══════════════════════════════════════════════════════════════════
#  الجلسة
# ══════════════════════════════════════════════════════════════════

def set_current(p):
    global _current
    _current = normalize(p) if p else None


def current():
    return _current


def kind():
    return (_current or {}).get("type") or ""


def free_sets():
    """هل يُباع الطقم غير المسجّل بإدخال وزنه مباشرةً؟ (نوع «عميل»)"""
    return kind() == CUSTOMER


def allowed(screen_key):
    """هل تظهر هذه الشاشة في القائمة وتُفتح؟"""
    p = _current
    if not p:
        return True
    scr = p.get("screens")
    if not scr:
        return True
    # شاشةٌ لا يعرفها الكتالوج (أُضيفت بعد إعداد الخطة) لا تُحجب
    if screen_key not in ALL_SCREENS:
        return True
    return screen_key in scr


# ══════════════════════════════════════════════════════════════════
#  شكل الخطة
# ══════════════════════════════════════════════════════════════════

def parse_screens(raw):
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(s) for s in raw if s]
    try:
        v = json.loads(raw)
        return [str(s) for s in v if s] if isinstance(v, list) else []
    except Exception:
        return []


def normalize(row):
    """صفّ الخادم أو المحفوظ ← قاموس موحّد."""
    row = dict(row or {})
    t = row.get("type") or row.get("plan_type") or FACTORY
    if t not in TYPE_LABEL:
        t = FACTORY
    exp = row.get("expires_at") or row.get("expires") or ""
    return {"type": t,
            "screens": parse_screens(row.get("screens")),
            "expires_at": str(exp)[:10] if exp else "",
            "max_devices": int(row.get("max_devices") or 0),
            "devices_used": int(row.get("devices_used") or 0),
            "device_ok": bool(row.get("device_ok", True)),
            "server_today": str(row.get("server_today") or "")[:10]}


def days_left(p, today=None):
    """الأيام الباقية في الاشتراك — None إن كان بلا نهاية."""
    exp = (p or {}).get("expires_at") or ""
    if not exp:
        return None
    try:
        end = _dt.date.fromisoformat(exp)
    except ValueError:
        return None
    if today is None:
        srv = (p or {}).get("server_today") or ""
        try:
            today = max(_dt.date.fromisoformat(srv), _dt.date.today()) \
                if srv else _dt.date.today()
        except ValueError:
            today = _dt.date.today()
    return (end - today).days


def check(p, today=None):
    """يرفع ValueError برسالةٍ واضحة إن كانت الخطة تمنع الدخول."""
    if not p:
        return
    left = days_left(p, today)
    if left is not None and left < 0:
        raise ValueError(
            f"انتهى الاشتراك في {p['expires_at']}.\n\n"
            "يرجى مراجعة الإدارة لتجديده.")
    if not p.get("device_ok", True):
        raise ValueError(
            f"هذا الجهاز غير مسجّل في الاشتراك — اكتمل عدد الأجهزة "
            f"المسموح ({p.get('max_devices')}).\n\n"
            "يرجى مراجعة الإدارة لإضافة الجهاز أو تفريغ قائمة الأجهزة.")


def notice(p):
    """تنبيهٌ قبل انتهاء الاشتراك بأسبوع — أو نصٌّ فارغ."""
    left = days_left(p)
    if left is None or left > 7:
        return ""
    if left == 0:
        return "ينتهي الاشتراك اليوم — راجع الإدارة لتجديده"
    return f"يبقى على انتهاء الاشتراك {left} يوماً"


# ══════════════════════════════════════════════════════════════════
#  هوية الجهاز
# ══════════════════════════════════════════════════════════════════

def _windows_guid():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SOFTWARE\Microsoft\Cryptography", 0,
                           winreg.KEY_READ | getattr(winreg,
                                                     "KEY_WOW64_64KEY", 0))
        v, _ = winreg.QueryValueEx(k, "MachineGuid")
        return str(v or "")
    except Exception:
        return ""


def device_id():
    """معرّف ثابت للجهاز — بصمةٌ منه لا قيمته الخام.

    على ويندوز: MachineGuid (ثابتٌ مع إعادة تثبيت البرنامج). وإلا رقمٌ
    عشوائي يُحفظ مرةً في مجلد البيانات."""
    raw = _windows_guid()
    if not raw:
        f = config.BASE_DIR / "data" / "device_id.txt"
        try:
            raw = f.read_text(encoding="utf-8").strip()
        except Exception:
            raw = ""
        if not raw:
            import uuid
            raw = uuid.uuid4().hex
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(raw, encoding="utf-8")
            except Exception:
                pass
    return hashlib.sha256(f"jadeite-device:{raw}".encode()).hexdigest()[:32]


def device_name():
    try:
        import platform
        return (platform.node() or "")[:60]
    except Exception:
        return ""
