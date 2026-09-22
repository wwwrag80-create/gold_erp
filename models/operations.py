# -*- coding: utf-8 -*-
"""إدارة وتعديل وتحويل العمليات (Invoices & Vouchers Management).

تصحيح أخطاء الإدخال **مع الحفاظ على سلامة الدفاتر**: لا يُعدَّل أي قيد
سابق في مكانه، بل تُعكس العملية القديمة بقيد صريح ثم تُنشأ الجديدة —
فيبقى الأثر التاريخي كاملاً وقابلاً للتدقيق، وتنعكس النتيجة فوراً في
كشوفات الحساب ولوحات حركة الأطقم.

كل دالة هنا تُستدعى داخل `with db() as conn` فتُغلَّف بمعاملة ذرّية
(BEGIN IMMEDIATE … COMMIT/ROLLBACK) — فإن فشلت أي خطوة تراجعت العملية
بكاملها ولم تُحفظ نصفها.
"""
from models import invoices, vouchers
from services.audit import log_action


# ══════════════════════════════════════════════════════════════════
# أدوات مشتركة
# ══════════════════════════════════════════════════════════════════

def _invoice_cart(conn, invoice_id):
    """يعيد بنود الفاتورة بصيغة سلة قابلة لإعادة الترحيل."""
    rows = conn.execute(
        "SELECT work_order_id, registered_weight, wage_per_gram,"
        " COALESCE(karat,0) karat"
        " FROM invoice_items WHERE invoice_id=? ORDER BY id",
        (invoice_id,)).fetchall()
    return [{"work_order_id": r["work_order_id"],
             "weight": r["registered_weight"],
             "karat": r["karat"],
             "wage_override": r["wage_per_gram"]} for r in rows]


def _invoice_source(conn, inv):
    """حساب مصدر الذهب وعياره — ليُعاد ترحيل الفاتورة من حيث خرجت.

    إعادةُ الترحيل من الحساب الافتراضي كانت ستُخرج الذهب من الذهب
    المشغول وقد خرج أصلاً من صندوق الكسر، فيختلّ المخزنان معاً بلا
    أن يظهر شيء في الميزان.
    """
    try:
        return {"source_account_id": inv["source_account_id"],
                "scrap_karat": inv["scrap_karat"] or 0}
    except (KeyError, IndexError):
        return {"source_account_id": None, "scrap_karat": 0}


def _entity_name(conn, entity_id):
    r = conn.execute("SELECT name FROM entities WHERE id=?",
                     (entity_id,)).fetchone()
    return r["name"] if r else f"#{entity_id}"


def _void(conn, entry_id, username, note):
    """يعكس قيداً سابقاً بقيد مضاد صريح (بلا حذف مادي)."""
    from services.audit import reverse_entry
    if entry_id:
        reverse_entry(conn, entry_id, username)
    log_action(conn, username, "void", "journal_entries", entry_id, note)


# ══════════════════════════════════════════════════════════════════
# 1) تحويل فاتورة من جهة إلى أخرى
# ══════════════════════════════════════════════════════════════════

