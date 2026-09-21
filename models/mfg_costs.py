# -*- coding: utf-8 -*-
"""تكاليف ورواتب قسم التصنيع.

**المنطق المحاسبي**: العمال جهات من نوع `employee` تماماً كالموظفين،
فلكلٍّ حسابه الشخصي في شجرة الحسابات. وقيد الرواتب مفصّل بسطرين لكل
عامل داخل سند واحد:

    مدين  حـ/ مصروف رواتب عمال التصنيع (5710)   بصافي راتبه
    دائن  حـ/ حساب العامل الشخصي                 بصافي راتبه

فيظهر في كشف المصروف سطرٌ باسم كل عامل، وفي كشف حساب العامل راتبه
دائناً مع سُلفه مدينةً والصافي آلياً.

**السحوبات** (نقدي/بنكي) تُجلب من سندات الصرف المسجّلة على حساب
العامل خلال الشهر، وتُعرض في عمودها ولا تُطرح من الصافي: السحب قُيّد
يوم وقوعه بسند صرف، فطرحُه من الصافي المُرحَّل يخصمه مرتين. الصافي
استحقاقُه كاملاً، ورصيدُ حسابه يطرح السحب من نفسه. وعمود «المستحق»
= الصافي − المسحوبات، للعرض والطباعة لا للترحيل.
"""
import calendar

from models.accounts import acc_id
from services.accounting_engine import post_entry
from services.audit import log_action

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
    from models import payroll
    rows = []
    for e in payroll.list_workers(conn):
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
    return {"overtime": overtime, "deduction": deduction,
            "net_salary": net, "draws": draws,
            "due": round(net - draws, 2)}


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


def _salary_people(conn):
    """عمال التصنيع، ومعهم من أُضيف يدوياً من الموظفين.

    الجدول لعمال التصنيع أصلاً، لكنّ الشهر قد يعمل فيه موظفٌ إداري
    مع القسم فيستحقّ تارجتاً أو مكافأةً معه. فبدل أن يُحوَّل نوعُه
    في الدليل — وهو تغييرٌ دائم لأجل شهر — يُضاف صفُّه هنا، ويُرفع
    متى شاء صاحب النظام.
    """
    from models import payroll
    people = list(payroll.list_workers(conn))
    have = {e["id"] for e in people}
    extra = [i for i in load_extra_staff() if i not in have]
    if extra:
        ph = ",".join("?" * len(extra))
        try:
            people += list(conn.execute(
                "SELECT e.*, en.job_title job_title, en.id entity_id,"
                " en.account_id account_id FROM employees e"
                " LEFT JOIN entities en ON en.employee_id=e.id"
                "   AND en.is_deleted=0"
                f" WHERE e.is_deleted=0 AND e.id IN ({ph})"
                " ORDER BY e.name", extra))
        except Exception:
            pass
    return people


def list_salaries(conn, period):
    """صفوف الرواتب مرتبطة ديناميكياً بالتارجت وسندات الصرف."""
    ensure_schema(conn)
    _extra_set = set(load_extra_staff())
    targets = {t["employee_id"]: t for t in list_targets(conn, period)}
    rows = []
    for e in _salary_people(conn):
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
            "is_posted": bool(saved["is_posted"]) if saved else False,
            # صفٌّ أُضيف يدوياً (موظفٌ من خارج عمال التصنيع)
            "is_extra": bool(e["id"] in _extra_set),
        }
        r.update(compute_salary_row(r))
        rows.append(r)
    return rows


def save_salaries(conn, period, rows, username):
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
    return n


# ══════════════════════════════════════════════════════════════════
# الترحيل المحاسبي
# ══════════════════════════════════════════════════════════════════

def post_salaries(conn, period, username, entry_date=None, rows=None):
    """يرحّل رواتب العمال بقيد واحد مفصّل بسطرين لكل عامل.

        مدين  5710 مصروف رواتب عمال التصنيع   بصافي الراتب
        دائن  حساب العامل الشخصي               بصافي الراتب

    البيان على الطرفين: «راتب عمال شهر YYYY-MM - اسم العامل» فيظهر
    في كشف المصروف سطرٌ باسم كل عامل لا «مذكورين».
    """
    import datetime as _dt
    ensure_schema(conn)
    rows = rows if rows is not None else list_salaries(conn, period)
    pending = [r for r in rows
               if float(r.get("net_salary") or 0) != 0
               and not r.get("is_posted")]
    if not pending:
        raise ValueError(
            f"لا توجد رواتب معلّقة لشهر {period} — ربما رُحّلت مسبقاً")

    date = entry_date or _dt.date.today().isoformat()
    exp_acc = acc_id(conn, WORKER_EXPENSE)
    lines, total = [], 0.0
    for r in pending:
        net = round(float(r["net_salary"]), 2)
        ent = conn.execute(
            "SELECT account_id FROM entities WHERE employee_id=?"
            " AND is_deleted=0", (r["employee_id"],)).fetchone()
        if not ent:
            raise ValueError(f"العامل «{r['name']}» بلا حساب في الشجرة")
        desc = f"راتب عمال شهر {period} - {r['name']}"
        lines.append({"account_id": exp_acc, "cash_debit": net,
                      "line_desc": desc})
        lines.append({"account_id": ent["account_id"], "cash_credit": net,
                      "line_desc": desc})
        total += net

    entry_id = post_entry(conn, date, f"رواتب عمال التصنيع {period}",
                          lines, source_table="mfg_salaries",
                          source_id=None, username=username)
    for r in pending:
        conn.execute(
            "UPDATE mfg_salaries SET is_posted=1, entry_id=?"
            " WHERE period=? AND employee_id=?",
            (entry_id, period, r["employee_id"]))
    log_action(conn, username, "create", "mfg_salaries", entry_id,
               f"ترحيل رواتب عمال {period}: {len(pending)} عامل"
               f" بإجمالي {total:,.2f}")
    return {"entry_id": entry_id, "count": len(pending),
            "total": round(total, 2)}


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
    sal = list_salaries(conn, period)
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
