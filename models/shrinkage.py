# -*- coding: utf-8 -*-
"""تسوية فاقد التصنيع الشهرية: مطابقة خزينة التصنيع مع الجرد الفعلي
بتحميل الخياسات على صندوق فاقد الذهب — قسم التصنيع."""
from models.accounts import acc_id
from services.accounting_engine import post_entry
from services.audit import log_action


def create_shrinkage(conn, weight, op_date, period, username,
                     notes=""):
    if weight <= 0:
        raise ValueError("أدخل وزن الفاقد بالجرام")
    w = round(weight, 3)
    lines = [
        {"account_id": acc_id(conn, "5110"), "gold_debit": w,
         "line_desc": "فاقد تصنيع (خياسات/جلي/تشغيل يومي)"},
        {"account_id": acc_id(conn, "1100"), "gold_credit": w,
         "line_desc": "تخفيض خزينة التصنيع للمطابقة مع الجرد الفعلي"},
    ]
    cur = conn.execute(
        "INSERT INTO shrinkage_ops(op_date,period,weight,notes,"
        "created_by) VALUES(?,?,?,?,?)",
        (op_date, period, w, notes, username))
    op_id = cur.lastrowid
    op_no = f"SH-{op_id:05d}"
    entry_id = post_entry(conn, op_date,
                          f"تسوية فاقد التصنيع {op_no} — فترة {period}", lines,
                          source_table="shrinkage_ops", source_id=op_id,
                          username=username, note=notes)
    conn.execute("UPDATE shrinkage_ops SET op_no=?, entry_id=? WHERE id=?",
                 (op_no, entry_id, op_id))
    log_action(conn, username, "create", "shrinkage_ops", op_id,
               f"{w} جم — {period}")
    return {"id": op_id, "op_no": op_no, "weight": w, "entry_id": entry_id}


def recent_shrinkage(conn, limit=20):
    return conn.execute(
        "SELECT s.* FROM shrinkage_ops s"
        " WHERE s.is_deleted=0 ORDER BY s.id DESC LIMIT ?", (limit,)).fetchall()


def search_shrinkage(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT s.* FROM shrinkage_ops s"
          " WHERE s.is_deleted=0")
    params = []
    if q:
        sql += " AND s.op_no LIKE ?"; params.append(f"%{q}%")
    if date_from:
        sql += " AND s.op_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND s.op_date<=?"; params.append(date_to)
    sql += " ORDER BY s.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()