def transfer_invoice(conn, invoice_id, new_entity_id, username, notes=""):
    """يحوّل فاتورة من العميل (أ) إلى العميل (ب) كعملية مركّبة:

    1. **قيد عكسي** للعميل (أ): يُخصم من ذمته ويظهر في كشف الذهب
       المشغول كحركة عكسية.
    2. **فاتورة جديدة** للعميل (ب) بنفس البنود: تُضاف لذمته وتظهر
       كمبيعات.
    3. أرقام التشغيل تُسجَّل حركتها فتبقى لوحات دوران المخزون دقيقة.
    """
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0",
                       (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة أو محذوفة")
    if inv["customer_id"] == new_entity_id:
        raise ValueError("الفاتورة مسجّلة على هذه الجهة أصلاً")
    cart = _invoice_cart(conn, invoice_id)
    if not cart:
        raise ValueError("الفاتورة بلا بنود")

    old_name = _entity_name(conn, inv["customer_id"])
    new_name = _entity_name(conn, new_entity_id)
    kind = inv["kind"]

    # (1) عكس أثر الفاتورة القديمة على الجهة (أ)
    _void(conn, inv["entry_id"], username,
          f"تحويل الفاتورة {inv['invoice_no']} من {old_name} إلى {new_name}")
    conn.execute("UPDATE invoices SET is_deleted=1 WHERE id=?", (invoice_id,))

    # إعادة الأطقم لحالتها قبل الفاتورة ليقبلها الترحيل الجديد
    back = "in_stock" if kind == "sale" else "sold"
    for it in cart:
        conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                     (back, it["work_order_id"]))

    # (2) إنشاء العملية نفسها على الجهة (ب)
    fn = invoices.create_sale if kind == "sale" else invoices.create_sale_return
    res = fn(conn, new_entity_id, cart, inv["invoice_date"], username,
             bool(inv["vat_applied"]),
             (inv["description"] or "")
             + f" [محوَّلة من {old_name} — {inv['invoice_no']}]",
             **_invoice_source(conn, inv))

    log_action(conn, username, "transfer", "invoices", invoice_id,
               f"{inv['invoice_no']} : {old_name} → {new_name}"
               f" | الجديدة {res['invoice_no']}"
               + (f" | {notes}" if notes else ""))
    return {"old_no": inv["invoice_no"], "new_no": res["invoice_no"],
            "new_id": res["id"], "from": old_name, "to": new_name,
            "items": len(cart)}


# ══════════════════════════════════════════════════════════════════
# 2) تعديل بنود فاتورة (إضافة/حذف أرقام تشغيل)
# ══════════════════════════════════════════════════════════════════

