# -*- coding: utf-8 -*-
"""التسكير: تسوية مديونية الذهب لأي جهة تعامل (عميل/مورد/شريك/داخلي)
عبر حساب وسيط، بأحد وضعين:

* **تسكير بسعر** (المبلغ النقدي مُدخَل): يُخفَّض رصيد الذهب ويُقيَّد
  مقابله مبلغ نقدي في الحساب الجاري للجهة بسعر اليوم.

* **تسكير ذهب فقط** (المبلغ صفر أو فارغ): يُرحَّل قيد الوزن وحده
  ويُتجاهَل الشق النقدي تماماً. القيد يبقى متوازناً لأن ميزان الذهب
  وميزان النقد مستقلان — فالوزن مدين/دائن متساوٍ، والنقد صفر على
  الطرفين."""
from models.accounts import acc_id
from models.entities import get_entity
from services.accounting_engine import post_entry
from services.audit import log_action


def create_fixing(conn, entity_id, weight, price, op_date, username,
                  notes=""):
    """ينشئ عملية تسكير. `price` اختياري: إن كان صفراً أو فارغاً تُرحَّل
    عملية «تسكير ذهب فقط» بلا أي أثر نقدي."""
    ent = get_entity(conn, entity_id)
    if not ent:
        raise ValueError("اختر الجهة")
    weight = round(float(weight or 0), 3)
    price = float(price or 0)
    if weight <= 0:
        raise ValueError("أدخل وزن التسكير")
    if price < 0:
        raise ValueError("سعر الجرام لا يقبل السالب")
    amount = round(weight * price, 2)
    gold_only = amount <= 0
    bridge = acc_id(conn, "6100")
    lines = [
        {"account_id": bridge, "gold_debit": weight,
         "line_desc": "تسكير: استلام الوزن دفترياً"},
        {"account_id": ent["account_id"], "gold_credit": weight,
         "line_desc": "تخفيض مديونية الذهب"},
    ]
    if not gold_only:            # الشق النقدي يُضاف فقط عند وجود مبلغ
        lines += [
            {"account_id": ent["account_id"], "cash_debit": amount,
             "line_desc": f"تسكير {weight:.2f} جم × {price:.2f}"},
            {"account_id": bridge, "cash_credit": amount},
        ]
    cur = conn.execute(
        "INSERT INTO fixing_ops(op_date,customer_id,weight,price,amount,created_by)"
        " VALUES(?,?,?,?,?,?)",
        (op_date, entity_id, weight, price, amount, username))
    op_id = cur.lastrowid
    op_no = f"F-{op_id:05d}"
    label = ("تسكير ذهب فقط" if gold_only else "تسكير بسعر")
    entry_id = post_entry(conn, op_date,
                          f"{label} {op_no} — {ent['name']}", lines,
                          source_table="fixing_ops", source_id=op_id,
                          username=username, note=notes)
    conn.execute("UPDATE fixing_ops SET op_no=?, entry_id=? WHERE id=?",
                 (op_no, entry_id, op_id))
    log_action(conn, username, "create", "fixing_ops", op_id, op_no)
    return {"id": op_id, "op_no": op_no, "amount": amount,
            "weight": weight, "gold_only": gold_only,
            "entry_id": entry_id}


def recent_fixing(conn, limit=20):
    return conn.execute(
        "SELECT f.*, e.name customer_name FROM fixing_ops f"
        " JOIN entities e ON e.id=f.customer_id"
        " WHERE f.is_deleted=0 ORDER BY f.id DESC LIMIT ?", (limit,)).fetchall()


def search_fixing(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT f.*, e.name customer_name FROM fixing_ops f"
          " JOIN entities e ON e.id=f.customer_id WHERE f.is_deleted=0")
    params = []
    if q:
        sql += " AND (f.op_no LIKE ? OR e.name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND f.op_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND f.op_date<=?"; params.append(date_to)
    sql += " ORDER BY f.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()
