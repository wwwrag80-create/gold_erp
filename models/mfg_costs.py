# -*- coding: utf-8 -*-
"""رواتب العمال والإدارة — وتكاليف قسم التصنيع.

**المنطق المحاسبي**: العمال جهات من نوع `employee` تماماً كالموظفين،
فلكلٍّ حسابه الشخصي في شجرة الحسابات. ولكل عامل قيدُ راتبه المستقل
بسطرين (4.78 — كان قيداً واحداً للشهر):

    مدين  حـ/ مصروف رواتب عمال التصنيع (5710)   بصافي راتبه
    دائن  حـ/ حساب العامل الشخصي                 بصافي راتبه

فيظهر في كشف المصروف سطرٌ باسم كل عامل، وفي كشف حساب العامل راتبه
دائناً مع سُلفه مدينةً والصافي آلياً.

**عمود «عليه (مدين)»** رصيدُ العامل في كشف حسابه إلى هذه اللحظة:
راتبُه المُرحَّل دائن وسنداتُ صرفه مدينة. فإن بقي الرصيد مديناً فقد
أخذ أكثر مما استحقّ والفرق باقٍ عليه، وإن كان دائناً فلا شيء عليه
ويُترك العمود فارغاً. وهو أصدق من «مسحوبات الشهر» وحدها، لأنه يحمل
باقي الشهور السابقة أيضاً.

ولا يُطرح شيء من الصافي عند الترحيل: السحب قُيّد يوم وقوعه بسند
صرف، فطرحُه من الصافي المُرحَّل يخصمه مرتين. الصافي استحقاقُه
كاملاً، ورصيدُ حسابه يطرح السحب من نفسه. وعمود «المستحق» = الصافي
− ما عليه، للعرض والطباعة لا للترحيل.
"""
import calendar

from models.accounts import acc_id
from services.accounting_engine import post_entry
from services.audit import log_action
from services import numfmt as _nf

WORKER_EXPENSE = "5710"      # مصروف رواتب عمال التصنيع
CASH_BOX = "1400"            # صندوق النقدي
BANK = "1500"                # البنك

# القيمة الافتراضية لأجر الساعة الإضافية
DEFAULT_OVERTIME_RATE = 10.0

# أيام الشهر المعتمدة في احتساب الأجر اليومي لخصم الغياب
DAYS_PER_MONTH = 30.0


# ══════════════════════════════════════════════════════════════════
# الجداول
# ══════════════════════════════════════════════════════════════════

SCHEMA = """
CREATE TABLE IF NOT EXISTS mfg_targets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  period TEXT NOT NULL,                 -- YYYY-MM
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  month_days REAL DEFAULT 0,
  hours REAL DEFAULT 0,
  overtime_hours REAL DEFAULT 0,
  absence REAL DEFAULT 0,
  overtime_month REAL DEFAULT 0,
  target_per_hour REAL DEFAULT 0,
  actual_output REAL DEFAULT 0,
  target_amount REAL DEFAULT 0,
  notes TEXT DEFAULT '',
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(period, employee_id)
);

CREATE TABLE IF NOT EXISTS mfg_salaries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  period TEXT NOT NULL,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  basic_salary REAL DEFAULT 0,
  overtime_rate REAL DEFAULT 10,
  gold_loss REAL DEFAULT 0,
  gold_deduction REAL DEFAULT 0,
  deduction_manual REAL DEFAULT 0,
  target_amount REAL DEFAULT 0,
  bonus REAL DEFAULT 0,
  net_salary REAL DEFAULT 0,
  is_posted INTEGER DEFAULT 0,
  entry_id INTEGER,
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(period, employee_id)
);
"""


