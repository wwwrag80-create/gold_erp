# -*- coding: utf-8 -*-
"""دورة الصب والتصفية المرحلية (Melting & Refining Cycle).

عملية ممتدة زمنياً من ثلاث مراحل، محورها حساب وسيط هو
**حـ/ الصب والتصفية (1350)**، وكل الأوزان تُقيَّد فيه بـ**معادل عيار
18** باعتباره العيار التشغيلي الموحّد للمصنع:

    مكافئ عيار 18 = الوزن الفعلي × العيار ÷ 18

  (أ) سند صرف للصب — يخرج الكسر/الخام من صناديق العيارات إلى الصهر:
        من حـ/ الصب والتصفية        (مدين بإجمالي المكافئ 18)
        إلى حـ/ صندوق كسر عيار (س)   (دائن بمكافئ كل عيار)

  (ب) سند قبض مصفى — يدخل الناتج بعد التصفية بأي عيار:
        من حـ/ صندوق كسر عيار (س)    (مدين بمكافئ كل عيار)
        إلى حـ/ الصب والتصفية       (دائن بإجمالي المكافئ 18)

  (جـ) قيد إقفال الفاقد الفني — الرصيد المتبقي في حساب الصهر هو الفاقد:
        من حـ/ الفاقد الفني للصب     (مدين بالفرق بمعادل 18)
        إلى حـ/ الصب والتصفية       (دائن لتصفير الحساب)

ملاحظة: الفاقد الفني للصب **مستقل تماماً** عن فاقد التصنيع والخياس
(5110)، ولا يدخل ضمن لوحة فاقد الذهب في تقرير خزينة التصنيع.
"""
import config
from models.accounts import acc_id
from models.inventory import BOX_CODE, add_scrap_move
from services import gold_math
from services.accounting_engine import account_balance, post_entry
from services.audit import log_action

REFINING = "1350"        # حـ/ الصب والتصفية (الحساب الوسيط)
TECH_LOSS = "5120"       # حـ/ الفاقد الفني للصب
KARATS = (18, 21, 24)
KIND_LABELS = {"disbursement": "سند صرف للصب",
               "receipt": "سند قبض مصفى",
               "close": "قيد إقفال الفاقد الفني",
               "legacy": "عملية صهر (نسخة سابقة)"}


def _clean_lines(lines):
    """يتحقق من أسطر العيارات ويحسب مكافئ 18 لكل سطر."""
    out, total = [], 0.0
    for ln in lines or []:
        karat = int(ln.get("karat", 18))
        weight = round(float(ln.get("weight") or 0), 3)
        if karat not in KARATS:
            raise ValueError("العيار يجب أن يكون 18 أو 21 أو 24")
        if weight < 0:
            raise ValueError("الأوزان لا تقبل السالب")
        if weight == 0:
            continue
        eq = gold_math.to_base_karat(weight, karat)
        out.append({"karat": karat, "weight": weight, "equiv18": eq})
        total = round(total + eq, 3)
    if not out:
        raise ValueError("أدخل وزناً واحداً على الأقل")
    return out, total


def refining_balance(conn):
    """رصيد حساب الصب والتصفية بمعادل 18 (موجب = ذهب تحت التصفية)."""
    return round(account_balance(conn, acc_id(conn, REFINING))[0], 3)


def _insert_op(conn, kind, op_date, equiv18, notes, username, lines=None):
    cur = conn.execute(
        "INSERT INTO melting_ops(kind,op_date,equiv18,w18,w21,expected24,"
        "actual24,loss24,loss_ratio,exceeded,notes,created_by)"
        " VALUES(?,?,?,0,0,0,0,0,0,0,?,?)",
        (kind, op_date, equiv18, notes, username))
    op_id = cur.lastrowid
    for ln in (lines or []):
        conn.execute(
            "INSERT INTO melting_lines(op_id,karat,weight,equiv18)"
            " VALUES(?,?,?,?)",
            (op_id, ln["karat"], ln["weight"], ln["equiv18"]))
    return op_id


def create_disbursement(conn, lines, op_date, username, notes=""):
    """(أ) صرف كسر/خام من صناديق العيارات إلى حساب الصب والتصفية."""
    lines, total = _clean_lines(lines)
    jl = [{"account_id": acc_id(conn, REFINING), "gold_debit": total,
           "line_desc": f"صرف للصب — إجمالي {total:.2f} جم مكافئ 18"}]
    for ln in lines:
        jl.append({"account_id": acc_id(conn, BOX_CODE[ln["karat"]]),
                   "gold_credit": ln["equiv18"],
                   "line_desc": f"وزن فعلي {ln['weight']:.2f} جم عيار "
                                f"{ln['karat']}"})
    op_id = _insert_op(conn, "disbursement", op_date, total, notes, username,
                       lines)
    op_no = f"MD-{op_id:05d}"
    entry_id = post_entry(conn, op_date, f"سند صرف للصب {op_no}", jl,
                          source_table="melting_ops", source_id=op_id,
                          username=username, note=notes)
    conn.execute("UPDATE melting_ops SET op_no=?, entry_id=? WHERE id=?",
                 (op_no, entry_id, op_id))
    for ln in lines:
        add_scrap_move(conn, ln["karat"], -ln["weight"], "melting_ops", op_id)
    log_action(conn, username, "create", "melting_ops", op_id,
               f"disbursement {total}")
    return {"id": op_id, "op_no": op_no, "kind": "disbursement",
            "equiv18": total, "entry_id": entry_id,
            "refining_balance": refining_balance(conn)}


