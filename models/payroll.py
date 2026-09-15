# -*- coding: utf-8 -*-
"""دورة الرواتب على أساس الاستحقاق (Accrual Basis).

المبدأ: دائنية الموظف تثبت **فور اعتماد مسير الرواتب** وقبل الصرف
الفعلي، فيظهر الراتب في كشف حساب الموظف كرصيد دائن (له):

    قيد الاستحقاق:  من حـ/ مصروف الرواتب والأجور        (مدين)
                    إلى حـ/ مستحقات الموظف — [الاسم]    (دائن)

    سند صرف الراتب: من حـ/ مستحقات الموظف — [الاسم]     (مدين بالإجمالي)
                    إلى حـ/ سلف الموظف — [الاسم]        (دائن بالمخصوم)
                    إلى حـ/ الصندوق أو البنك             (دائن بالصافي)

فيتعادل حساب مستحقات الموظف إلى صفر بعد الصرف."""
from models.accounts import acc_id
from services.accounting_engine import balance_by_code, post_entry
import calendar
import datetime as _dt

from services.audit import log_action

SALARY_EXP = "5700"   # مصروف الرواتب والأجور
ACCRUED = "2200"      # مستحقات الموظفين — الحساب الأب (خصوم متداولة)
ADVANCES = "1950"     # سلف الموظفين (الحساب الأب — أصول متداولة)


def advance_account_id(conn, employee_id):
    """حساب سلف الموظف: الحساب الفرعي المخصص له إن كان مُكوَّداً في دليل
    جهات التعامل، وإلا الحساب الأب العام (توافق رجعي للموظفين القدامى)."""
    row = conn.execute(
        "SELECT account_id FROM entities WHERE employee_id=? AND is_deleted=0",
        (employee_id,)).fetchone()
    return row["account_id"] if row else acc_id(conn, ADVANCES)


def accrued_account_id(conn, employee_id):
    """حساب مستحقات الموظف الشخصي (الطرف الدائن لقيد الاستحقاق).

    يقع تحت 2200 «مستحقات الموظفين». إن كان الموظف قديماً بلا حساب
    مستحقات يُنشأ له آلياً الآن حتى لا يفشل قيد الاستحقاق."""
    row = conn.execute(
        "SELECT id, name, capital_account_id FROM entities"
        " WHERE employee_id=? AND is_deleted=0", (employee_id,)).fetchone()
    if row and row["capital_account_id"]:
        return row["capital_account_id"]
    if row:
        from models.entities import _create_sub_account
        acc = _create_sub_account(conn, ACCRUED,
                                  f"مستحقات الموظف: {row['name']}",
                                  "liability", "cash")
        conn.execute("UPDATE entities SET capital_account_id=? WHERE id=?",
                     (acc, row["id"]))
        return acc
    return acc_id(conn, ACCRUED)      # موظف غير مُكوَّد — الحساب الأب


def add_employee(conn, name, salary, username):
    if not name.strip():
        raise ValueError("أدخل اسم الموظف")
    if salary <= 0:
        raise ValueError("أدخل الراتب الأساسي")
    cur = conn.execute(
        "INSERT INTO employees(name,basic_salary,created_by)"
        " VALUES(?,?,?)", (name.strip(), salary, username))
    log_action(conn, username, "create", "employees", cur.lastrowid, name)
    return cur.lastrowid


def list_workers(conn, active_only=True):
    """عمال قسم التصنيع فقط — منفصلون عن الموظفين الإداريين."""
    return list_employees(conn, active_only=active_only, kind="worker")


def list_employees(conn, active_only=False, kind=None):
    """الموظفون النشطون مع مسمّاهم الوظيفي وحسابهم الشخصي.

    المسمى الوظيفي وحساب الموظف مخزَّنان في جدول الجهات (entities)،
    فيُضمّان هنا ليُستخدما مباشرةً في شاشة إنزال الرواتب.
    """
    q = ("SELECT e.*, en.job_title AS job_title,"
         " en.id AS entity_id, en.account_id AS account_id"
         " FROM employees e"
         " LEFT JOIN entities en ON en.employee_id=e.id AND en.is_deleted=0"
         " WHERE e.is_deleted=0")
    if active_only:
        q += " AND e.is_active=1"
    params = []
    if kind:
        # `staff_kind` يفصل عمال التصنيع عن الموظفين الإداريين
        q += " AND COALESCE(e.staff_kind,'employee')=?"
        params.append(kind)
    elif kind is None:
        pass
    return conn.execute(q + " ORDER BY e.name", params).fetchall()


