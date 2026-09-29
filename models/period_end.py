# -*- coding: utf-8 -*-
"""تسويات نهاية الفترة — ما تطلبه القوائم المالية النظامية قبل رفعها.

أربع تسويات، كلٌّ منها **يُحسب ثم يُقيَّد بالفرق** عن المقيَّد سابقاً
(لا يُقيَّد مرتين، ويُعاد حسابه متى تغيّرت البيانات):

1. **الزكاة** — الوعاء الزكوي بطريقة المصادر والاستخدامات المعتمدة لدى
   هيئة الزكاة والضريبة والجمارك للمكلّفين الممسكين دفاتر: حقوق الملكية
   والمخصصات أول المدة والمطلوبات طويلة الأجل وصافي الربح المعدّل،
   يُحسم منها صافي الأصول غير المتداولة؛ ولا يقلّ الوعاء عن صافي الربح
   المعدّل. النسبة 2.5% للسنة الهجرية، ولسنةٍ ميلادية 2.5% × أيامها ÷ 354.
   القيد: مدين الزكاة (5950) / دائن مخصص الزكاة (2400).
2. **مكافأة نهاية الخدمة** (IAS 19 · نظام العمل م84): نصف أجر شهر عن
   كل سنة من السنوات الخمس الأولى، وأجر شهرٍ كامل عمّا بعدها، بآخر أجر.
   القيد: مدين 5870 / دائن مخصص نهاية الخدمة (2600 — غير متداول).
3. **الخسائر الائتمانية المتوقعة** (IFRS 9 — المنهج المبسّط بمصفوفة
   المخصص): نسبةٌ لكل فئة عمرية من ذمم العملاء النقدية.
   القيد: مدين 5880 / دائن مخصص الخسائر (1680 — يُطرح من الذمم).
4. **المصروفات المقدمة والمستحقة**: جدول إطفاء لما دُفع عن فتراتٍ قادمة
   (1980)، وقيد استحقاق لما استُهلك ولم تصل فاتورته (2280).

كل القيود بمصدرٍ صريح (`source_table`) فتُقرأ في سجل التدقيق، وتمرّ
بقفل الفترات كأي قيد.
"""
import datetime as _dt
import json

from models.accounts import acc_id
from services.accounting_engine import post_entry
from services.audit import log_action

ZAKAT_RATE_HIJRI = 0.025
HIJRI_DAYS = 354
ECL_KEY = "ecl_rates"
ECL_DEFAULT = [0.5, 2.0, 5.0, 25.0]          # % لكل فئة عمرية
EPS = 0.005


# ══════════════════════════════════════════════════════════════════
#  المخطط
# ══════════════════════════════════════════════════════════════════

