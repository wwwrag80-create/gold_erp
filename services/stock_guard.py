# -*- coding: utf-8 -*-
"""حارس الأرصدة السالبة — يمنع الصرف من رصيدٍ غير موجود.

**المشكلة**: خزينة التصنيع والذهب المشغول والصندوق أرصدةٌ مادية: ما
لا يوجد فيها لا يُصرف منها. لكن المحرك المحاسبي يقبل أي قيد متوازن،
فبيع طقم أو صرف وزن يفوق الموجود يمرّ بلا اعتراض — ويظهر الخلل بعد
أسابيع في صورة رصيد سالب لا أحد يعرف متى بدأ ولا من أين.

**العلاج**: بعد ترحيل أي قيد يمسّ حساباً مادياً، يُقرأ رصيده. فإن صار
سالباً:

* `block`  → تُلغى العملية كاملةً برسالة واضحة (المعاملة لم تُغلق بعد،
             فالإلغاء تام ولا يبقى أثر).
* `warn`   → تمرّ العملية ويُسجَّل تنبيه يظهر للمستخدم فور الترحيل
             (الافتراضي — لا يوقف عملاً قائماً عند أول تحديث).
* `off`    → لا فحص.

**لماذا التنبيه هو الافتراضي**: المنع الفوري على نظام يعمل منذ شهور
قد يوقف عملاً مشروعاً بسبب رصيد افتتاحي ناقص أو ترتيب إدخال مختلف.
فيُنبَّه المستخدم أولاً، ومتى اطمأنّ رفع الوضع إلى المنع من شاشة
الإعدادات.

**ما لا يُحرس**: حسابات الجهات (العميل قد يكون له أو عليه) وحسابات
النتيجة. السالب فيها حالة مشروعة لا خطأ.
"""
import threading

SETTING_KEY = "stock_guard_mode"
MODES = ("off", "warn", "block")
DEFAULT_MODE = "warn"

# الحسابات المادية وحدها — ما فيها موجود فعلاً في الخزنة أو الدرج
WATCHED = {
    "1100": "خزينة التصنيع",
    "1200": "الذهب المشغول",
    "1310": "صندوق الكسر",
    "1350": "الصب والتصفية",
    "1400": "الصندوق النقدي",
}

# هامش تسامح: فروق التقريب في الجرام والهللة ليست رصيداً سالباً
EPS_GOLD = 0.011
EPS_CASH = 0.011


# ══════════════════════════════════════════════════════════════════
#  تنبيه آخر ترحيل — لكل خيط على حدة
# ------------------------------------------------------------------
#  الترحيل يجري في خيط الواجهة والنسخ الاحتياطي في خيط آخر، فتنبيهٌ
#  مشترك بينهما قد يظهر لعملية غير التي أنتجته. لذلك لكل خيط تنبيهه.
# ══════════════════════════════════════════════════════════════════

_local = threading.local()


def set_warning(text):
    _local.warning = text or ""


def take_warning():
    """يعيد تنبيه آخر ترحيل في هذا الخيط ويمسحه — فلا يتكرر."""
    txt = getattr(_local, "warning", "")
    _local.warning = ""
    return txt


def mode(conn):
    """وضع الحارس الحالي."""
    try:
        from models import fiscal
        m = (fiscal.get_setting(conn, SETTING_KEY, "") or "").strip()
    except Exception:
        m = ""
    return m if m in MODES else DEFAULT_MODE


def set_mode(conn, value, username=None):
    """يضبط وضع الحارس ويسجّله في التدقيق."""
    v = (value or "").strip()
    if v not in MODES:
        raise ValueError(f"وضع غير مدعوم: {value} — المتاح {MODES}")
    from models import fiscal
    from services.audit import log_action
    fiscal.set_setting(conn, SETTING_KEY, v, username)
    try:
        log_action(conn, username, "update", "app_settings", None,
                   f"stock_guard={v}")
    except Exception:
        pass
    return v


def _balances(conn, codes):
    """أرصدة الحسابات المطلوبة دفعةً واحدة — استعلام واحد لا استعلام
    لكل حساب، فالحارس يعمل بعد **كل** قيد في النظام."""
    if not codes:
        return {}
    qs = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT a.code, a.name,"
        f" COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
        f" COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
        f" FROM accounts a"
        f" LEFT JOIN journal_lines l ON l.account_id=a.id"
        f" LEFT JOIN journal_entries e ON e.id=l.entry_id"
        f"      AND e.is_deleted=0"
        f" WHERE a.code IN ({qs}) GROUP BY a.id", list(codes)).fetchall()
    return {r["code"]: {"name": r["name"], "gold": round(r["g"] or 0, 3),
                        "cash": round(r["c"] or 0, 2)} for r in rows}