def advance_outstanding(conn, employee_id):
    """السلف القائمة = ما صُرف من سلف − ما خُصم منها عند صرف الرواتب."""
    r = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='advance' THEN amount ELSE 0 END),0)"
        " - COALESCE(SUM(CASE WHEN kind='payment' THEN advance_deducted"
        " ELSE 0 END),0) v"
        " FROM payroll_ledger WHERE employee_id=? AND is_deleted=0",
        (employee_id,)).fetchone()
    return round(r["v"], 2)


def give_advance(conn, employee_id, amount, pay_code, adv_date, username,
                 notes=""):
    emp = conn.execute("SELECT * FROM employees WHERE id=? AND is_deleted=0",
                       (employee_id,)).fetchone()
    if not emp:
        raise ValueError("اختر الموظف")
    if amount <= 0:
        raise ValueError("أدخل مبلغ السلفة")
    entry_id = post_entry(
        conn, adv_date, f"سلفة نقدية للموظف {emp['name']}",
        [{"account_id": advance_account_id(conn, employee_id),
          "cash_debit": amount, "line_desc": f"سلفة — {emp['name']}"},
         {"account_id": acc_id(conn, pay_code), "cash_credit": amount}],
        source_table="payroll_ledger", username=username, note=notes)
    cur = conn.execute(
        "INSERT INTO payroll_ledger(employee_id,period,kind,amount,entry_id,"
        "notes,created_by) VALUES(?,?,?,?,?,?,?)",
        (employee_id, adv_date[:7], "advance", amount, entry_id, notes,
         username))
    log_action(conn, username, "create", "payroll_ledger", cur.lastrowid,
               f"advance {amount}")
    return {"entry_id": entry_id,
            "outstanding": advance_outstanding(conn, employee_id)}


def _check_period(period):
    if len(period) != 7 or period[4] != "-":
        raise ValueError("صيغة الفترة يجب أن تكون YYYY-MM")


def run_accrual(conn, period, username, entry_date=None):
    """اعتماد مسير رواتب الشهر (توحيد كشف حساب الموظف كحساب جاري).

    القيد: مدين مصروف الرواتب والأجور (5700) / دائن حساب الموظف الجاري
    (1950) مباشرة — نفس الحساب الذي تُسجَّل فيه السلف، وبلا أي مساس
    بالصندوق. بهذا يُظهر كشف حساب الموظف الواحد السلف مديناً والراتب
    المستحق دائناً، والرصيد الختامي هو صافي ما له أو ما عليه."""
    _check_period(period)
    due = []
    for e in list_employees(conn, active_only=True, kind="employee"):
        if e["basic_salary"] <= 0:
            continue
        exists = conn.execute(
            "SELECT 1 FROM payroll_ledger WHERE employee_id=? AND period=?"
            " AND kind='accrual' AND is_deleted=0", (e["id"], period)).fetchone()
        if not exists:
            due.append(e)
    if not due:
        return []
    lines = []
    for e in due:
        s = round(e["basic_salary"], 2)
        lines.append({"account_id": acc_id(conn, SALARY_EXP), "cash_debit": s,
                      "line_desc": f"استحقاق راتب شهر {period} - {e['name']}"})
        lines.append({"account_id": advance_account_id(conn, e["id"]),
                      "cash_credit": s,
                      "line_desc":
                          f"استحقاق راتب شهر {period} - {e['name']}"})
    # **التاريخ الفعلي للإجراء** (اليوم افتراضياً) لا آخر الشهر — فينزل
    # القيد طبيعياً كآخر حركة في كشف الحساب ولا يُحسب ضمن الرصيد السابق.
    accrual_date = entry_date or _dt.date.today().isoformat()
    entry_id = post_entry(conn, accrual_date,
                          f"قيد استحقاق رواتب شهر {period}", lines,
                          source_table="payroll_ledger", username=username)
    out = []
    for e in due:
        conn.execute(
            "INSERT INTO payroll_ledger(employee_id,period,kind,amount,"
            "entry_id,created_by) VALUES(?,?,?,?,?,?)",
            (e["id"], period, "accrual", round(e["basic_salary"], 2),
             entry_id, username))
        out.append((e["name"], round(e["basic_salary"], 2)))
    log_action(conn, username, "create", "payroll_ledger", entry_id,
               f"accrual {period}")
    return out