def ensure_schema(conn):
    """أعمدة الموظفين وجدول المصروفات المقدمة — تُضاف مرةً بلا فقد."""
    try:
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(employees)")}
    except Exception:
        cols = set()
    if cols:
        for col, ddl in (("hire_date", "TEXT"), ("eos_wage", "REAL"),
                         ("end_date", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE employees ADD COLUMN {col} {ddl}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS prepaid_items("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL,"
        " expense_account_id INTEGER NOT NULL REFERENCES accounts(id),"
        " amount REAL NOT NULL,"
        " start_date TEXT NOT NULL,"
        " months INTEGER NOT NULL,"
        " mode TEXT NOT NULL DEFAULT 'reclass',"
        " entry_id INTEGER,"
        " is_deleted INTEGER NOT NULL DEFAULT 0,"
        " created_by TEXT,"
        " created_at TEXT DEFAULT (datetime('now','localtime')))")


def _d(s):
    return _dt.date.fromisoformat(str(s)[:10])


def _bal(conn, code, as_of, d1=None):
    """رصيد حساب وشجرته (مدين − دائن، نقداً) حتى تاريخ — أو حركته بين
    تاريخين. قيد الإقفال السنوي يُستبعد من الحركة."""
    from models.accounts import subtree_ids
    root = conn.execute("SELECT id FROM accounts WHERE code=?",
                        (code,)).fetchone()
    if not root:
        return 0.0
    ids = subtree_ids(conn, root["id"]) or [root["id"]]
    ph = ",".join("?" * len(ids))
    q = ("SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) b"
         " FROM journal_lines l JOIN journal_entries e"
         " ON e.id=l.entry_id AND e.is_deleted=0"
         f" WHERE l.account_id IN ({ph}) AND e.entry_date<=?")
    p = list(ids) + [as_of]
    if d1:
        q += (" AND e.entry_date>=?"
              " AND COALESCE(e.source_table,'')<>'year_close'")
        p.append(d1)
    return conn.execute(q, p).fetchone()["b"] or 0.0


def _post_diff(conn, date, desc, dr_code, cr_code, amount, source,
               username, note=""):
    """قيد الفرق: موجبٌ مدين/دائن كما هو، وسالبٌ معكوس. يُعيد رقم القيد."""
    amount = round(amount, 2)
    if abs(amount) < EPS:
        return None
    a, b = (dr_code, cr_code) if amount > 0 else (cr_code, dr_code)
    amt = abs(amount)
    eid = post_entry(conn, date, desc, [
        {"account_id": acc_id(conn, a), "cash_debit": amt,
         "line_desc": desc},
        {"account_id": acc_id(conn, b), "cash_credit": amt,
         "line_desc": desc}], source_table=source, username=username,
        note=note)
    log_action(conn, username, "create", "journal_entries", eid,
               f"{source}: {desc} = {amount:,.2f}")
    return eid


# ══════════════════════════════════════════════════════════════════
#  1) الزكاة
# ══════════════════════════════════════════════════════════════════

def zakat_rate(d1, d2):
    """2.5% للسنة الهجرية، وللفترة الميلادية بنسبة أيامها إلى 354."""
    days = (_d(d2) - _d(d1)).days + 1
    return ZAKAT_RATE_HIJRI * days / HIJRI_DAYS


def zakat_compute(conn, d1, d2, extra_add=0.0, extra_ded=0.0):
    """الوعاء الزكوي ومقدار الزكاة للفترة — تفصيلٌ بنداً بنداً.

    يُعيد: additions، deductions (قوائم (بيان، مبلغ))، adjusted_profit،
    base، base_floor (هل رُفع الوعاء إلى صافي الربح المعدّل)، rate،
    zakat، booked (المقيَّد في الفترة)، due (الفرق المطلوب قيده).
    """
    from models import statements as st
    before = st._day_before(d1)
    fp_open = st.financial_position(conn, before, "")["cash"]["values"]
    fp_close = st.financial_position(conn, d2, "")["cash"]["values"]
    inc = st.income_statement(conn, d1, d2, False)["cash"]
    before_zakat = inc["totals"]["before_zakat"]
    # المخصصات المحمّلة على الربح تُردّ إليه — لا تُحسم زكوياً
    prov_exp = -(inc["values"].get("ecl_exp", 0.0)) + (
        _bal(conn, "5870", d2, d1))
    adjusted = round(before_zakat + prov_exp, 2)

    additions = [
        ("رأس المال (آخر الفترة)", fp_close["capital"]),
        ("الاحتياطيات", fp_close.get("reserve", 0.0)),
        ("جاري الشركاء الدائن (آخر الفترة)", max(fp_close["partners"], 0.0)),
        ("الأرباح المبقاة / الخسائر المتراكمة أول الفترة",
         fp_open["retained"] + fp_open["profit"]),
        ("حساب تسوية الأرصدة الافتتاحية", fp_close["opening_susp"]),
        ("حقوق ملكية أخرى", fp_close["eq_other"]),
        ("مخصص مكافأة نهاية الخدمة أول الفترة", fp_open["eosb"]),
        ("قروض ومطلوبات طويلة الأجل",
         fp_close["ncl_other"] + fp_close.get("loans_lt", 0.0)),
        ("صافي الربح المعدّل للفترة", adjusted),
    ]
    if abs(extra_add) >= EPS:
        additions.append(("إضافات أخرى (يدوية)", float(extra_add)))
    deductions = [
        ("صافي الممتلكات والآلات والمعدات",
         fp_close["ppe_cost"] + fp_close["ppe_dep"]),
        ("أصول غير متداولة أخرى", fp_close["nca_other"]),
    ]
    if abs(extra_ded) >= EPS:
        deductions.append(("حسميات أخرى (يدوية)", float(extra_ded)))
    base = round(sum(v for _l, v in additions)
                 - sum(v for _l, v in deductions), 2)
    floor = False
    if adjusted > 0 and base < adjusted:
        base, floor = adjusted, True
    rate = zakat_rate(d1, d2)
    zakat = round(max(base, 0.0) * rate, 2)
    booked = round(_bal(conn, "5950", d2, d1), 2)
    return {"d1": d1, "d2": d2,
            "additions": [(l, round(v, 2)) for l, v in additions],
            "deductions": [(l, round(v, 2)) for l, v in deductions],
            "adjusted_profit": adjusted, "base": base, "base_floor": floor,
            "rate": rate, "zakat": zakat, "booked": booked,
            "due": round(zakat - booked, 2)}


def zakat_post(conn, d1, d2, username, extra_add=0.0, extra_ded=0.0):
    """يقيّد الفرق بين الزكاة المحسوبة والمقيَّدة في الفترة."""
    z = zakat_compute(conn, d1, d2, extra_add, extra_ded)
    eid = _post_diff(conn, d2, f"مخصص الزكاة للفترة {d1} — {d2}",
                     "5950", "2400", z["due"], "zakat", username,
                     note=f"زكاة الفترة {d1} — {d2}")
    from models.fiscal import set_setting
    set_setting(conn, f"zakat_calc:{d1}:{d2}",
                json.dumps(z, ensure_ascii=False), username)
    z["entry_id"] = eid
    return z


def zakat_saved(conn, d1, d2):
    """آخر حسابٍ مقيَّد للفترة — للإيضاحات."""
    from models.fiscal import get_setting
    raw = get_setting(conn, f"zakat_calc:{d1}:{d2}", "")
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  2) مكافأة نهاية الخدمة
# ══════════════════════════════════════════════════════════════════

def eos_award(wage, years):
    """المادة 84: نصف شهر عن كل سنة من الخمس الأولى، وشهرٌ عمّا بعدها."""
    years = max(float(years or 0.0), 0.0)
    wage = max(float(wage or 0.0), 0.0)
    return round(wage / 2.0 * min(years, 5.0)
                 + wage * max(years - 5.0, 0.0), 2)


def eos_list(conn, as_of):
    """الموظفون والعمال بمدة خدمتهم ومكافأتهم المستحقة في تاريخ."""
    ensure_schema(conn)
    out = []
    for r in conn.execute(
            "SELECT id, name, staff_kind, basic_salary, hire_date, eos_wage,"
            " end_date, is_active FROM employees WHERE is_deleted=0"
            " ORDER BY name"):
        wage = r["eos_wage"] if r["eos_wage"] not in (None, "") \
            else r["basic_salary"]
        hired = (r["hire_date"] or "").strip()
        left = (r["end_date"] or "").strip()
        years = 0.0
        counted = bool(hired) and hired <= as_of and not (left and
                                                          left <= as_of)
        if counted:
            years = ((_d(as_of) - _d(hired)).days + 1) / 365.0
        out.append({"id": r["id"], "name": r["name"],
                    "kind": r["staff_kind"] or "employee",
                    "hire_date": hired, "end_date": left,
                    "wage": round(float(wage or 0.0), 2),
                    "years": round(years, 2), "counted": counted,
                    "award": eos_award(wage, years) if counted else 0.0})
    return out


def eos_update(conn, emp_id, hire_date, wage, end_date, username):
    ensure_schema(conn)
    for v in (hire_date, end_date):
        if v:
            _d(v)                      # يرفع خطأً لتاريخٍ غير صالح
    conn.execute("UPDATE employees SET hire_date=?, eos_wage=?, end_date=?"
                 " WHERE id=?", (hire_date or None,
                                 None if wage in (None, "") else float(wage),
                                 end_date or None, emp_id))
    log_action(conn, username, "update", "employees", emp_id,
               f"eos: hire={hire_date} wage={wage} end={end_date}")


def eos_compute(conn, as_of):
    rows = eos_list(conn, as_of)
    required = round(sum(r["award"] for r in rows), 2)
    current = round(-_bal(conn, "2600", as_of), 2)
    missing = [r["name"] for r in rows if not r["hire_date"]]
    return {"as_of": as_of, "rows": rows, "required": required,
            "current": current, "due": round(required - current, 2),
            "missing_hire": missing}


def eos_post(conn, as_of, username):
    c = eos_compute(conn, as_of)
    c["entry_id"] = _post_diff(
        conn, as_of, f"تسوية مخصص مكافأة نهاية الخدمة حتى {as_of}",
        "5870", "2600", c["due"], "eosb", username,
        note=f"مكافأة نهاية الخدمة حتى {as_of}")
    return c


# ══════════════════════════════════════════════════════════════════
#  3) الخسائر الائتمانية المتوقعة
# ══════════════════════════════════════════════════════════════════

def ecl_rates(conn):
    from models.fiscal import get_setting
    try:
        v = json.loads(get_setting(conn, ECL_KEY, "") or "null")
        if isinstance(v, list) and len(v) == 4:
            return [float(x) for x in v]
    except Exception:
        pass
    return list(ECL_DEFAULT)


def ecl_set_rates(conn, rates, username):
    rates = [float(x) for x in rates]
    if len(rates) != 4 or any(r < 0 or r > 100 for r in rates):
        raise ValueError("النسب أربعٌ بين 0 و100")
    from models.fiscal import set_setting
    set_setting(conn, ECL_KEY, json.dumps(rates), username)
    return rates


def ecl_compute(conn, as_of, rates=None):
    """مصفوفة المخصص: رصيد كل فئة عمرية من ذمم العملاء النقدية × نسبتها."""
    from models import aging
    rates = rates or ecl_rates(conn)
    rows = aging.report(conn, "customer", as_of)
    buckets = aging.totals(rows)["cash_buckets"] if rows else [0.0] * 4
    lines = []
    for label, bal, pct in zip(aging.BUCKET_LABELS, buckets, rates):
        lines.append({"label": label, "balance": round(bal, 2),
                      "rate": pct, "allowance": round(bal * pct / 100.0, 2)})
    required = round(sum(x["allowance"] for x in lines), 2)
    current = round(-_bal(conn, "1680", as_of), 2)
    return {"as_of": as_of, "lines": lines, "rates": rates,
            "required": required, "current": current,
            "due": round(required - current, 2)}


def ecl_post(conn, as_of, username, rates=None):
    c = ecl_compute(conn, as_of, rates)
    c["entry_id"] = _post_diff(
        conn, as_of, f"تسوية مخصص الخسائر الائتمانية المتوقعة حتى {as_of}",
        "5880", "1680", c["due"], "ecl", username,
        note=f"مخصص الديون المشكوك فيها حتى {as_of}")
    return c


# ══════════════════════════════════════════════════════════════════
#  4) المصروفات المقدمة والمستحقة
# ══════════════════════════════════════════════════════════════════

def _add_months(d, months):
    y, m = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    import calendar
    day = min(d.day, calendar.monthrange(y, m)[1])
    return _dt.date(y, m, day)


def prepaid_add(conn, name, expense_code, amount, start_date, months,
                username, mode="reclass", cash_code="1400"):
    """يسجّل مصروفاً مدفوعاً مقدماً.

    * `reclass`: دُفع وقُيِّد مصروفاً ⇒ يُنقل كامله إلى «مدفوعة مقدماً»
      ثم يُطفأ على مدته.
    * `paid`: يُدفع الآن من الصندوق/البنك إلى «مدفوعة مقدماً» مباشرة.
    """
    ensure_schema(conn)
    amount = round(float(amount), 2)
    months = int(months)
    if amount <= 0 or months <= 0:
        raise ValueError("المبلغ وعدد الأشهر يجب أن يكونا موجبين")
    _d(start_date)
    exp_id = acc_id(conn, expense_code)
    cur = conn.execute(
        "INSERT INTO prepaid_items(name, expense_account_id, amount,"
        " start_date, months, mode, created_by) VALUES(?,?,?,?,?,?,?)",
        (name.strip(), exp_id, amount, start_date, months, mode, username))
    pid = cur.lastrowid
    credit = expense_code if mode == "reclass" else cash_code
    desc = f"مصروف مدفوع مقدماً: {name}"
    eid = post_entry(conn, start_date, desc, [
        {"account_id": acc_id(conn, "1980"), "cash_debit": amount,
         "line_desc": desc},
        {"account_id": acc_id(conn, credit), "cash_credit": amount,
         "line_desc": desc}], source_table="prepaid", source_id=pid,
        username=username, note=desc)
    conn.execute("UPDATE prepaid_items SET entry_id=? WHERE id=?", (eid, pid))
    log_action(conn, username, "create", "prepaid_items", pid,
               f"{name} {amount:,.2f} / {months}m")
    return pid


def _amortized(conn, pid):
    r = conn.execute(
        "SELECT COALESCE(SUM(l.cash_credit-l.cash_debit),0) a"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " AND e.is_deleted=0 JOIN accounts a ON a.id=l.account_id"
        " WHERE e.source_table='prepaid_amort' AND e.source_id=?"
        " AND a.code='1980'", (pid,)).fetchone()
    return round(r["a"] or 0.0, 2)


def prepaid_list(conn, as_of):
    ensure_schema(conn)
    out = []
    for r in conn.execute(
            "SELECT p.*, a.code exp_code, a.name exp_name FROM prepaid_items p"
            " JOIN accounts a ON a.id=p.expense_account_id"
            " WHERE p.is_deleted=0 ORDER BY p.start_date, p.id"):
        start = _d(r["start_date"])
        end = _add_months(start, r["months"])
        total_days = max((end - start).days, 1)
        used = min(max((_d(as_of) - start).days + 1, 0), total_days)
        should = round(r["amount"] * used / total_days, 2)
        done = _amortized(conn, r["id"])
        out.append({"id": r["id"], "name": r["name"],
                    "exp_code": r["exp_code"], "exp_name": r["exp_name"],
                    "amount": r["amount"], "start": r["start_date"],
                    "end": (end - _dt.timedelta(days=1)).isoformat(),
                    "months": r["months"], "should": should, "done": done,
                    "due": round(should - done, 2),
                    "remaining": round(r["amount"] - should, 2)})
    return out


def prepaid_amortize(conn, as_of, username):
    """يُطفئ ما استُهلك حتى التاريخ ولم يُقيَّد — قيدٌ لكل بند."""
    posted = []
    for it in prepaid_list(conn, as_of):
        if abs(it["due"]) < EPS:
            continue
        desc = f"إطفاء مصروف مقدم: {it['name']} حتى {as_of}"
        amt = it["due"]
        a, b = (it["exp_code"], "1980") if amt > 0 else ("1980",
                                                         it["exp_code"])
        eid = post_entry(conn, as_of, desc, [
            {"account_id": acc_id(conn, a), "cash_debit": abs(amt),
             "line_desc": desc},
            {"account_id": acc_id(conn, b), "cash_credit": abs(amt),
             "line_desc": desc}], source_table="prepaid_amort",
            source_id=it["id"], username=username, note=desc)
        posted.append((it["name"], amt, eid))
    return posted


def accrue_expense(conn, expense_code, amount, date, username, note="",
                   auto_reverse=True):
    """مصروفٌ استُهلك ولم تصل فاتورته: مدين المصروف / دائن «مستحقة».

    `auto_reverse`: يُعكس القيد أول يومٍ من الفترة التالية، فحين تصل
    الفاتورة وتُقيَّد كالمعتاد لا يُحمَّل المصروف مرتين.
    """
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون موجباً")
    desc = f"مصروف مستحق: {note or expense_code}"
    eid = post_entry(conn, date, desc, [
        {"account_id": acc_id(conn, expense_code), "cash_debit": amount,
         "line_desc": desc},
        {"account_id": acc_id(conn, "2280"), "cash_credit": amount,
         "line_desc": desc}], source_table="accrual", username=username,
        note=note or desc)
    rev = None
    if auto_reverse:
        nxt = (_d(date) + _dt.timedelta(days=1)).isoformat()
        rdesc = f"عكس استحقاق: {note or expense_code}"
        rev = post_entry(conn, nxt, rdesc, [
            {"account_id": acc_id(conn, "2280"), "cash_debit": amount,
             "line_desc": rdesc},
            {"account_id": acc_id(conn, expense_code), "cash_credit": amount,
             "line_desc": rdesc}], source_table="accrual_rev",
            source_id=eid, username=username, note=rdesc)
    log_action(conn, username, "create", "journal_entries", eid,
               f"accrual {expense_code} {amount:,.2f}")
    return eid, rev
