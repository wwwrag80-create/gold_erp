# -*- coding: utf-8 -*-
"""حدّ الائتمان — سقفٌ لِما يُسلَّم للعميل قبل أن يسدّد.

**المشكلة التي يحلّها**: أكثر ما يوجع مصانع الذهب دَينٌ كبر بلا أن
ينتبه أحد. الفاتورة تُرحَّل، والرصيد يُقرأ آخر الشهر، فيتبيّن أن عميلاً
أخذ ثلاثة أضعاف ما اعتاد — وقد خرجت البضاعة. تقرير أعمار الديون يقول
«تأخّر»، لكنه يقوله **بعد** الخروج لا قبله.

**العلاج**: لكل جهة سقفان — نقديٌّ بالريال ووزنيٌّ بالجرام — يُفحصان
**لحظة الترحيل**:

* `block`  → تُلغى العملية كاملةً (المعاملة لم تُغلق بعد فلا يبقى أثر).
* `warn`   → تمرّ ويُسجَّل تنبيه يظهر فور الترحيل (الافتراضي).
* `off`    → لا فحص.

**سقفٌ صفرٌ يعني بلا حدّ**، لا حدّاً صفرياً. فالنظام بعد التحديث يعمل
كما كان تماماً حتى يضع المستخدم سقفاً لمن يريد — لا يُوقَف عملٌ قائم
بسبب حقلٍ جديد فارغ.

**ولا يُنبَّه إلا على من زاد دينه بهذا القيد**: سند القبض من عميلٍ
متجاوزٍ سقفه يمرّ صامتاً، وإلا استحال تخفيض الدين في وضع المنع لأن
القيد المخفِّض نفسه يُرفض.

**الوزن بمكافئ عيار 18** كسائر أوزان النظام: السقف يُخزَّن بالأساس
ويُعرض ويُدخَل بعيار المصنع المختار.
"""
import threading

SETTING_KEY = "credit_guard_mode"
MODES = ("off", "warn", "block")
DEFAULT_MODE = "warn"

# هامش تسامح: فروق التقريب ليست تجاوزاً للسقف
EPS_GOLD = 0.011
EPS_CASH = 0.011

# الجهات التي لها ائتمان أصلاً — الموظف والشريك والجهة الداخلية
# ليست مديونيةً تجارية، وسقفها لا معنى له.
CREDIT_TYPES = ("customer", "supplier", "other")

_local = threading.local()


def set_warning(text):
    _local.warning = text or ""


def take_warning():
    """يعيد تنبيه آخر ترحيل في هذا الخيط ويمسحه — فلا يتكرر."""
    txt = getattr(_local, "warning", "")
    _local.warning = ""
    return txt


# ══════════════════════════════════════════════════════════════════
#  الوضع
# ══════════════════════════════════════════════════════════════════

def mode(conn):
    try:
        from models import fiscal
        m = (fiscal.get_setting(conn, SETTING_KEY, "") or "").strip()
    except Exception:
        m = ""
    return m if m in MODES else DEFAULT_MODE


def set_mode(conn, value, username=None):
    v = (value or "").strip()
    if v not in MODES:
        raise ValueError(f"وضع غير مدعوم: {value} — المتاح {MODES}")
    from models import fiscal
    from services.audit import log_action
    fiscal.set_setting(conn, SETTING_KEY, v, username)
    try:
        log_action(conn, username, "update", "app_settings", None,
                   f"credit_guard={v}")
    except Exception:
        pass
    return v


# ══════════════════════════════════════════════════════════════════
#  السقوف والأرصدة
# ══════════════════════════════════════════════════════════════════

def _limited_rows(conn, account_ids=None):
    """الجهات ذات السقف مع رصيدها — استعلام واحد لا استعلامٌ لكل جهة.

    الحارس يعمل بعد **كل** قيد في النظام، فاستعلامٌ لكل جهة يعني
    عشرات الاستعلامات في كل ترحيل.
    """
    q = ("SELECT e.id, e.name, e.entity_type, e.account_id, a.code,"
         " COALESCE(e.credit_limit,0) lim_cash,"
         " COALESCE(e.credit_limit_gold,0) lim_gold,"
         " COALESCE(SUM(l.gold_debit-l.gold_credit),0) gold,"
         " COALESCE(SUM(l.cash_debit-l.cash_credit),0) cash"
         " FROM entities e"
         " JOIN accounts a ON a.id=e.account_id"
         " LEFT JOIN journal_lines l ON l.account_id=e.account_id"
         " LEFT JOIN journal_entries j ON j.id=l.entry_id AND j.is_deleted=0"
         " WHERE e.is_deleted=0 AND e.is_internal=0"
         "   AND (COALESCE(e.credit_limit,0) > 0"
         "        OR COALESCE(e.credit_limit_gold,0) > 0)")
    params = []
    if account_ids:
        qs = ",".join("?" * len(account_ids))
        q += f" AND e.account_id IN ({qs})"
        params.extend(list(account_ids))
    q += " GROUP BY e.id"
    try:
        return conn.execute(q, params).fetchall()
    except Exception:
        return []          # قاعدة قديمة بلا أعمدة السقف — لا حارس