def pay_salaries(conn, period, pay_code, pay_date, username):
    """صرف رواتب الفترة من حساب الموظف الجاري الموحّد (1950).

    الاستحقاق سبق أن قيّد الراتب دائناً في حساب الموظف، والسلف مقيَّدة
    فيه مدينة. الصرف يُخرج النقد ويُقفل الدائنية بتقييد المدين بالصافي
    (الراتب ناقص السلف القائمة)، فيعود رصيد الموظف إلى صفر إن لم تكن
    له مستحقات أخرى، وتُخصم السلف ضمناً لأنها في الحساب نفسه:

        من حـ/ الموظف الجاري (1950)   مدين بالصافي
            إلى حـ/ الصندوق أو البنك   دائن بالمبلغ المدفوع
    """
    _check_period(period)
    accr = conn.execute(
        "SELECT p.*, e.name FROM payroll_ledger p"
        " JOIN employees e ON e.id=p.employee_id"
        " WHERE p.period=? AND p.kind='accrual' AND p.is_deleted=0"
        " ORDER BY e.name", (period,)).fetchall()
    due = [r for r in accr if not conn.execute(
        "SELECT 1 FROM payroll_ledger WHERE employee_id=? AND period=?"
        " AND kind='payment' AND is_deleted=0",
        (r["employee_id"], period)).fetchone()]
    if not due:
        raise ValueError("لا توجد مستحقات غير مصروفة لهذه الفترة — "
                         "نفّذ قيد الاستحقاق أولاً")
    lines, results, cash_total = [], [], 0.0
    for r in due:
        gross = round(r["amount"], 2)
        # السلف مقيَّدة في نفس الحساب الجاري، فالصافي المدفوع = الراتب
        # ناقص السلف القائمة، والخصم يتم ضمناً بتقييد المدين بالصافي.
        ded = round(min(advance_outstanding(conn, r["employee_id"]), gross), 2)
        net = round(gross - ded, 2)
        lines.append({"account_id": advance_account_id(conn, r["employee_id"]),
                      "cash_debit": net,
                      "line_desc": f"صرف صافي راتب {period} — {r['name']}"})
        cash_total = round(cash_total + net, 2)
        results.append((r["employee_id"], r["name"], gross, ded, net))
    if cash_total:
        lines.append({"account_id": acc_id(conn, pay_code),
                      "cash_credit": cash_total,
                      "line_desc": "صافي الرواتب المدفوعة"})
    entry_id = post_entry(conn, pay_date, f"صرف رواتب شهر {period}", lines,
                          source_table="payroll_ledger", username=username)
    for emp_id, name, gross, ded, net in results:
        conn.execute(
            "INSERT INTO payroll_ledger(employee_id,period,kind,amount,"
            "advance_deducted,entry_id,created_by) VALUES(?,?,?,?,?,?,?)",
            (emp_id, period, "payment", gross, ded, entry_id, username))
    log_action(conn, username, "create", "payroll_ledger", entry_id,
               f"payment {period}")
    return {"entry_id": entry_id,
            "rows": [(n, g, d, net) for _, n, g, d, net in results]}


def ledger_recent(conn, limit=40):
    return conn.execute(
        "SELECT p.*, e.name emp_name FROM payroll_ledger p"
        " JOIN employees e ON e.id=p.employee_id"
        " WHERE p.is_deleted=0 ORDER BY p.id DESC LIMIT ?", (limit,)).fetchall()


def search_ledger(conn, q="", date_from=None, date_to=None, limit=300):
    sql = ("SELECT p.*, e.name emp_name FROM payroll_ledger p"
          " JOIN employees e ON e.id=p.employee_id WHERE p.is_deleted=0")
    params = []
    if q:
        sql += " AND (e.name LIKE ? OR p.period LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND p.period>=?"; params.append(date_from[:7])
    if date_to:
        sql += " AND p.period<=?"; params.append(date_to[:7])
    sql += " ORDER BY p.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


def accrued_outstanding(conn, employee_id):
    """صافي مستحقات الموظف من حسابه الجاري الموحّد (1950).

    الرصيد المدين موجب (سلف عليه)؛ فإذا فاق الاستحقاق السلف صار الرصيد
    دائناً = مستحق له. تُعيد الدالة قيمة موجبة عند وجود مستحق غير
    مصروف، وصفراً إذا كان الموظف مديناً (عليه سلف)."""
    from services.accounting_engine import account_balance
    acc = advance_account_id(conn, employee_id)
    bal = account_balance(conn, acc)[1]      # موجب = مدين (سلف)
    return round(-bal, 2) if bal < 0 else 0.0


def payroll_balances(conn):
    """إجماليات الشاشة من الحساب الجاري الموحّد لكل موظف:
    المستحق (ما للموظفين) والسلف (ما عليهم) يُجمَّعان صافيَين."""
    accrued = advances = 0.0
    for e in list_employees(conn):
        accrued = round(accrued + accrued_outstanding(conn, e["id"]), 2)
        advances = round(advances + advance_outstanding(conn, e["id"]), 2)
    # أي رصيد تاريخي على حساب المستحقات القديم (2200) قبل التوحيد
    accrued = round(accrued - balance_by_code(conn, ACCRUED)[1], 2)
    return {"expense": balance_by_code(conn, SALARY_EXP)[1],
            "accrued": accrued, "advances": advances}
