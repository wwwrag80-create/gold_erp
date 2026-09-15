# -*- coding: utf-8 -*-
"""المشتريات (تشغيلية/أصول) — آجلة إلزامياً: تُقيَّد على حساب المورد
(جهة تعامل من نوع مورد) لا نقداً مباشرة؛ السداد يتم حصراً لاحقاً عبر
سندات الصرف. تشمل أيضاً الإهلاك الشهري للأصول الثابتة."""
import config
from models.accounts import acc_id
from models.entities import get_entity
from services.accounting_engine import post_entry
from services.audit import log_action


def create_purchase(conn, kind, supplier_id, description, amount, vat_amount,
                    purchase_date, username):
    if kind not in ("expense", "asset"):
        raise ValueError("نوع الفاتورة غير صحيح")
    sup = get_entity(conn, supplier_id)
    if not sup or sup["entity_type"] != "supplier":
        raise ValueError("اختر مورداً من دليل جهات التعامل")
    if not description.strip():
        raise ValueError("أدخل بيان الفاتورة")
    if amount <= 0:
        raise ValueError("أدخل مبلغ الفاتورة")
    if vat_amount < 0:
        raise ValueError("الضريبة لا تقبل السالب")
    total = round(amount + vat_amount, 2)

    asset_id = None
    if kind == "asset":
        # الأصول تُسجَّل بقيمتها الدفترية فقط — بلا إهلاك ولا مجمع إهلاك
        cur = conn.execute(
            "INSERT INTO fixed_assets(name,purchase_date,cost,created_by)"
            " VALUES(?,?,?,?)",
            (description.strip(), purchase_date, amount, username))
        asset_id = cur.lastrowid

    debit_code = "1700" if kind == "asset" else "5500"
    lines = [{"account_id": acc_id(conn, debit_code), "cash_debit": amount, "line_desc": description.strip()}]
    if vat_amount:
        lines.append({"account_id": acc_id(conn, "1900"),
                      "cash_debit": vat_amount, "line_desc": "ضريبة مدخلات"})
    lines.append({"account_id": sup["account_id"], "cash_credit": total,
                  "line_desc": "مشتريات آجلة"})

    cur = conn.execute(
        "INSERT INTO purchases(purchase_date,supplier,supplier_id,kind,"
        "description,amount,vat_amount,total,asset_id,created_by)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (purchase_date, sup["name"], supplier_id, kind, description.strip(),
         amount, vat_amount, total, asset_id, username))
    p_id = cur.lastrowid
    p_no = f"P-{p_id:05d}"
    label = "شراء أصل ثابت" if kind == "asset" else "مشتريات تشغيلية"
    entry_id = post_entry(
        conn, purchase_date,
        f"{label} آجلة {p_no} — المورد {sup['name']} — {description}", lines,
        source_table="purchases", source_id=p_id, username=username,
        note=description)
    conn.execute("UPDATE purchases SET purchase_no=?, entry_id=? WHERE id=?",
                 (p_no, entry_id, p_id))
    log_action(conn, username, "create", "purchases", p_id, p_no)
    return {"id": p_id, "purchase_no": p_no, "total": total,
            "asset_id": asset_id, "entry_id": entry_id, "supplier_name": sup["name"]}


def list_assets(conn):
    """سجل الأصول الثابتة بقيمتها الدفترية فقط (بلا إهلاك)."""
    return conn.execute(
        "SELECT * FROM fixed_assets WHERE is_deleted=0 ORDER BY id").fetchall()


def recent_purchases(conn, limit=20):
    return conn.execute(
        "SELECT * FROM purchases WHERE is_deleted=0 ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def search_purchases(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT p.*, COALESCE(e.name, p.supplier) supplier_name"
          " FROM purchases p LEFT JOIN entities e ON e.id=p.supplier_id"
          " WHERE p.is_deleted=0")
    params = []
    if q:
        sql += (" AND (p.purchase_no LIKE ? OR p.description LIKE ?"
               " OR p.supplier LIKE ? OR e.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND p.purchase_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND p.purchase_date<=?"; params.append(date_to)
    sql += " ORDER BY p.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