def negatives(conn, codes=None):
    """الحسابات المادية ذات الرصيد السالب الآن.

    تُستعمل للفحص الدوري وللوحة التحكم — لا للترحيل وحده.
    """
    codes = list(codes or WATCHED.keys())
    out = []
    for code, b in _balances(conn, codes).items():
        neg_g = b["gold"] < -EPS_GOLD
        neg_c = b["cash"] < -EPS_CASH
        if neg_g or neg_c:
            out.append({"code": code, "name": WATCHED.get(code, b["name"]),
                        "gold": b["gold"] if neg_g else 0.0,
                        "cash": b["cash"] if neg_c else 0.0})
    return sorted(out, key=lambda r: r["code"])


def _entry_effect(conn, entry_id):
    """أثر هذا القيد وحده على كل حساب محروس: {الرمز: (ذهب, نقد)}.

    الفحص مقصور على الحسابات المحروسة: قيد رواتب لا علاقة له
    بالخزينة، وفحص كل الحسابات بعد كل قيد ثمنٌ بلا مقابل.
    """
    rows = conn.execute(
        "SELECT a.code,"
        " COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
        " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
        " FROM journal_lines l JOIN accounts a ON a.id=l.account_id"
        " WHERE l.entry_id=? GROUP BY a.code", (entry_id,)).fetchall()
    return {r["code"]: (round(r["g"] or 0, 3), round(r["c"] or 0, 2))
            for r in rows if r["code"] in WATCHED}


def check_entry(conn, entry_id, raise_on_block=True):
    """يفحص أثر قيدٍ رُحّل للتوّ. يعيد قائمة التنبيهات (قد تكون فارغة).

    **لا يُنبَّه إلا على ما زاد سوءاً بهذا القيد**: القيد الذي يُخرج
    من رصيد سالب (سداد · توريد · تسوية تصحيحية) يمرّ صامتاً. ولولا
    هذا الشرط لصار كل قيد في مصنعٍ رصيده سالب أصلاً ينبّه بلا فائدة،
    ولاستحال تصحيح العجز في وضع المنع لأن القيد المصحِّح نفسه يُرفض.

    في وضع `block` يرفع ValueError فتُلغى المعاملة كاملةً.
    """
    m = mode(conn)
    if m == "off":
        return []
    effect = _entry_effect(conn, entry_id)
    if not effect:
        return []
    neg = []
    for r in negatives(conn, list(effect.keys())):
        dg, dc = effect.get(r["code"], (0.0, 0.0))
        worse_gold = r["gold"] < 0 and dg < -EPS_GOLD
        worse_cash = r["cash"] < 0 and dc < -EPS_CASH
        if worse_gold or worse_cash:
            neg.append({**r,
                        "gold": r["gold"] if worse_gold else 0.0,
                        "cash": r["cash"] if worse_cash else 0.0,
                        "delta_gold": dg, "delta_cash": dc})
    if not neg:
        return []
    if m == "block" and raise_on_block:
        raise ValueError(message(neg, blocked=True))
    return neg


def message(neg, blocked=False):
    """رسالة عربية واضحة تصف الرصيد السالب وسببه."""
    from services import karat_view as kv
    parts = []
    for r in neg:
        bits = []
        if r["gold"]:
            bits.append(f"ذهب {kv.g(r['gold']):,.3f} {kv.unit()}")
        if r["cash"]:
            bits.append(f"نقد {r['cash']:,.2f} ريال")
        parts.append(f"• {r['code']} — {r['name']}: "
                     + " · ".join(bits))
    body = "\n".join(parts)
    if blocked:
        return ("الرصيد لا يكفي — أُلغيت العملية بالكامل:\n\n" + body
                + "\n\nالصرف من رصيدٍ غير موجود يجعل الجرد مستحيلاً. "
                  "راجع الأرصدة الافتتاحية أو رتّب إدخال العمليات "
                  "بتواريخها، أو خفّف الحارس إلى «تنبيه» من شاشة "
                  "الإعدادات إن كان السالب مقصوداً مؤقتاً.")
    return ("⚠ تنبيه: صار الرصيد سالباً بعد هذه العملية:\n\n" + body
            + "\n\nالعملية رُحّلت، لكن الرصيد السالب يعني صرفاً من "
              "غير موجود — راجعه قبل الجرد.")