def ensure_schema(conn):
    """ينشئ الجداول **ويُرقّيها** — يضيف أي عمود جديد للجداول القائمة.

    `CREATE TABLE IF NOT EXISTS` لا يضيف أعمدة لجدول موجود مسبقاً،
    فيظهر خطأ «has no column named …» عند كل إضافة حقل. لذلك نستنتج
    الأعمدة من تعريف المخطط ونضيف الناقص تلقائياً — فلا يتكرر هذا
    النوع من الأخطاء أبداً.
    """
    import re
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)

    # ترقية ذاتية: أضف الأعمدة الناقصة لكل جدول في المخطط
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\((.*?)\n\)",
                         SCHEMA, re.S):
        table, body = m.group(1), m.group(2)
        have = {r["name"] for r in conn.execute(
            f"PRAGMA table_info({table})")}
        if not have:
            continue
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if (not line or line.upper().startswith(
                    ("UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "CONSTRAINT"))):
                continue
            col = line.split()[0]
            if col in have or not col.isidentifier():
                continue
            # نوع العمود وقيمته الافتراضية كما في المخطط
            decl = line[len(col):].strip()
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
# التبويب الأول: التارجت
# ══════════════════════════════════════════════════════════════════

def compute_target_row(r):
    """الأعمدة المحسوبة في شاشة التارجت.

    * الخصم                = الغياب × عدد الساعات
    * الساعات الإضافية/شهر = (أيام الشهر × الساعات) + الساعات الإضافية
    * التارجت/ساعة         = التارجت ÷ (أيام الشهر × الساعات)
    * المفترض إنتاجه       = التارجت/ساعة × الساعات الإضافية/شهر
    * الفرق                = إنتاجه الفعلي − المفترض إنتاجه

    كل التحويلات محمية: القيم الفارغة أو غير الرقمية تُعامل صفراً،
    والقسمة على صفر تُعيد صفراً — فلا يمكن لخلية فارغة أن تُسقط النظام.
    """
    def _f(k):
        try:
            v = r.get(k)
            if v is None or v == "":
                return 0.0
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    days = _f("month_days")
    hours = _f("hours")
    absence = _f("absence")
    ot = _f("overtime_hours")
    target = _f("target_amount")
    actual = _f("actual_output")

    base_hours = days * hours                 # ساعات الشهر الأساسية
    deduction = round(absence * hours, 2)
    # الساعات الإضافية/شهر = (أيام × ساعات) + الإضافية − ساعات الغياب
    ot_month = round(base_hours + ot - deduction, 2)
    tph = round(target / base_hours, 4) if base_hours else 0.0
    expected = round(tph * ot_month, 2)
    return {"deduction": deduction,
            "overtime_month": ot_month,
            "target_per_hour": tph,
            "expected_output": expected,
            "difference": round(actual - expected, 2)}


def list_targets(conn, period):
    """صفوف التارجت لكل العمال النشطين — تُنشأ فارغة إن لم توجد."""
    rows = []
    for e in section_people(conn, "target", period):
        r = conn.execute(
            "SELECT * FROM mfg_targets WHERE period=? AND employee_id=?",
            (period, e["id"])).fetchone()
        base = {"employee_id": e["id"], "name": e["name"],
                "month_days": 0, "hours": 0, "overtime_hours": 0,
                "absence": 0, "overtime_month": 0, "target_per_hour": 0,
                "actual_output": 0, "target_amount": 0}
        if r:
            base.update({k: r[k] for k in base if k in r.keys()})
            base["name"] = e["name"]
            base["employee_id"] = e["id"]
        base.update(compute_target_row(base))
        rows.append(base)
    return rows


def save_targets(conn, period, rows, username):
    """يحفظ صفوف التارجت (upsert لكل عامل)."""
    ensure_schema(conn)
    n = 0
    for r in rows:
        eid = r.get("employee_id")
        if not eid:
            continue
        conn.execute(
            "INSERT INTO mfg_targets(period,employee_id,month_days,hours,"
            "overtime_hours,absence,overtime_month,target_per_hour,"
            "actual_output,target_amount,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))"
            " ON CONFLICT(period,employee_id) DO UPDATE SET"
            " month_days=excluded.month_days, hours=excluded.hours,"
            " overtime_hours=excluded.overtime_hours,"
            " absence=excluded.absence,"
            " overtime_month=excluded.overtime_month,"
            " target_per_hour=excluded.target_per_hour,"
            " actual_output=excluded.actual_output,"
            " target_amount=excluded.target_amount,"
            " updated_at=datetime('now','localtime')",
            (period, eid, r.get("month_days") or 0, r.get("hours") or 0,
             r.get("overtime_hours") or 0, r.get("absence") or 0,
             r.get("overtime_month") or 0, r.get("target_per_hour") or 0,
             r.get("actual_output") or 0, r.get("target_amount") or 0))
        n += 1
    log_action(conn, username, "update", "mfg_targets", None,
               f"تارجت {period}: {n} عامل")
    return n


# ══════════════════════════════════════════════════════════════════
# السحوبات من سندات الصرف
# ══════════════════════════════════════════════════════════════════

def _period_range(period):
    yy, mm = (int(x) for x in period.split("-")[:2])
    last = calendar.monthrange(yy, mm)[1]
    return f"{yy:04d}-{mm:02d}-01", f"{yy:04d}-{mm:02d}-{last:02d}"


def owed_now(conn, employee_id):
    """ما على العامل الآن من كشف حسابه — المدين وحده.

    **الفرق عن «المسحوبات»**: المسحوبات سحبُ هذا الشهر وحده، وقد
    يكون العامل مديناً بباقٍ من شهرٍ سابق أو دائناً برصيدٍ له. وحسابُه
    في الدفتر يقول الحقيقة كاملةً إلى هذه اللحظة: راتبُه المُرحَّل
    دائن، وسندات صرفه مدينة.

    فإن كان الرصيد **مديناً** فقد أخذ أكثر مما استحقّ، والفرق باقٍ
    عليه — وهو ما يُعرض. وإن كان **دائناً** فلا شيء عليه، فيُترك
    فارغاً: صفرٌ يُكتب في خانةٍ معناها «عليه» يُقرأ خطأً على أنه
    رقمٌ محسوب، والفراغ أصدق.
    """
    ent = conn.execute(
        "SELECT account_id FROM entities"
        " WHERE employee_id=? AND is_deleted=0", (employee_id,)).fetchone()
    if not ent or not ent["account_id"]:
        return 0.0
    from services.accounting_engine import account_balance
    _g, cash = account_balance(conn, ent["account_id"])
    return round(cash, 2) if cash > 0.004 else 0.0


def balance_now(conn, employee_id):
    """رصيد العامل في كشف حسابه الآن — بإشارته: موجبٌ مدين (عليه)،
    سالبٌ دائن (له). عمود «الرصيد» يعرضه كما هو بطرفه (4.48)."""
    ent = conn.execute(
        "SELECT account_id FROM entities"
        " WHERE employee_id=? AND is_deleted=0", (employee_id,)).fetchone()
    if not ent or not ent["account_id"]:
        return 0.0
    from services.accounting_engine import account_balance
    _g, cash = account_balance(conn, ent["account_id"])
    return round(cash, 2) if abs(cash) > 0.004 else 0.0


def bal_text(v):
    """الرصيد رقماً بإشارته (4.50): عليه ← سالب «-1,200.00» · له ← موجب
    «500.00» · والصفر فراغ.

    `v` رصيد الدفتر (موجبٌ مدين = عليه)، فيُعرض بعكس إشارته. وعلامة
    اتجاهٍ (LRM) قبل الرقم تُبقي السالب أمامه في السطر العربي — فلا يُقرأ
    «1,200.00-».
    """
    v = round(float(v or 0), 2)
    if abs(v) < 0.005:
        return ""
    shown = -v
    return f"\u200e-{_nf.f2(abs(shown))}" if shown < 0 else _nf.f2(shown)


def withdrawals(conn, employee_id, period):
    """سحوبات العامل خلال الشهر مفصولة: نقدي وبنكي.

    تُجمع من سندات الصرف المسجّلة على حسابه، ويُميَّز النقدي عن البنكي
    بحساب الصرف المستخدم في السند.
    """
    d1, d2 = _period_range(period)
    ent = conn.execute(
        "SELECT id FROM entities WHERE employee_id=? AND is_deleted=0",
        (employee_id,)).fetchone()
    if not ent:
        return {"cash": 0.0, "bank": 0.0}
    # المبلغ يُجمع من أسطر السند إن وُجدت، وإلا من حقل السند نفسه —
    # فلا تضيع سحوبات مسجّلة بأي من الطريقتين.
    rows = conn.execute(
        "SELECT COALESCE(v.cash_account_code,'1400') acc,"
        " COALESCE((SELECT SUM(l.cash_amount) FROM voucher_lines l"
        "           WHERE l.voucher_id=v.id), v.cash_amount, 0) amt"
        " FROM vouchers v WHERE v.is_deleted=0 AND v.kind='payment'"
        " AND v.customer_id=? AND v.voucher_date BETWEEN ? AND ?",
        (ent["id"], d1, d2)).fetchall()
    cash = bank = 0.0
    for r in rows:
        amt = float(r["amt"] or 0)
        if not amt:
            continue
        if str(r["acc"]) == BANK:
            bank += amt
        else:
            cash += amt
    return {"cash": round(cash, 2), "bank": round(bank, 2)}


# ══════════════════════════════════════════════════════════════════
# التبويب الثاني: الرواتب
# ══════════════════════════════════════════════════════════════════

def compute_salary_row(r):
    """راتب العامل: الصافي المستحقّ له، ثم ما سحبه، ثم ما بقي.

        الصافي   = الأساسي + الإضافي + التارجت + المكافأة
                   − الخصم − خصم الذهب
        المسحوبات = ما أخذه بسندات صرفٍ خلال الشهر
        المستحق  = الصافي − المسحوبات

    **ولماذا خرجت المسحوبات من الصافي**: السحب قُيّد يوم وقوعه بسند
    صرف (مدين حساب العامل / دائن الصندوق). فلو طُرح من الصافي
    المُرحَّل لخُصم مرتين: مرةً في السند ومرةً في قيد الراتب —
    فيظهر حساب العامل مديناً بما لم يأخذه. الصافي هو استحقاقُه
    كاملاً، ورصيدُ حسابه يطرح السحب من نفسه.

    والمسحوبات والمستحق للعرض والطباعة وحدهما: **الصافي** هو ما
    يُنزَل في حساب كل عامل عند الترحيل.

    **والإضافي من الساعات الإضافية لا من كل الساعات**: كان يُضرب
    معاملُ الإضافي في ساعات الدوام كلها، فيصير «الإضافي» راتباً
    ثانياً. الصواب ساعاتُ الإضافي وحدها — وهي عمود «إضافية» في
    شاشة التارجت.

    محمي بالكامل ضد القيم الفارغة وغير الرقمية.
    """
    def _f(k, d=0.0):
        try:
            v = r.get(k)
            if v is None or v == "":
                return d
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return d

    basic = _f("basic_salary")
    ot_hours = _f("overtime_hours")
    rate = _f("overtime_rate", DEFAULT_OVERTIME_RATE)
    absence = _f("absence")
    overtime = round(ot_hours * rate, 2)

    # **خصم الغياب**: (الراتب الأساسي ÷ 30) × أيام الغياب.
    # يُحسب من الراتب نفسه لا يُجلب من التارجت — فالخصم المالي يخصّ
    # الأجر اليومي، وخصم التارجت يخصّ الإنتاج وهما مختلفان.
    # وإن أدخل المستخدم قيمة يدوية صريحة تُعتمد كما هي.
    manual = r.get("deduction_manual")
    if manual not in (None, "", 0, 0.0):
        deduction = _f("deduction_manual")
    else:
        deduction = round((basic / DAYS_PER_MONTH) * absence, 2) \
            if basic and absence else 0.0

    earn = basic + overtime + _f("target_amount") + _f("bonus")
    net = round(earn - deduction - _f("gold_deduction"), 2)
    draws = round(_f("draw_cash") + _f("draw_bank"), 2)
    # **المستحق = الصافي − ما عليه في الدفتر** لا − مسحوبات الشهر:
    # العامل قد يدخل الشهر وعليه باقٍ من شهرٍ سابق، أو له رصيد.
    # وكشفُ حسابه يجمع ذلك كلَّه إلى هذه اللحظة، فهو أصدق أساسٍ
    # لسؤال «كم أدفع له الآن؟».
    # و«owed» رصيدُه بإشارته (4.48): موجبٌ عليه، سالبٌ له. فإن رُحِّل
    # راتبُ الشهر فقد دخل الرصيدَ نفسه — والمستحق حينها ما له فيه
    # وحده، لا الصافي مرةً ثانية.
    owed = round(_f("owed"), 2)
    base = 0.0 if r.get("is_posted") else net
    return {"overtime": overtime, "deduction": deduction,
            "net_salary": net, "draws": draws, "owed": owed,
            "due": round(base - owed, 2)}


def _extra_cfg_path():
    from pathlib import Path

    import config
    d = Path(str(config.DB_PATH)).parent
    d.mkdir(parents=True, exist_ok=True)
    return d / "mfg_extra_staff.json"


def load_extra_staff():
    """معرّفات من أُضيف يدوياً لجدول رواتب التصنيع من غير عماله."""
    import json
    try:
        p = _extra_cfg_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return [int(x) for x in (d or []) if str(x).isdigit()
                    or isinstance(x, int)]
    except Exception:
        pass
    return []


def save_extra_staff(ids):
    import json
    try:
        _extra_cfg_path().write_text(
            json.dumps(sorted({int(x) for x in (ids or [])}),
                       ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def _order_cfg_path():
    from pathlib import Path

    import config
    d = Path(str(config.DB_PATH)).parent
    d.mkdir(parents=True, exist_ok=True)
    return d / "mfg_staff_order.json"


def load_staff_order():
    """ترتيب أسماء العمال كما رتّبه صاحب النظام.

    **لماذا يُحفظ**: الترتيب الأبجدي ترتيبُ الحاسوب لا ترتيبُ الورشة.
    صاحب المصنع يقرأ الكشف بترتيب الخطوط أو الأقدمية، فإن أعاد
    ترتيبه كل شهر لم ينتفع به. والترتيب عرضٌ محض — لا يمسّ راتباً
    ولا قيداً.
    """
    import json
    try:
        p = _order_cfg_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            out, seen = [], set()
            for x in (d or []):
                try:
                    i = int(x)
                except (TypeError, ValueError):
                    continue
                if i not in seen:
                    seen.add(i)
                    out.append(i)
            return out
    except Exception:
        pass
    return []


def save_staff_order(ids):
    import json
    try:
        out, seen = [], set()
        for x in (ids or []):
            i = int(x)
            if i not in seen:
                seen.add(i)
                out.append(i)
        _order_cfg_path().write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def sort_people(people):
    """يرتّب الأشخاص بالترتيب المحفوظ، ومن لا ترتيب له فبالاسم آخراً."""
    order = {}
    for i, e in enumerate(load_staff_order()):
        order[int(e)] = i
    big = len(order) + 10 ** 6

    def _key(p):
        try:
            pid = int(p["id"])
        except Exception:
            pid = -1
        try:
            admin = 0 if (p["staff_kind"] or "employee") == "worker" else 1
        except (KeyError, IndexError, TypeError):
            admin = 0
        return (order.get(pid, big), admin, str(p["name"] or ""))

    return sorted(people, key=_key)


# ══════════════════════════════════════════════════════════════════
# من يظهر في كل جدول — رواتب العمال والإدارة (4.54)
# ══════════════════════════════════════════════════════════════════
# شاشة «إنزال رواتب الموظفين» أُلغيت: كل موظفٍ — عاملاً كان أو
# إدارياً — يظهر هنا وتُنزَل رواتبه من مكانٍ واحد. والتارجت لعمال
# التصنيع أصلاً.
#
# **والإزالة ليست حذفاً**: موظفٌ في إجازة يُزال من جدول الرواتب فلا
# ينزل له راتب، وحسابُه وقيودُه وكشفُه باقيةٌ كما هي. فإذا عاد أُضيف
# بزرّ «إضافة» فعاد صفُّه. والإزالة لكل جدولٍ وحده: من أُزيل من
# الرواتب قد يبقى في التارجت، والعكس.
SECTIONS = {"target": "التارجت", "salary": "الرواتب"}
_SECT_KEY = "mfg_staff_sections"


def load_sections(conn):
    """{"target": {"add": [...], "hide": [...]}, "salary": {...}}"""
    import json
    out = {k: {"add": [], "hide": []} for k in SECTIONS}
    try:
        from models import fiscal
        raw = fiscal.get_setting(conn, _SECT_KEY, "")
        d = json.loads(raw) if raw else {}
        for k in SECTIONS:
            for part in ("add", "hide"):
                out[k][part] = sorted({int(x) for x in
                                       (d.get(k, {}).get(part) or [])
                                       if str(x).lstrip("-").isdigit()})
    except Exception:
        pass
    return out


def save_sections(conn, d, username=None):
    import json
    from models import fiscal
    clean = {k: {"add": sorted({int(x) for x in d.get(k, {}).get("add", [])}),
                 "hide": sorted({int(x) for x in
                                 d.get(k, {}).get("hide", [])})}
             for k in SECTIONS}
    fiscal.set_setting(conn, _SECT_KEY, json.dumps(clean), username)
    return clean


def _default_ids(conn, section):
    """أهل الجدول افتراضاً: التارجت لعمال التصنيع، والرواتب للجميع."""
    from models import payroll
    people = (payroll.list_workers(conn) if section == "target"
              else payroll.list_employees(conn, active_only=True))
    return {e["id"] for e in people}


def _people_by_ids(conn, ids):
    ids = [int(i) for i in ids]
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    try:
        return list(conn.execute(
            "SELECT e.*, en.job_title job_title, en.id entity_id,"
            " en.account_id account_id FROM employees e"
            " LEFT JOIN entities en ON en.employee_id=e.id"
            "   AND en.is_deleted=0"
            f" WHERE e.is_deleted=0 AND e.id IN ({ph})", ids))
    except Exception:
        return []


def _posted_in(conn, period, employee_id):
    """هل نزل راتبُه لهذا الشهر بقيدٍ قائم؟ (فيبقى صفُّه ولو أُزيل)"""
    if not period:
        return False
    try:
        r = conn.execute(
            "SELECT is_posted, entry_id FROM mfg_salaries"
            " WHERE period=? AND employee_id=?",
            (period, employee_id)).fetchone()
    except Exception:
        return False
    return _posted(conn, r) or _payroll_accrued(conn, employee_id, period)


def section_people(conn, section, period=None):
    """من يظهر في الجدول: أهلُه افتراضاً + المضاف − المُزال.

    ومن أُزيل بعد أن نزل راتب شهرٍ له يبقى ظاهراً **في ذلك الشهر
    وحده** — فكشفُ شهرٍ مضى لا تنقص منه رواتبُ نزلت فعلاً.
    """
    sec = load_sections(conn).get(section, {"add": [], "hide": []})
    hide = set(sec["hide"])
    ids = (_default_ids(conn, section) | set(sec["add"])) - hide
    if section == "salary" and period:
        ids |= {i for i in hide if _posted_in(conn, period, i)}
    return sort_people(_people_by_ids(conn, ids))


def available_people(conn, section):
    """من يمكن إضافته للجدول: المُزالون أولاً ثم بقية الموظفين."""
    from models import payroll
    sec = load_sections(conn).get(section, {"add": [], "hide": []})
    shown = {e["id"] for e in section_people(conn, section)}
    hidden = set(sec["hide"])
    out = []
    for e in payroll.list_employees(conn, active_only=True):
        if e["id"] in shown:
            continue
        out.append({"id": e["id"], "name": e["name"],
                    "hidden": e["id"] in hidden,
                    "kind": (e["staff_kind"] or "employee")})
    out.sort(key=lambda x: (not x["hidden"], x["kind"] != "worker",
                            x["name"]))
    return out


def remove_person(conn, section, employee_id, username):
    """يُزيل الشخص من جدولٍ — لا يمسّ حسابه ولا قيوده."""
    d = load_sections(conn)
    sec = d[section]
    eid = int(employee_id)
    sec["add"] = [i for i in sec["add"] if i != eid]
    if eid in _default_ids(conn, section) and eid not in sec["hide"]:
        sec["hide"].append(eid)
    save_sections(conn, d, username)
    log_action(conn, username, "update", "mfg_staff", eid,
               f"إزالة من جدول {SECTIONS[section]} (الحساب باقٍ)")


def add_person(conn, section, employee_id, username):
    """يعيد المُزال أو يضيف موظفاً للجدول."""
    d = load_sections(conn)
    sec = d[section]
    eid = int(employee_id)
    sec["hide"] = [i for i in sec["hide"] if i != eid]
    if eid not in _default_ids(conn, section) and eid not in sec["add"]:
        sec["add"].append(eid)
    save_sections(conn, d, username)
    log_action(conn, username, "update", "mfg_staff", eid,
               f"إضافة إلى جدول {SECTIONS[section]}")


def _salary_people(conn, period=None):
    """أهل جدول الرواتب (توافقٌ مع ما قبل 4.54)."""
    return section_people(conn, "salary", period)


def _payroll_accrued(conn, employee_id, period):
    """راتبٌ نزل لهذا الشهر من شاشة «إنزال رواتب الموظفين» الملغاة —
    فلا يُنزَل مرةً ثانية من هنا."""
    try:
        return bool(conn.execute(
            "SELECT 1 FROM payroll_ledger WHERE employee_id=? AND period=?"
            " AND kind='accrual' AND is_deleted=0",
            (employee_id, period)).fetchone())
    except Exception:
        return False


def _posted(conn, saved):
    """مرحّلٌ فعلاً: موسومٌ بالترحيل **وقيدُه قائم**. صفٌّ رُحّل بقيدٍ
    حُذف لاحقاً (قاعدةٌ سبقت عكسَ الحذف لوسم الترحيل) يعود معلّقاً
    فيُنزَل راتب الشهر من جديد."""
    if not saved or not saved["is_posted"]:
        return False
    if not saved["entry_id"]:
        return True
    return bool(conn.execute(
        "SELECT 1 FROM journal_entries WHERE id=? AND is_deleted=0",
        (saved["entry_id"],)).fetchone())


def refresh_posted(conn, period, rows):
    """يحدّث وسم «مرحّل» في صفوفٍ محمّلة من قبل من القاعدة الآن —
    فقيدٌ حُذف من كشف العامل والشاشة مفتوحة لا يمنع إنزال الشهر."""
    for r in rows:
        if r.get("employee_id"):
            r["is_posted"] = _posted_in(conn, period, r["employee_id"])
    return rows


def list_salaries(conn, period):
    """صفوف الرواتب مرتبطة ديناميكياً بالتارجت وسندات الصرف."""
    ensure_schema(conn)
    targets = {t["employee_id"]: t for t in list_targets(conn, period)}
    rows = []
    for e in _salary_people(conn, period):
        saved = conn.execute(
            "SELECT * FROM mfg_salaries WHERE period=? AND employee_id=?",
            (period, e["id"])).fetchone()
        t = targets.get(e["id"], {})
        w = withdrawals(conn, e["id"], period)
        r = {
            "employee_id": e["id"], "name": e["name"],
            "basic_salary": (saved["basic_salary"] if saved
                             else (e["basic_salary"] or 0)),
            "hours": t.get("hours", 0),
            # ساعات **الإضافي** من التارجت — لا ساعات الدوام كلها
            "overtime_hours": t.get("overtime_hours", 0),
            "overtime_rate": (saved["overtime_rate"] if saved
                              else DEFAULT_OVERTIME_RATE),
            "absence": t.get("absence", 0),
            # الخصم يُحسب من الراتب لا يُجلب من التارجت
            "deduction": 0.0,
            "deduction_manual": (saved["deduction_manual"]
                                 if saved and "deduction_manual"
                                 in saved.keys() else 0),
            "gold_loss": saved["gold_loss"] if saved else 0,
            "gold_deduction": saved["gold_deduction"] if saved else 0,
            # التارجت في كشف الرواتب هو **الفرق** بين الإنتاج الفعلي
            # والمفترض — فهو ما يستحقه العامل زيادةً أو يُخصم منه.
            "target_amount": (saved["target_amount"] if saved
                              and saved["target_amount"]
                              else t.get("difference", 0)),
            "bonus": saved["bonus"] if saved else 0,
            "draw_cash": w["cash"], "draw_bank": w["bank"],
            # رصيدُه في الدفتر الآن: المدين وحده يُعرض
            "owed": balance_now(conn, e["id"]),
            "is_posted": (_posted(conn, saved)
                          or _payroll_accrued(conn, e["id"], period)),
            # عاملُ تصنيع أم موظفٌ إداري — ومنه حسابُ مصروف راتبه
            "staff_kind": (e["staff_kind"] or "employee"),
            "is_extra": (e["staff_kind"] or "employee") != "worker",
        }
        r.update(compute_salary_row(r))
        rows.append(r)
    return rows


def save_salaries(conn, period, rows, username, edited=()):
    """يحفظ صفوف الشهر. ومن في `edited` (معرّفات من عُدّل صفُّه) وكان
    راتبه مرحّلاً يتبعه قيدُه بالصافي الجديد (`repost_salary`). أما من
    لم يُلمَس صفُّه فلا يُعاد قيده ولو اختلف حسابُه الآن — شهرٌ مضى لا
    يتغيّر رقمه لأن صفاً آخر عُدّل بجواره."""
    ensure_schema(conn)
    n = 0
    for r in rows:
        eid = r.get("employee_id")
        if not eid:
            continue
        calc = compute_salary_row(r)
        conn.execute(
            "INSERT INTO mfg_salaries(period,employee_id,basic_salary,"
            "overtime_rate,gold_loss,gold_deduction,deduction_manual,"
            "target_amount,bonus,net_salary,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))"
            " ON CONFLICT(period,employee_id) DO UPDATE SET"
            " basic_salary=excluded.basic_salary,"
            " overtime_rate=excluded.overtime_rate,"
            " gold_loss=excluded.gold_loss,"
            " gold_deduction=excluded.gold_deduction,"
            " deduction_manual=excluded.deduction_manual,"
            " target_amount=excluded.target_amount,"
            " bonus=excluded.bonus, net_salary=excluded.net_salary,"
            " updated_at=datetime('now','localtime')",
            (period, eid, r.get("basic_salary") or 0,
             r.get("overtime_rate") or DEFAULT_OVERTIME_RATE,
             r.get("gold_loss") or 0, r.get("gold_deduction") or 0,
             r.get("deduction_manual") or 0,
             r.get("target_amount") or 0, r.get("bonus") or 0,
             calc["net_salary"]))
        n += 1
    log_action(conn, username, "update", "mfg_salaries", None,
               f"رواتب عمال {period}: {n} عامل")
    for eid in {int(i) for i in edited or ()}:
        repost_salary(conn, period, eid, username)
    return n


# ══════════════════════════════════════════════════════════════════
# الترحيل المحاسبي
# ══════════════════════════════════════════════════════════════════

def _salary_row_id(conn, period, employee_id, net):
    """معرّف صفّ الشهر — يُنشأ إن لم يُحفظ بعد، فلكل قيدٍ مستندُه."""
    conn.execute(
        "INSERT INTO mfg_salaries(period,employee_id,net_salary)"
        " VALUES(?,?,?) ON CONFLICT(period,employee_id) DO NOTHING",
        (period, employee_id, net))
    return conn.execute(
        "SELECT id FROM mfg_salaries WHERE period=? AND employee_id=?",
        (period, employee_id)).fetchone()["id"]


def _post_one(conn, period, employee_id, net, date, username, note=""):
    """قيدُ راتب شخصٍ واحد — سطران باسمه:

        مدين  مصروف الرواتب (5710 للعامل · مصروف الرواتب للإداري)
        دائن  حسابه الشخصي

    **قيدٌ لكل عامل لا قيدٌ للشهر**: القيد الجامع يجعل المقابل في كشف
    العامل عاملاً آخر من القيد نفسه، ولا يُعدَّل راتب واحدٍ منه إلا
    بإعادة قيد الجميع."""
    from models import payroll as _pr
    net = round(float(net), 2)
    emp = conn.execute(
        "SELECT name, COALESCE(staff_kind,'employee') k FROM employees"
        " WHERE id=?", (employee_id,)).fetchone()
    # حسابه الشخصي في الدليل — وموظفٌ قديم غير مُكوَّد يُقيَّد على
    # الحساب الأب «سلف الموظفين» كما كانت تفعل شاشة الموظفين
    acc = _pr.advance_account_id(conn, employee_id)
    if not emp or not acc:
        raise ValueError(f"الموظف «{emp['name'] if emp else employee_id}»"
                         " بلا حساب في الشجرة")
    worker = emp["k"] == "worker"
    # عامل التصنيع على «مصروف رواتب عمال التصنيع»، والإداري على
    # «مصروف الرواتب والأجور» — فتبقى قائمة الدخل تفصل الصنفين
    exp = acc_id(conn, WORKER_EXPENSE if worker else _pr.SALARY_EXP)
    desc = (f"راتب عمال شهر {period} - {emp['name']}" if worker
            else f"راتب شهر {period} - {emp['name']}")
    rid = _salary_row_id(conn, period, employee_id, net)
    entry_id = post_entry(
        conn, date, f"راتب شهر {period} - {emp['name']}",
        [{"account_id": exp, "cash_debit": net, "line_desc": desc},
         {"account_id": acc, "cash_credit": net, "line_desc": desc}],
        source_table="mfg_salaries", source_id=rid, username=username,
        note=note or "")
    conn.execute("UPDATE mfg_salaries SET is_posted=1, entry_id=?"
                 " WHERE id=?", (entry_id, rid))
    return {"id": rid, "entry_id": entry_id, "net": net}


def post_salaries(conn, period, username, entry_date=None, rows=None):
    """يرحّل رواتب الشهر **بقيدٍ مستقل لكل عامل** (انظر `_post_one`).

    البيان على الطرفين: «راتب عمال شهر YYYY-MM - اسم العامل» فيظهر
    في كشف المصروف سطرٌ باسم كل عامل، وفي كشف العامل مقابلُه المصروف.
    """
    import datetime as _dt
    ensure_schema(conn)
    rows = rows if rows is not None else list_salaries(conn, period)
    refresh_posted(conn, period, rows)
    pending = [r for r in rows
               if float(r.get("net_salary") or 0) != 0
               and not r.get("is_posted")]
    if not pending:
        raise ValueError(
            f"لا توجد رواتب معلّقة لشهر {period} — ربما رُحّلت مسبقاً")

    date = entry_date or _dt.date.today().isoformat()
    ids, total = [], 0.0
    for r in pending:
        res = _post_one(conn, period, r["employee_id"], r["net_salary"],
                        date, username)
        ids.append(res["entry_id"])
        r["is_posted"] = True
        total += res["net"]
    log_action(conn, username, "create", "mfg_salaries", ids[0],
               f"ترحيل رواتب {period}: {len(pending)} موظف بقيدٍ لكلٍّ"
               f" بإجمالي {_nf.f2(total)}")
    return {"entry_id": ids[0], "entry_ids": ids, "count": len(pending),
            "total": round(total, 2)}


def _entry_amount(conn, entry_id):
    return round(float(conn.execute(
        "SELECT COALESCE(SUM(cash_debit),0) v FROM journal_lines"
        " WHERE entry_id=?", (entry_id,)).fetchone()["v"]), 2)


def _shared(conn, entry_id):
    """قيدٌ جامع من قبل 4.78 يحمل رواتب أكثر من شخص."""
    return conn.execute(
        "SELECT COUNT(*) n FROM mfg_salaries WHERE entry_id=?",
        (entry_id,)).fetchone()["n"] > 1


def repost_salary(conn, period, employee_id, username, entry_date=None):
    """راتبٌ مرحّل عُدّل: يتبعه قيدُه بالصافي الجديد.

    التعديل عندنا إلغاءٌ ثم ترحيل (`editing.repost`) لا تحريرُ أسطر —
    فسلسلة البصمات تبقى سليمة، والقيد الجديد يرث تاريخ القديم وموضعه
    في الكشوف، و«من عدّل ماذا» يحفظ القيمتين. وصافٍ صار صفراً يُلغي
    القيد ويعيد الصف معلّقاً. يعيد None إن لم يتغيّر شيء.

    `entry_date` (4.81): تاريخٌ جديد للقيد من نافذة «تعديل» — يُعاد القيد
    به ولو لم يتغيّر الصافي."""
    saved = conn.execute(
        "SELECT * FROM mfg_salaries WHERE period=? AND employee_id=?",
        (period, employee_id)).fetchone()
    if not saved or not saved["entry_id"] or not _posted(conn, saved):
        return None
    if _shared(conn, saved["entry_id"]):
        split_combined(conn, username, only=saved["entry_id"], strict=True)
        saved = conn.execute("SELECT * FROM mfg_salaries WHERE id=?",
                             (saved["id"],)).fetchone()
    eid = saved["entry_id"]
    net = round(float(saved["net_salary"] or 0), 2)
    e = conn.execute("SELECT entry_date, user_note FROM journal_entries"
                     " WHERE id=?", (eid,)).fetchone()
    date = str(entry_date or e["entry_date"])[:10]
    if abs(_entry_amount(conn, eid) - net) < 0.005 \
            and date == str(e["entry_date"])[:10]:
        return None
    from services.audit import reverse_entry
    if not net:
        reverse_entry(conn, eid, username)
        return {"entry_id": None, "old_entry_id": eid, "net": 0.0}
    from models import editing
    res = editing.repost(conn, eid, username, _post_one, period,
                         employee_id, net, date, username,
                         e["user_note"] or "")
    res["old_entry_id"] = eid
    return res


def entry_date_of(conn, period, employee_id):
    """تاريخ قيد راتب العامل لهذا الشهر — أو None إن لم يُرحَّل."""
    r = conn.execute(
        "SELECT e.entry_date FROM mfg_salaries s JOIN journal_entries e"
        " ON e.id=s.entry_id AND e.is_deleted=0"
        " WHERE s.period=? AND s.employee_id=?",
        (period, employee_id)).fetchone()
    return r["entry_date"] if r else None


def posted_date(conn, period):
    """تاريخ قيود رواتب الشهر المرحّلة (الأكثر تكراراً) — أو None."""
    r = conn.execute(
        "SELECT e.entry_date d, COUNT(*) n FROM mfg_salaries s"
        " JOIN journal_entries e ON e.id=s.entry_id AND e.is_deleted=0"
        " WHERE s.period=? AND s.is_posted=1 GROUP BY e.entry_date"
        " ORDER BY n DESC, d DESC LIMIT 1", (period,)).fetchone()
    return r["d"] if r else None


def redate_salaries(conn, period, entry_date, username):
    """يغيّر تاريخ قيود رواتب الشهر المرحّلة كلها إلى `entry_date` (4.82).

    تاريخٌ أُدخل خطأً عند الإنزال يُصحَّح بنقرةٍ واحدة لا قيداً قيداً.
    المبالغ كما هي في القيود — يتغيّر التاريخ وحده — وكل قيدٍ يُلغى
    ويُرحَّل بديله (`editing.repost`) فيبقى أثره في «من عدّل ماذا».
    يعيد عدد القيود التي تغيّر تاريخها."""
    from services.dates import normalize_date
    from models import editing
    date = normalize_date(entry_date, "تاريخ القيد")
    n = 0
    for s in conn.execute(
            "SELECT * FROM mfg_salaries WHERE period=? AND is_posted=1"
            " AND entry_id IS NOT NULL", (period,)).fetchall():
        if not _posted(conn, s):
            continue
        if _shared(conn, s["entry_id"]):
            split_combined(conn, username, only=s["entry_id"], strict=True)
            s = conn.execute("SELECT * FROM mfg_salaries WHERE id=?",
                             (s["id"],)).fetchone()
        eid = s["entry_id"]
        e = conn.execute("SELECT entry_date, user_note FROM journal_entries"
                         " WHERE id=?", (eid,)).fetchone()
        if str(e["entry_date"])[:10] == date:
            continue
        amt = _entry_amount(conn, eid)
        editing.repost(conn, eid, username, _post_one, period,
                       s["employee_id"], amt, date, username,
                       e["user_note"] or "")
        n += 1
    if n:
        log_action(conn, username, "update", "mfg_salaries", None,
                   f"تاريخ قيود رواتب {period}: {n} قيد ← {date}")
    return n


EDIT_KEYS = ("basic_salary", "overtime_rate", "deduction_manual",
             "gold_loss", "gold_deduction", "target_amount", "bonus")


def edit_posted_salary(conn, period, employee_id, values, username,
                       entry_date=None):
    """تعديل راتب عاملٍ مرحّل من نافذته (4.81).

    يُحفظ صفّه بالقيم الجديدة ثم يُعاد قيدُه هو وحده بالصافي الجديد
    وبالتاريخ المختار (إلغاءٌ ثم ترحيل — `repost_salary`). يعيد
    {net, entry_id, old_entry_id} أو None إن لم يتغيّر شيء."""
    eid = int(employee_id)
    rows = [r for r in list_salaries(conn, period)
            if r["employee_id"] == eid]
    if not rows:
        raise ValueError("العامل ليس في جدول رواتب هذا الشهر")
    r = rows[0]
    if not r.get("is_posted"):
        raise ValueError("راتب هذا العامل لم يُرحَّل بعد — عدّله في"
                         " الجدول ثم أنزل الرواتب")
    for k in EDIT_KEYS:
        if k in values:
            r[k] = float(values[k] or 0)
    # الخصم اليدوي يحلّ محل المحسوب كما في الجدول
    if "deduction_manual" in values:
        r["deduction"] = r["deduction_manual"]
    r.update(compute_salary_row(r))
    save_salaries(conn, period, [r], username)
    res = repost_salary(conn, period, eid, username, entry_date=entry_date)
    log_action(conn, username, "update", "mfg_salaries", eid,
               f"تعديل راتب مرحّل {period} — {r['name']}: صافي"
               f" {_nf.f2(r['net_salary'])}"
               + (f" بتاريخ {entry_date}" if entry_date else ""))
    out = {"net": round(float(r["net_salary"]), 2)}
    if res:
        out.update(res)
    return out


def split_combined(conn, username="system", only=None, strict=False):
    """يقسم قيود الرواتب الجامعة (قبل 4.78) قيداً لكل عامل.

    كل زوج أسطر ببيانٍ واحد (مدين مصروف · دائن حساب العامل) يصير
    قيداً مستقلاً بتاريخ الأصل وموضعه، ويُحذف الجامع حذفاً منطقياً.
    فيصحّ المقابل في كشف كل عامل: المصروف لا العامل الذي تحته.
    وأي شكٍّ في المطابقة (سطرٌ بلا زوج · صفٌّ بلا سطر · فترةٌ مقفلة)
    يترك القيد كما هو — التقسيم إصلاحُ عرضٍ لا يجوز أن يغيّر رقماً.
    كل قيدٍ داخل نقطة حفظ: يُقسم كاملاً أو لا يُمسّ."""
    from models import payroll as _pr
    from services.audit import reverse_entry
    ensure_schema(conn)
    q = ("SELECT e.* FROM journal_entries e WHERE e.is_deleted=0"
         " AND e.source_table='mfg_salaries'"
         " AND (SELECT COUNT(*) FROM mfg_salaries s"
         "      WHERE s.entry_id=e.id) > 1")
    args = ()
    if only:
        q += " AND e.id=?"
        args = (only,)
    done = 0
    for e in conn.execute(q, args).fetchall():
        conn.execute("SAVEPOINT sal_split")
        try:
            rows = conn.execute(
                "SELECT s.*, m.name FROM mfg_salaries s"
                " JOIN employees m ON m.id=s.employee_id"
                " WHERE s.entry_id=?", (e["id"],)).fetchall()
            groups = {}
            for l in conn.execute("SELECT * FROM journal_lines"
                                  " WHERE entry_id=? ORDER BY id",
                                  (e["id"],)):
                groups.setdefault(l["line_desc"] or "", []).append(l)
            pairs = []
            for desc, ls in groups.items():
                dr = [l for l in ls if (l["cash_debit"] or 0) > 0]
                cr = [l for l in ls if (l["cash_credit"] or 0) > 0]
                if (len(ls) != 2 or len(dr) != 1 or len(cr) != 1
                        or abs(dr[0]["cash_debit"]
                               - cr[0]["cash_credit"]) > 0.005
                        or any((l["gold_debit"] or 0)
                               or (l["gold_credit"] or 0) for l in ls)):
                    raise ValueError(f"أسطر غير مزدوجة: {desc}")
                pairs.append((desc, dr[0], cr[0]))
            if len(pairs) != len(rows):
                raise ValueError("عدد الأسطر لا يطابق عدد الرواتب")
            matched, used = [], set()
            for r in rows:
                acc = _pr.advance_account_id(conn, r["employee_id"])
                cand = [p for p in pairs if p[2]["account_id"] == acc
                        and id(p) not in used]
                if len(cand) > 1:
                    cand = [p for p in cand
                            if p[0].endswith(f"- {r['name']}")]
                if len(cand) != 1:
                    raise ValueError(f"تعذّرت مطابقة «{r['name']}»")
                used.add(id(cand[0]))
                matched.append((r, cand[0]))
            key = e["sort_key"] if "sort_key" in e.keys() else None
            reverse_entry(conn, e["id"], username)
            new_ids = []
            for r, (desc, dr, cr) in matched:
                amt = round(float(cr["cash_credit"]), 2)
                nid = post_entry(
                    conn, e["entry_date"],
                    f"راتب شهر {r['period']} - {r['name']}",
                    [{"account_id": dr["account_id"], "cash_debit": amt,
                      "line_desc": desc},
                     {"account_id": cr["account_id"], "cash_credit": amt,
                      "line_desc": desc}],
                    source_table="mfg_salaries", source_id=r["id"],
                    username=e["created_by"] or username,
                    note=e["user_note"] or "")
                conn.execute("UPDATE journal_entries SET sort_key=?"
                             " WHERE id=?", (key or e["id"], nid))
                conn.execute("UPDATE mfg_salaries SET is_posted=1,"
                             " entry_id=? WHERE id=?", (nid, r["id"]))
                new_ids.append(nid)
            log_action(conn, username, "update", "mfg_salaries", e["id"],
                       f"تقسيم قيد الرواتب الجامع {e['doc_no'] or e['id']}"
                       f" إلى {len(new_ids)} قيد — قيدٌ لكل عامل")
            conn.execute("RELEASE sal_split")
            done += 1
        except Exception:
            conn.execute("ROLLBACK TO sal_split")
            conn.execute("RELEASE sal_split")
            if strict:
                raise
    return done


# ══════════════════════════════════════════════════════════════════
# ملخص تكاليف قسم التصنيع
# ══════════════════════════════════════════════════════════════════

# حسابات الفاقد التشغيلي لقسم التصنيع (وزناً)
MFG_LOSS_CODES = ("5110", "5130")
# حسابات المصروف التشغيلي التي تُرحَّل إليها المشتريات والمصاريف
MFG_EXPENSE_CODES = ("5500", "5510", "5800", "5900")


def summary(conn, period):
    """ملخص القسم بثلاثة أعمدة: الاسم · المبلغ · الذهب.

    * **رواتب العمال**   = صافي الرواتب − إجمالي التارجت
      (لأن التارجت جزء من الصافي، ففصله يبيّن الأجر الأساسي وحده)
    * **فاقد تشغيلي**    = حركة حساب الفاقد خلال الشهر (وزناً وقيمةً)
    * **التارجت**        = إجمالي تارجت العمال
    * **مصروف تشغيلي**   = مصروفات المشتريات التشغيلية خلال الشهر
    """
    from models.accounts import acc_id
    d1, d2 = _period_range(period)
    # ملخص **قسم التصنيع**: رواتب الإدارة ظاهرةٌ في جدول الرواتب لكنها
    # ليست من تكلفة القسم
    sal = [r for r in list_salaries(conn, period)
           if r.get("staff_kind", "worker") == "worker"]
    net = round(sum(float(r.get("net_salary") or 0) for r in sal), 2)
    target = round(sum(float(r.get("target_amount") or 0) for r in sal), 2)
    gold_loss_w = round(sum(float(r.get("gold_loss") or 0) for r in sal), 2)

    def _acc_move(code):
        """حركة حساب خلال الفترة: (نقد، ذهب)."""
        try:
            aid = acc_id(conn, code)
        except Exception:
            return 0.0, 0.0
        r = conn.execute(
            "SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) c,"
            " COALESCE(SUM(l.gold_debit-l.gold_credit),0) g"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0 AND l.account_id=?"
            " AND e.entry_date BETWEEN ? AND ?", (aid, d1, d2)).fetchone()
        return round(r["c"] or 0, 2), round(r["g"] or 0, 2)

    loss_c = loss_g = 0.0
    for code in MFG_LOSS_CODES:
        c, g = _acc_move(code)
        loss_c += c
        loss_g += g
    # + الفاقد المُدخل يدوياً في جدول الرواتب
    loss_g = round(loss_g + gold_loss_w, 2)
    loss_c = round(loss_c, 2)

    # المصروف التشغيلي: حركة حسابات المصروف وأبنائها خلال الشهر
    # (المشتريات التشغيلية تُرحَّل إلى 5500 وما يتفرّع عنه)
    exp_c = 0.0
    try:
        from models.reports import _subtree_ids
        ids = set()
        for code in MFG_EXPENSE_CODES:
            try:
                ids |= set(_subtree_ids(conn, code))
            except Exception:
                pass
        if ids:
            qs = ",".join("?" * len(ids))
            row = conn.execute(
                "SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
                " FROM journal_lines l"
                " JOIN journal_entries e ON e.id=l.entry_id"
                f" WHERE e.is_deleted=0 AND l.account_id IN ({qs})"
                " AND e.entry_date BETWEEN ? AND ?",
                list(ids) + [d1, d2]).fetchone()
            exp_c = round(row["c"] or 0, 2)
    except Exception:
        exp_c = 0.0

    # ══ صفوف الملخص القابلة للتخصيص ══
    # الصفوف الأساسية ثابتة، والمخفية منها والمضافة يحدّدها المستخدم
    # في `summary_config` — فكل مصنع يرى ما يعنيه.
    cfg = load_summary_config()
    hidden = set(cfg.get("hidden") or [])

    base = [
        ("salaries", "رواتب العمال", round(net - target, 2), 0.0),
        ("loss", "فاقد تشغيلي — قسم التصنيع", loss_c, loss_g),
        ("target", "التارجت", target, 0.0),
        ("expense", "مصروف تشغيلي", exp_c, 0.0),
    ]
    rows = [(t, c, g) for k, t, c, g in base if k not in hidden]

    # صفوف حسابات أضافها المستخدم من دليل الحسابات
    for extra in (cfg.get("accounts") or []):
        code = str(extra.get("code") or "").strip()
        if not code:
            continue
        try:
            from models.reports import _subtree_ids
            ids = list(_subtree_ids(conn, code))
        except Exception:
            ids = []
        c = g = 0.0
        if ids:
            qs = ",".join("?" * len(ids))
            r = conn.execute(
                "SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) c,"
                " COALESCE(SUM(l.gold_debit-l.gold_credit),0) g"
                " FROM journal_lines l"
                " JOIN journal_entries e ON e.id=l.entry_id"
                f" WHERE e.is_deleted=0 AND l.account_id IN ({qs})"
                " AND e.entry_date BETWEEN ? AND ?",
                ids + [d1, d2]).fetchone()
            c = round(r["c"] or 0, 2)
            g = round(r["g"] or 0, 2)
        rows.append((extra.get("name") or code, c, g))

    tot_c = round(sum(r[1] for r in rows), 2)
    tot_g = round(sum(r[2] for r in rows), 2)
    rows.append(("الإجمالي", tot_c, tot_g))
    return rows


# ══════════════════════════════════════════════════════════════════
# تخصيص صفوف الملخص
# ══════════════════════════════════════════════════════════════════

SUMMARY_KEYS = [("salaries", "رواتب العمال"),
                ("loss", "فاقد تشغيلي — قسم التصنيع"),
                ("target", "التارجت"),
                ("expense", "مصروف تشغيلي")]


def _summary_cfg_path():
    from pathlib import Path

    import config
    d = Path(str(config.DB_PATH)).parent
    d.mkdir(parents=True, exist_ok=True)
    return d / "mfg_summary.json"


def load_summary_config():
    """إعدادات الملخص: الصفوف المخفية والحسابات المضافة."""
    import json
    try:
        p = _summary_cfg_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {"hidden": list(d.get("hidden") or []),
                        "accounts": list(d.get("accounts") or [])}
    except Exception:
        pass
    return {"hidden": [], "accounts": []}


def save_summary_config(cfg):
    import json
    try:
        _summary_cfg_path().write_text(
            json.dumps({"hidden": list(cfg.get("hidden") or []),
                        "accounts": list(cfg.get("accounts") or [])},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        return True
    except Exception:
        return False