def over_limit(conn, account_ids=None):
    """الجهات المتجاوزة سقفها الآن.

    تُستعمل للفحص الدوري وللتقارير — لا للترحيل وحده.
    """
    out = []
    for r in _limited_rows(conn, account_ids):
        if str(r["entity_type"] or "") not in CREDIT_TYPES:
            continue
        lim_c = float(r["lim_cash"] or 0)
        lim_g = float(r["lim_gold"] or 0)
        cash = round(float(r["cash"] or 0), 2)
        gold = round(float(r["gold"] or 0), 3)
        over_c = lim_c > 0 and cash - lim_c > EPS_CASH
        over_g = lim_g > 0 and gold - lim_g > EPS_GOLD
        if not (over_c or over_g):
            continue
        out.append({
            "entity_id": r["id"], "name": r["name"], "code": r["code"],
            "account_id": r["account_id"],
            "cash": cash, "limit_cash": lim_c,
            "gold": gold, "limit_gold": lim_g,
            "over_cash": round(cash - lim_c, 2) if over_c else 0.0,
            "over_gold": round(gold - lim_g, 3) if over_g else 0.0,
        })
    return sorted(out, key=lambda r: (-r["over_cash"], -r["over_gold"]))


def _entry_effect(conn, entry_id):
    """أثر هذا القيد على كل حساب مسّه: {معرّف الحساب: (ذهب, نقد)}."""
    rows = conn.execute(
        "SELECT l.account_id aid,"
        " COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
        " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
        " FROM journal_lines l WHERE l.entry_id=?"
        " GROUP BY l.account_id", (entry_id,)).fetchall()
    return {r["aid"]: (round(r["g"] or 0, 3), round(r["c"] or 0, 2))
            for r in rows}


def check_entry(conn, entry_id, raise_on_block=True):
    """يفحص أثر قيدٍ رُحّل للتوّ على سقوف الجهات التي مسّها.

    يعيد قائمة التجاوزات (قد تكون فارغة). وفي وضع `block` يرفع
    ValueError فتُلغى المعاملة كاملةً قبل إغلاقها.
    """
    m = mode(conn)
    if m == "off":
        return []
    effect = _entry_effect(conn, entry_id)
    if not effect:
        return []
    hits = []
    for r in over_limit(conn, list(effect.keys())):
        dg, dc = effect.get(r["account_id"], (0.0, 0.0))
        worse_cash = r["over_cash"] > 0 and dc > EPS_CASH
        worse_gold = r["over_gold"] > 0 and dg > EPS_GOLD
        if not (worse_cash or worse_gold):
            continue          # القيد يخفّض الدين — لا شأن للحارس به
        hits.append({**r,
                     "over_cash": r["over_cash"] if worse_cash else 0.0,
                     "over_gold": r["over_gold"] if worse_gold else 0.0})
    if not hits:
        return []
    if m == "block" and raise_on_block:
        raise ValueError(message(hits, blocked=True))
    return hits


def message(hits, blocked=False):
    """رسالة عربية تصف التجاوز بالرقم والسقف والفرق."""
    from services import karat_view as kv
    parts = []
    for r in hits:
        bits = []
        if r["over_cash"]:
            bits.append(
                f"نقداً {r['cash']:,.2f} من سقف {r['limit_cash']:,.2f} ريال "
                f"(تجاوز {r['over_cash']:,.2f})")
        if r["over_gold"]:
            bits.append(
                f"وزناً {kv.g(r['gold']):,.3f} من سقف "
                f"{kv.g(r['limit_gold']):,.3f} {kv.unit()} "
                f"(تجاوز {kv.g(r['over_gold']):,.3f})")
        parts.append(f"• {r['name']}: " + " · ".join(bits))
    body = "\n".join(parts)
    if blocked:
        return ("تجاوزُ حدّ الائتمان — أُلغيت العملية بالكامل:\n\n" + body
                + "\n\nإما أن يسدّد العميل ما يخفّض رصيده تحت السقف، أو "
                  "يُرفع سقفه من شاشة «التكويد الموحّد لجهات التعامل»، "
                  "أو يُخفَّف الحارس إلى «تنبيه» من الشاشة نفسها.")
    return ("⚠ تنبيه: تجاوز هذا العميل حدّ الائتمان المقرّر له:\n\n" + body
            + "\n\nالعملية رُحّلت — راجع الرصيد قبل تسليم بضاعةٍ أخرى.")