def edit_invoice_items(conn, invoice_id, new_cart, username,
                       entity_id=None, invoice_date=None, apply_vat=None,
                       notes=""):
    """يعيد ترحيل الفاتورة ببنودها الجديدة بعد عكس القديمة.

    * **حذف رقم تشغيل**: تنقص المديونية وتعود حالته إلى «متاح».
    * **إضافة رقم تشغيل**: تزيد المديونية وتصير حالته «مباع».

    كل ذلك داخل معاملة واحدة — فإن فشلت خطوة تراجع كل شيء.
    """
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0",
                       (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة أو محذوفة")
    if not new_cart:
        raise ValueError("لا يمكن ترك الفاتورة بلا بنود — احذفها بدل ذلك")

    old_cart = _invoice_cart(conn, invoice_id)
    old_ids = {c["work_order_id"] for c in old_cart}
    new_ids = {c["work_order_id"] for c in new_cart}
    removed, added = old_ids - new_ids, new_ids - old_ids
    kind = inv["kind"]

    _void(conn, inv["entry_id"], username,
          f"تعديل بنود الفاتورة {inv['invoice_no']}")
    conn.execute("UPDATE invoices SET is_deleted=1 WHERE id=?", (invoice_id,))

    # أرقام التشغيل القديمة تعود لحالتها السابقة قبل إعادة الترحيل
    back = "in_stock" if kind == "sale" else "sold"
    for wid in old_ids:
        conn.execute("UPDATE work_orders SET status=? WHERE id=?", (back, wid))

    fn = invoices.create_sale if kind == "sale" else invoices.create_sale_return
    res = fn(conn, entity_id or inv["customer_id"], new_cart,
             invoice_date or inv["invoice_date"], username,
             bool(inv["vat_applied"] if apply_vat is None else apply_vat),
             inv["description"] or "", **_invoice_source(conn, inv))

    log_action(conn, username, "edit_items", "invoices", invoice_id,
               f"{inv['invoice_no']} → {res['invoice_no']}"
               f" | حُذف {len(removed)} | أُضيف {len(added)}"
               + (f" | {notes}" if notes else ""))
    return {"old_no": inv["invoice_no"], "new_no": res["invoice_no"],
            "new_id": res["id"], "removed": len(removed), "added": len(added)}


# ══════════════════════════════════════════════════════════════════
# 3) تحويل سند قبض/صرف من حساب إلى آخر
# ══════════════════════════════════════════════════════════════════

def transfer_voucher(conn, voucher_id, new_entity_id, username, notes=""):
    """يعكس السند على الجهة القديمة وينشئه على الجهة الجديدة بكل أسطره
    (أعيرة الذهب المتعددة والنقد معاً)."""
    v = conn.execute("SELECT * FROM vouchers WHERE id=? AND is_deleted=0",
                     (voucher_id,)).fetchone()
    if not v:
        raise ValueError("السند غير موجود أو محذوف")
    if v["customer_id"] == new_entity_id:
        raise ValueError("السند مسجّل على هذه الجهة أصلاً")

    rows = [{"kind": r["line_kind"], "weight": r["gold_weight"],
             "karat": r["gold_karat"], "amount": r["cash_amount"],
             "notes": r["line_notes"] or ""}
            for r in vouchers.voucher_lines(conn, voucher_id)]
    if not rows:
        rows = []
        if v["gold_weight"]:
            rows.append({"kind": "gold", "weight": v["gold_weight"],
                         "karat": v["gold_karat"], "notes": ""})
        if v["cash_amount"]:
            rows.append({"kind": "cash", "amount": v["cash_amount"],
                         "notes": ""})
    if not rows:
        raise ValueError("السند بلا أسطر")

    old_name = _entity_name(conn, v["customer_id"]) if v["customer_id"] else "—"
    new_name = _entity_name(conn, new_entity_id)

    _void(conn, v["entry_id"], username,
          f"تحويل السند {v['voucher_no']} من {old_name} إلى {new_name}")
    conn.execute("UPDATE vouchers SET is_deleted=1 WHERE id=?", (voucher_id,))

    res = vouchers.create_voucher(
        conn, v["kind"], v["voucher_date"], username,
        entity_id=new_entity_id, rows=rows,
        cash_account_code=v["cash_account_code"] or "1400",
        net_diff=v["net_diff"] or 0, disc_cash=v["disc_cash"] or 0,
        disc_gold=v["disc_gold"] or 0,
        notes=(v["notes"] or "") + f" [محوَّل من {old_name}]")

    log_action(conn, username, "transfer", "vouchers", voucher_id,
               f"{v['voucher_no']} : {old_name} → {new_name}"
               f" | الجديد {res['voucher_no']}"
               + (f" | {notes}" if notes else ""))
    return {"old_no": v["voucher_no"], "new_no": res["voucher_no"],
            "new_id": res["id"], "from": old_name, "to": new_name,
            "lines": len(rows)}


# ══════════════════════════════════════════════════════════════════
# 4) سجل التدقيق
# ══════════════════════════════════════════════════════════════════

AUDIT_ACTIONS = {
    "transfer": "تحويل", "edit_items": "تعديل بنود", "void": "عكس قيد",
    "create": "إنشاء", "update": "تعديل", "soft_delete": "حذف",
    "edit": "تعديل شامل",
}


def audit_trail(conn, date_from=None, date_to=None, action=None, limit=500):
    """سجل التدقيق: من عدّل ماذا ومتى وبأي نوع تعديل."""
    q = "SELECT * FROM audit_log WHERE 1=1"
    p = []
    if date_from:
        q += " AND substr(created_at,1,10)>=?"
        p.append(date_from)
    if date_to:
        q += " AND substr(created_at,1,10)<=?"
        p.append(date_to)
    if action:
        q += " AND action=?"
        p.append(action)
    q += " ORDER BY id DESC LIMIT ?"
    p.append(limit)
    return [{"id": r["id"], "when": r["created_at"],
             "user": r["username"] or "—",
             "action": AUDIT_ACTIONS.get(r["action"], r["action"]),
             "table": r["table_name"] or "—",
             "record": r["record_id"], "details": r["details"] or ""}
            for r in conn.execute(q, p).fetchall()]


# ══════════════════════════════════════════════════════════════════
# 5) ضوابط حالة المخزون عند تعديل بنود الفاتورة
# ══════════════════════════════════════════════════════════════════

def check_item_addable(conn, wo_no, invoice_kind, current_ids=()):
    """رقابة صارمة قبل إضافة رقم تشغيل لفاتورة معدَّلة.

    * **فاتورة مبيعات**: لا يُضاف طقم غير موجود في الخزنة — لا يُباع
      ما ليس لدينا.
    * **فاتورة مرتجع**: لا يُضاف طقم موجود أصلاً في الخزنة — لا يُرجَع
      ما هو عندنا.

    تُعيد سجل الطقم عند القبول، وترفع خطأ مفصّلاً عند الرفض.
    """
    wo = conn.execute(
        "SELECT * FROM work_orders WHERE work_order_no=? AND is_deleted=0",
        (str(wo_no).strip(),)).fetchone()
    if not wo:
        raise ValueError(f"لا يوجد طقم برقم التشغيل {wo_no}")
    if wo["id"] in set(current_ids):
        raise ValueError(f"رقم التشغيل {wo_no} مضاف مسبقاً في هذه الفاتورة")
    in_stock = wo["status"] == "in_stock"
    if invoice_kind == "sale" and not in_stock:
        raise ValueError(
            f"رقم التشغيل {wo_no} غير متاح في الخزنة (مباع حالياً) — "
            f"لا يمكن إضافته لفاتورة مبيعات")
    if invoice_kind == "sale_return" and in_stock:
        raise ValueError(
            f"رقم التشغيل {wo_no} موجود بالفعل في الخزنة — "
            f"لا يمكن إرجاع طقم لم يخرج")
    return wo


def find_document(conn, number):
    """بحث مباشر برقم الفاتورة أو رقم السند."""
    num = str(number).strip()
    if not num:
        raise ValueError("أدخل رقم الفاتورة أو السند")
    inv = conn.execute(
        "SELECT i.id, i.invoice_no no, i.kind k, i.invoice_date d,"
        " i.customer_id ent, e.name party FROM invoices i"
        " LEFT JOIN entities e ON e.id=i.customer_id"
        " WHERE i.is_deleted=0 AND i.invoice_no=?", (num,)).fetchone()
    if inv:
        return {"src": "invoices", "id": inv["id"], "no": inv["no"],
                "kind": inv["k"], "date": inv["d"],
                "entity_id": inv["ent"], "party": inv["party"] or "—"}
    v = conn.execute(
        "SELECT v.id, v.voucher_no no, v.kind k, v.voucher_date d,"
        " v.customer_id ent, e.name party FROM vouchers v"
        " LEFT JOIN entities e ON e.id=v.customer_id"
        " WHERE v.is_deleted=0 AND v.voucher_no=?", (num,)).fetchone()
    if v:
        return {"src": "vouchers", "id": v["id"], "no": v["no"],
                "kind": v["k"], "date": v["d"],
                "entity_id": v["ent"], "party": v["party"] or "—"}
    raise ValueError(f"لا توجد عملية بالرقم {num}")


# ══════════════════════════════════════════════════════════════════
# 6) عكس نوع الفاتورة (مبيعات ⇄ مرتجع)
# ══════════════════════════════════════════════════════════════════

def flip_invoice_kind(conn, invoice_id, username, notes=""):
    """يحوّل الفاتورة من مبيعات إلى مرتجع أو العكس لنفس الجهة.

    يُعكس القيد المالي بالكامل (فيصبح العميل دائناً والذهب المشغول
    مديناً في حالة التحويل إلى مرتجع)، وتُحدَّث حالة **جميع** أرقام
    التشغيل المرتبطة لتعود للخزنة أو تخرج منها بحسب النوع الجديد.
    """
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0",
                       (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة أو محذوفة")
    cart = _invoice_cart(conn, invoice_id)
    if not cart:
        raise ValueError("الفاتورة بلا بنود")

    old_kind = inv["kind"]
    new_kind = "sale_return" if old_kind == "sale" else "sale"
    lbl = {"sale": "مبيعات", "sale_return": "مرتجع"}

    _void(conn, inv["entry_id"], username,
          f"عكس نوع الفاتورة {inv['invoice_no']}:"
          f" {lbl[old_kind]} → {lbl[new_kind]}")
    conn.execute("UPDATE invoices SET is_deleted=1 WHERE id=?", (invoice_id,))

    # تهيئة حالة الأطقم لتقبل النوع الجديد
    need = "in_stock" if new_kind == "sale" else "sold"
    for it in cart:
        conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                     (need, it["work_order_id"]))

    fn = invoices.create_sale if new_kind == "sale" else invoices.create_sale_return
    res = fn(conn, inv["customer_id"], cart, inv["invoice_date"], username,
             bool(inv["vat_applied"]),
             (inv["description"] or "")
             + f" [عُكس نوعها من {lbl[old_kind]}]",
             **_invoice_source(conn, inv))

    log_action(conn, username, "flip_kind", "invoices", invoice_id,
               f"{inv['invoice_no']} : {lbl[old_kind]} → {lbl[new_kind]}"
               f" | الجديدة {res['invoice_no']}"
               + (f" | {notes}" if notes else ""))
    return {"old_no": inv["invoice_no"], "new_no": res["invoice_no"],
            "new_id": res["id"], "from": lbl[old_kind], "to": lbl[new_kind],
            "items": len(cart)}


# ══════════════════════════════════════════════════════════════════
# 7) تعديل عملية توريد (خزينة التصنيع ⇄ الذهب المشغول)
# ══════════════════════════════════════════════════════════════════

def edit_supply(conn, wo_id, gold, small_stones, big_stones, username,
                wage_per_gram=None, notes=""):
    """يعدّل أوزان عملية توريد فيتحدّث الرصيد **في الخزنتين معاً**.

    التوريد يُنقص خزينة التصنيع ويزيد الذهب المشغول بنفس الوزن المقيد،
    فتعديله يُعكس القيد القديم كاملاً ويُرحَّل الجديد داخل معاملة واحدة
    — فلا يختلّ ميزان الذهب بين الخزنتين إطلاقاً.
    """
    from models import inventory
    wo = conn.execute("SELECT * FROM work_orders WHERE id=? AND is_deleted=0",
                      (wo_id,)).fetchone()
    if not wo:
        raise ValueError("الطقم غير موجود")
    if wo["status"] != "in_stock":
        raise ValueError(
            f"الطقم {wo['work_order_no']} مباع حالياً — "
            f"أعد فاتورته أولاً ثم عدّل التوريد")

    _void(conn, wo["entry_id"], username,
          f"تعديل توريد رقم التشغيل {wo['work_order_no']}")
    conn.execute("UPDATE work_orders SET is_deleted=1 WHERE id=?", (wo_id,))

    created = inventory.create_work_orders_batch(
        conn, [{"wo_no": wo["work_order_no"], "gold": gold,
                "small_stones": small_stones, "big_stones": big_stones,
                "discount_rate": wo["discount_rate"],
                "wage_per_gram": (wage_per_gram
                                  if wage_per_gram is not None
                                  else wo["wage_per_gram"]),
                "notes": notes or (wo["notes"] or "")}],
        (conn.execute("SELECT entry_date d FROM journal_entries WHERE id=?",
                      (wo["entry_id"],)).fetchone() or {"d": None})["d"]
        or wo["created_at"][:10],
        username)

    log_action(conn, username, "edit_supply", "work_orders", wo_id,
               f"{wo['work_order_no']}: مقيد {wo['registered_weight']:.2f}"
               f" → {created['total_registered']:.2f}"
               + (f" | {notes}" if notes else ""))
    item = (created.get("items") or [{}])[0]
    return {"wo_no": wo["work_order_no"],
            "old_reg": round(wo["registered_weight"], 2),
            "new_reg": round(created["total_registered"], 2),
            "new_id": item.get("id")}