def create_receipt(conn, lines, op_date, username, notes=""):
    """(ب) قبض الذهب المصفّى بأي عيار وإدخاله صناديق العيارات."""
    lines, total = _clean_lines(lines)
    jl = []
    for ln in lines:
        jl.append({"account_id": acc_id(conn, BOX_CODE[ln["karat"]]),
                   "gold_debit": ln["equiv18"],
                   "line_desc": f"وزن فعلي {ln['weight']:.2f} جم عيار "
                                f"{ln['karat']}"})
    jl.append({"account_id": acc_id(conn, REFINING), "gold_credit": total,
               "line_desc": f"قبض مصفى — إجمالي {total:.2f} جم مكافئ 18"})
    op_id = _insert_op(conn, "receipt", op_date, total, notes, username, lines)
    op_no = f"MR-{op_id:05d}"
    entry_id = post_entry(conn, op_date, f"سند قبض مصفى {op_no}", jl,
                          source_table="melting_ops", source_id=op_id,
                          username=username, note=notes)
    conn.execute("UPDATE melting_ops SET op_no=?, entry_id=? WHERE id=?",
                 (op_no, entry_id, op_id))
    for ln in lines:
        add_scrap_move(conn, ln["karat"], ln["weight"], "melting_ops", op_id)
    log_action(conn, username, "create", "melting_ops", op_id,
               f"receipt {total}")
    return {"id": op_id, "op_no": op_no, "kind": "receipt",
            "equiv18": total, "entry_id": entry_id,
            "refining_balance": refining_balance(conn)}


def cycle_summary(conn, date_from=None, date_to=None):
    """ملخص الدورة: المصروف والمقبوض والفاقد القائم — كلها بمعادل 18."""
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='disbursement' THEN equiv18 END),0) d,"
        " COALESCE(SUM(CASE WHEN kind='receipt' THEN equiv18 END),0) r,"
        " COALESCE(SUM(CASE WHEN kind='close' THEN equiv18 END),0) c"
        " FROM melting_ops WHERE is_deleted=0"
        + (" AND op_date>=?" if date_from else "")
        + (" AND op_date<=?" if date_to else ""),
        [x for x in (date_from, date_to) if x]).fetchone()
    out = round(row["d"], 3)
    back = round(row["r"], 3)
    ratio = round((out - back) / out, 4) if out else 0.0
    return {"disbursed": out, "received": back,
            "outstanding": refining_balance(conn),
            "closed_loss": round(row["c"], 3), "loss_ratio": ratio,
            "exceeded": ratio > config.MELTING_LOSS_LIMIT}


def close_cycle(conn, op_date, username, notes=""):
    """(جـ) إقفال حساب الصهر وترحيل الفرق إلى الفاقد الفني للصب."""
    bal = refining_balance(conn)
    if abs(bal) < 0.001:
        raise ValueError("رصيد حساب الصب والتصفية صفر — لا يوجد فاقد للإقفال")
    summary = cycle_summary(conn)
    if bal > 0:
        jl = [{"account_id": acc_id(conn, TECH_LOSS), "gold_debit": bal,
               "line_desc": f"فاقد فني للصب ({summary['loss_ratio']*100:.2f}%)"},
              {"account_id": acc_id(conn, REFINING), "gold_credit": bal,
               "line_desc": "تصفير حساب الصب والتصفية"}]
    else:
        jl = [{"account_id": acc_id(conn, REFINING), "gold_debit": abs(bal),
               "line_desc": "تصفير حساب الصب والتصفية"},
              {"account_id": acc_id(conn, TECH_LOSS), "gold_credit": abs(bal),
               "line_desc": "زيادة عن المتوقع (فرق موجب)"}]
    op_id = _insert_op(conn, "close", op_date, bal, notes, username)
    op_no = f"MC-{op_id:05d}"
    entry_id = post_entry(conn, op_date,
                          f"إقفال الفاقد الفني للصب {op_no}", jl,
                          source_table="melting_ops", source_id=op_id,
                          username=username, note=notes)
    conn.execute("UPDATE melting_ops SET op_no=?, entry_id=? WHERE id=?",
                 (op_no, entry_id, op_id))
    log_action(conn, username, "create", "melting_ops", op_id,
               f"close {bal}")
    return {"id": op_id, "op_no": op_no, "kind": "close", "loss18": bal,
            "loss_ratio": summary["loss_ratio"],
            "exceeded": summary["exceeded"], "entry_id": entry_id,
            "refining_balance": refining_balance(conn)}


def op_lines(conn, op_id):
    return conn.execute(
        "SELECT * FROM melting_lines WHERE op_id=? ORDER BY karat",
        (op_id,)).fetchall()


def recent_melting(conn, limit=20):
    return conn.execute(
        "SELECT * FROM melting_ops WHERE is_deleted=0 ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def search_melting(conn, q="", date_from=None, date_to=None, limit=200):
    sql = "SELECT * FROM melting_ops WHERE is_deleted=0"
    params = []
    if q:
        sql += " AND op_no LIKE ?"; params.append(f"%{q}%")
    if date_from:
        sql += " AND op_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND op_date<=?"; params.append(date_to)
    sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()
