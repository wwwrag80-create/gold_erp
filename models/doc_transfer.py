# -*- coding: utf-8 -*-
"""نقل عملية مُرحَّلة من حساب إلى آخر.

**الحالة**: سُجّلت فاتورة أو سند على العميل الخطأ، واكتُشف ذلك بعد
الترحيل. الحل الشائع — حذف العملية وإعادة إدخالها — يُغيّر تاريخها
ورقمها ويترك أثر حذف في السجل.

**الحل الصحيح محاسبياً**: العملية تبقى كما هي بتاريخها ورقمها
وأوزانها، ويُستبدل **طرفها المقابل فقط**. فتخرج من كشف العميل القديم
وتدخل كشف الجديد بنفس التاريخ، ولا يتغيّر أي رقم آخر.

**لماذا هذا سليم**: الطرف المقابل بيانٌ في القيد لا قيمة فيه. تغييره
لا يمسّ المدين ولا الدائن ولا الميزان — يُبدّل الحساب الذي يحمل
الطرف فقط. والميزانية تبقى متوازنة بالضرورة لأن المبلغ لم يتغيّر.

يُسجَّل النقل في سجل التدقيق كاملاً: من أي حساب، إلى أي حساب، ومتى.
"""
from services.audit import log_action

# الجداول التي تحمل طرفاً مقابلاً، وعمود الطرف في كلٍّ منها
DOC_PARTY = {
    "invoices": "customer_id",
    "vouchers": "customer_id",
    "purchases": "supplier_id",
    "fixing_ops": "customer_id",
}


def _entity_accounts(conn, entity_id):
    """حساب الجهة الرئيسي وحساباتها الفرعية."""
    e = conn.execute(
        "SELECT id, name, entity_type, account_id, capital_account_id"
        " FROM entities WHERE id=?", (entity_id,)).fetchone()
    if not e:
        raise ValueError("الجهة غير موجودة")
    ids = [e["account_id"]]
    if e["capital_account_id"]:
        ids.append(e["capital_account_id"])
    return e, [i for i in ids if i]


def preview(conn, source_table, source_id):
    """يعرض ما سيتغيّر قبل التنفيذ — بلا أي تعديل."""
    col = DOC_PARTY.get(source_table)
    if not col:
        raise ValueError(f"لا يمكن نقل مستندات من نوع: {source_table}")
    doc = conn.execute(
        f"SELECT * FROM {source_table} WHERE id=? AND is_deleted=0",
        (source_id,)).fetchone()
    if not doc:
        raise ValueError("المستند غير موجود أو محذوف")
    old_id = doc[col]
    if not old_id:
        raise ValueError("المستند بلا طرف مقابل — لا شيء يُنقل")
    old, old_accs = _entity_accounts(conn, old_id)

    entry_id = doc["entry_id"] if "entry_id" in doc.keys() else None
    lines = []
    if entry_id:
        qs = ",".join("?" * len(old_accs))
        lines = [dict(r) for r in conn.execute(
            f"SELECT l.id, l.account_id, l.gold_debit, l.gold_credit,"
            f" l.cash_debit, l.cash_credit, a.name acc_name"
            f" FROM journal_lines l JOIN accounts a ON a.id=l.account_id"
            f" WHERE l.entry_id=? AND l.account_id IN ({qs})",
            [entry_id] + old_accs)]

    date = ""
    for k in ("invoice_date", "voucher_date", "purchase_date", "op_date"):
        if k in doc.keys() and doc[k]:
            date = doc[k]
            break
    no = ""
    for k in ("invoice_no", "voucher_no", "purchase_no", "op_no"):
        if k in doc.keys() and doc[k]:
            no = doc[k]
            break

    return {"doc_no": no or f"#{source_id}", "date": date,
            "from_id": old_id, "from_name": old["name"],
            "entry_id": entry_id, "lines": lines,
            "line_count": len(lines)}


def transfer(conn, source_table, source_id, new_entity_id, username,
             reason=""):
    """ينقل المستند لجهة أخرى — بنفس التاريخ والرقم والمبالغ.

    يُبدّل:
      * الطرف المقابل في جدول المستند
      * أسطر القيد التي تخصّ حساب الجهة القديمة → حساب الجديدة

    ولا يمسّ: التاريخ · الرقم · المبالغ · الأوزان · بقية الأطراف.
    """
    info = preview(conn, source_table, source_id)
    col = DOC_PARTY[source_table]
    old_id = info["from_id"]
    if int(new_entity_id) == int(old_id):
        raise ValueError("الجهة الجديدة هي نفسها الحالية")

    old, old_accs = _entity_accounts(conn, old_id)
    new, new_accs = _entity_accounts(conn, new_entity_id)
    if not new_accs:
        raise ValueError(f"الجهة «{new['name']}» بلا حساب في الشجرة")

    # خريطة: الحساب الرئيسي القديم → الجديد، والفرعي → الفرعي
    amap = {old_accs[0]: new_accs[0]}
    if len(old_accs) > 1 and len(new_accs) > 1:
        amap[old_accs[1]] = new_accs[1]
    elif len(old_accs) > 1:
        # الجهة الجديدة بلا حساب فرعي: يُوجَّه للرئيسي
        amap[old_accs[1]] = new_accs[0]

    moved = 0
    if info["entry_id"]:
        for ln in info["lines"]:
            target = amap.get(ln["account_id"])
            if not target:
                continue
            conn.execute("UPDATE journal_lines SET account_id=? WHERE id=?",
                         (target, ln["id"]))
            moved += 1
        # البيان يذكر الجهة، فيُحدَّث ليطابق الواقع
        try:
            conn.execute(
                "UPDATE journal_entries SET description="
                "REPLACE(description, ?, ?) WHERE id=?",
                (old["name"], new["name"], info["entry_id"]))
            conn.execute(
                "UPDATE journal_lines SET line_desc="
                "REPLACE(line_desc, ?, ?) WHERE entry_id=?",
                (old["name"], new["name"], info["entry_id"]))
            # نقل المستند يغيّر حسابات القيد وبيانه: تعديلٌ مشروع
            # يُوسَم ليُعاد ختمه في سلسلة البصمات عند إغلاق المعاملة.
            from models import integrity
            integrity.mark(conn, info["entry_id"])
        except Exception:
            pass

    conn.execute(f"UPDATE {source_table} SET {col}=? WHERE id=?",
                 (new_entity_id, source_id))

    log_action(conn, username, "transfer", source_table, source_id,
               f"نقل {info['doc_no']} ({info['date']}) من «{old['name']}» "
               f"إلى «{new['name']}» — {moved} سطر"
               + (f" | {reason}" if reason else ""))
    return {"doc_no": info["doc_no"], "date": info["date"],
            "from_name": old["name"], "to_name": new["name"],
            "lines_moved": moved}


def can_transfer(source_table):
    return source_table in DOC_PARTY
