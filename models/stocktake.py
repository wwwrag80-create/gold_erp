# -*- coding: utf-8 -*-
"""الجرد الفعلي — وضعان مختلفان جذرياً:
1) جرد كتلي بالوزن (خزينة التصنيع وصناديق الكسر): يُقارن وزن الميزان
   الفعلي بالرصيد الدفتري ويولّد قيد التسوية (عجز أو زيادة) آلياً.
2) جرد تفصيلي بالباركود (الذهب المشغول): تُمرَّر أرقام التشغيل فعلياً
   وتُقارن بالمتاح في النظام — مطابق / عجز (مفقود) / زيادة (غير مسجَّل)."""
from models.accounts import acc_id
from services.accounting_engine import account_balance, post_entry
from services.audit import log_action

BULK_ACCOUNTS = {"1100": "5110", "1310": "5120"}
GAIN_ACC = "4300"   # أرباح فروقات الجرد والتسويات (إيراد)


def create_bulk_stocktake(conn, account_code, actual_weight, stocktake_date,
                          username, notes=""):
    """جرد وزني لخزينة التصنيع أو أحد صناديق الكسر."""
    if account_code not in BULK_ACCOUNTS:
        raise ValueError("الجرد الكتلي يخص خزينة التصنيع أو صناديق الكسر فقط")
    if actual_weight < 0:
        raise ValueError("الوزن الفعلي لا يقبل السالب")
    account_id = acc_id(conn, account_code)
    loss_code = BULK_ACCOUNTS[account_code]
    loss_id = acc_id(conn, loss_code)
    ledger = account_balance(conn, account_id)[0]
    diff = round(actual_weight - ledger, 3)  # + زيادة (النظام يقل عن الواقع) / − عجز

    entry_id = None
    if diff != 0:
        if diff < 0:  # عجز: الفعلي أقل من الدفتري
            lines = [{"account_id": loss_id, "gold_debit": abs(diff),
                      "line_desc": f"عجز جرد — دفتري {ledger:.2f} فعلي {actual_weight:.2f}"},
                     {"account_id": account_id, "gold_credit": abs(diff)}]
        else:  # زيادة: الفعلي أكبر من الدفتري → إيراد أرباح فروقات الجرد
            lines = [{"account_id": account_id, "gold_debit": diff,
                      "line_desc": f"زيادة جرد — دفتري {ledger:.2f} فعلي {actual_weight:.2f}"},
                     {"account_id": acc_id(conn, GAIN_ACC), "gold_credit": diff}]
        entry_id = post_entry(
            conn, stocktake_date,
            f"تسوية جرد فعلي — حساب {account_code} ({'عجز' if diff < 0 else 'زيادة'})",
            lines, source_table="stocktakes", username=username)

    cur = conn.execute(
        "INSERT INTO stocktakes(mode,account_id,stocktake_date,ledger_value,"
        "actual_value,diff,entry_id,notes,created_by) VALUES('bulk',?,?,?,?,?,?,?,?)",
        (account_id, stocktake_date, ledger, actual_weight, diff, entry_id,
         notes, username))
    st_id = cur.lastrowid
    st_no = f"ST-{st_id:05d}"
    conn.execute("UPDATE stocktakes SET stocktake_no=? WHERE id=?", (st_no, st_id))
    if entry_id:
        conn.execute("UPDATE journal_entries SET source_id=? WHERE id=?",
                     (st_id, entry_id))
    log_action(conn, username, "create", "stocktakes", st_id,
              f"{st_no} diff={diff}")
    return {"id": st_id, "stocktake_no": st_no, "ledger": ledger,
            "actual": actual_weight, "diff": diff, "entry_id": entry_id}


def create_itemized_reconcile(conn, scanned_numbers, stocktake_date, username,
                              notes=""):
    """جرد تفصيلي بالباركود للذهب المشغول: يقارن الأرقام الممسوحة فعلياً
    بالمتاح في النظام، ويولّد قيد عجز فقط للمفقود (الزيادة تُبلَّغ دون
    ترحيل آلي لعدم توفر بيانات موثوقة لوزنها/مصدرها)."""
    scanned = {s.strip() for s in scanned_numbers if s and s.strip()}
    system_rows = conn.execute(
        "SELECT id, work_order_no, registered_weight FROM work_orders"
        " WHERE is_deleted=0 AND status='in_stock'").fetchall()
    system = {r["work_order_no"]: r for r in system_rows}

    matched = sorted(scanned & system.keys())
    missing = sorted(system.keys() - scanned)
    excess = sorted(scanned - system.keys())

    missing_weight = round(sum(system[no]["registered_weight"] for no in missing), 3)
    matched_weight = round(sum(system[no]["registered_weight"] for no in matched), 3)
    ledger_weight = round(sum(r["registered_weight"] for r in system_rows), 3)

    entry_id = None
    if missing_weight > 0:
        entry_id = post_entry(
            conn, stocktake_date,
            f"عجز جرد الذهب المشغول — {len(missing)} طقم مفقود",
            [{"account_id": acc_id(conn, "5130"), "gold_debit": missing_weight,
              "line_desc": "عجز جرد بالباركود"},
             {"account_id": acc_id(conn, "1200"), "gold_credit": missing_weight}],
            source_table="stocktakes", username=username)

    cur = conn.execute(
        "INSERT INTO stocktakes(mode,account_id,stocktake_date,ledger_value,"
        "actual_value,diff,matched_count,missing_count,excess_count,entry_id,"
        "notes,created_by) VALUES('itemized',?,?,?,?,?,?,?,?,?,?,?)",
        (acc_id(conn, "1200"), stocktake_date, ledger_weight, matched_weight,
         -missing_weight, len(matched), len(missing), len(excess), entry_id,
         notes, username))
    st_id = cur.lastrowid
    st_no = f"ST-{st_id:05d}"
    conn.execute("UPDATE stocktakes SET stocktake_no=? WHERE id=?", (st_no, st_id))
    if entry_id:
        conn.execute("UPDATE journal_entries SET source_id=? WHERE id=?",
                     (st_id, entry_id))

    for no in matched:
        r = system[no]
        conn.execute(
            "INSERT INTO stocktake_lines(stocktake_id,work_order_id,work_order_no,"
            "status,registered_weight) VALUES(?,?,?,'matched',?)",
            (st_id, r["id"], no, r["registered_weight"]))
    for no in missing:
        r = system[no]
        conn.execute(
            "INSERT INTO stocktake_lines(stocktake_id,work_order_id,work_order_no,"
            "status,registered_weight) VALUES(?,?,?,'missing',?)",
            (st_id, r["id"], no, r["registered_weight"]))
        conn.execute("UPDATE work_orders SET is_deleted=1 WHERE id=?", (r["id"],))
    for no in excess:
        conn.execute(
            "INSERT INTO stocktake_lines(stocktake_id,work_order_id,work_order_no,"
            "status,registered_weight) VALUES(?,NULL,?,'excess',0)", (st_id, no))

    log_action(conn, username, "create", "stocktakes", st_id,
              f"{st_no} matched={len(matched)} missing={len(missing)} excess={len(excess)}")
    return {"id": st_id, "stocktake_no": st_no, "matched": matched,
            "missing": missing, "excess": excess, "missing_weight": missing_weight,
            "matched_weight": matched_weight, "entry_id": entry_id}


def recent_stocktakes(conn, limit=20):
    return conn.execute(
        "SELECT s.*, a.code account_code, a.name account_name FROM stocktakes s"
        " LEFT JOIN accounts a ON a.id=s.account_id"
        " WHERE s.is_deleted=0 ORDER BY s.id DESC LIMIT ?", (limit,)).fetchall()


def search_stocktakes(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT s.*, a.code account_code, a.name account_name FROM stocktakes s"
          " LEFT JOIN accounts a ON a.id=s.account_id WHERE s.is_deleted=0")
    params = []
    if q:
        sql += " AND (s.stocktake_no LIKE ? OR a.name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND s.stocktake_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND s.stocktake_date<=?"; params.append(date_to)
    sql += " ORDER BY s.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


def stocktake_lines(conn, stocktake_id):
    return conn.execute(
        "SELECT * FROM stocktake_lines WHERE stocktake_id=?"
        " ORDER BY status, work_order_no", (stocktake_id,)).fetchall()
