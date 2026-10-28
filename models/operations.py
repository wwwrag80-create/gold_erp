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
        "SELECT it.work_order_id, it.registered_weight, it.wage_per_gram,"
        " COALESCE(it.karat,0) karat, it.wages,"
        " COALESCE(it.line_note,'') line_note,"
        " COALESCE(it.diamond,0) diamond,"
        " COALESCE(w.is_service,0) is_service"
        " FROM invoice_items it JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE it.invoice_id=? ORDER BY it.id",
        (invoice_id,)).fetchall()
    return [{"wage_only": True, "amount": r["wages"],
             "note": r["line_note"], "work_order_id": r["work_order_id"]}
            if r["is_service"] else
            {"work_order_id": r["work_order_id"],
             "weight": r["registered_weight"],
             "karat": r["karat"],
             "diamond": r["diamond"],
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
    from services.fatoora import ledger as _fatoora
    _fatoora.guard_change(conn, "invoices", invoice_id, "نقل")
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


def resale_marker(inv, party_name):
    """بيان الفاتورة المُصدَرة من مرتجع — يُكتب فيها ويُبحث به."""
    return f"مرتجع من {party_name} — فاتورة المرتجع رقم {inv['invoice_no']}"


def resell_return(conn, return_id, new_entity_id, username,
                  invoice_date=None, notes=""):
    """يُصدر **فاتورة مبيعات جديدة** بنفس بنود فاتورة مرتجع لجهةٍ أخرى.

    مثال: علي أرجع البضاعة بالمرتجع R-1، ثم بيعت نفس القطع لمحمد ⇒
    فاتورة مبيعات جديدة لمحمد بنفس أرقام التشغيل وأوزانها وأجورها،
    وبيانها «مرتجع من علي — فاتورة المرتجع رقم R-1».

    **المرتجع يبقى كما هو** (علي دائنٌ بما أرجع) — فهذه عمليتان حقيقيتان
    لا تصحيح خطأ: مرتجعٌ من جهة ثم بيعٌ لجهة أخرى. والبيع الجديد يمرّ
    بكل ضوابط البيع: لا تُباع قطعة ليست في المخزون (أي بيعت بعد
    المرتجع)، ولا يُصدر المرتجع نفسه مرتين.
    """
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0",
                       (return_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة أو محذوفة")
    if inv["kind"] != "sale_return":
        raise ValueError("هذا الخيار لفواتير المرتجع فقط — اختر فاتورة مرتجع")
    if not new_entity_id:
        raise ValueError("اختر الجهة التي تُصدَر لها الفاتورة الجديدة")
    cart = _invoice_cart(conn, return_id)
    if not cart:
        raise ValueError("فاتورة المرتجع بلا بنود")
    old_name = _entity_name(conn, inv["customer_id"])
    new_name = _entity_name(conn, new_entity_id)
    marker = resale_marker(inv, old_name)
    dup = conn.execute(
        "SELECT invoice_no FROM invoices WHERE kind='sale' AND is_deleted=0"
        " AND description LIKE ?", (f"%{marker}%",)).fetchone()
    if dup:
        raise ValueError(f"صدرت من هذا المرتجع فاتورة مبيعات من قبل: "
                         f"{dup['invoice_no']}")
    desc = marker + (f" — {notes}" if notes else "")
    res = invoices.create_sale(
        conn, new_entity_id, cart, invoice_date or inv["invoice_date"],
        username, bool(inv["vat_applied"]), desc,
        **_invoice_source(conn, inv))
    log_action(conn, username, "resell", "invoices", return_id,
               f"{inv['invoice_no']} ({old_name}) ⇒ مبيعات "
               f"{res['invoice_no']} ({new_name})"
               + (f" | {notes}" if notes else ""))
    return {"return_no": inv["invoice_no"], "new_no": res["invoice_no"],
            "new_id": res["id"], "from": old_name, "to": new_name,
            "items": len(cart), "description": desc}


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
    from services.fatoora import ledger as _fatoora
    _fatoora.guard_change(conn, "invoices", invoice_id, "تعديل بنود")
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0",
                       (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة أو محذوفة")
    if not new_cart:
        raise ValueError("لا يمكن ترك الفاتورة بلا بنود — احذفها بدل ذلك")

    old_cart = _invoice_cart(conn, invoice_id)
    old_ids = {c["work_order_id"] for c in old_cart if not c.get("wage_only")}
    new_ids = {c["work_order_id"] for c in new_cart if not c.get("wage_only")}
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

    # الأطقم المحذوفة من الفاتورة: حالتها من سلسلة حركتها لا «قبلها» (4.75)
    from models import wo_moves
    wo_moves.resync(conn, old_ids, username)
    log_action(conn, username, "edit_items", "invoices", invoice_id,
               f"{inv['invoice_no']} → {res['invoice_no']}"
               f" | حُذف {len(removed)} | أُضيف {len(added)}"
               + (f" | {notes}" if notes else ""))
    return {"old_no": inv["invoice_no"], "new_no": res["invoice_no"],
            "new_id": res["id"], "removed": len(removed), "added": len(added)}


# ══════════════════════════════════════════════════════════════════
# 2ب) دمج فواتير الجهة الواحدة في فاتورةٍ واحدة (4.95)
# ══════════════════════════════════════════════════════════════════

def merge_check(conn, invoice_ids):
    """يفحص قابلية الدمج ويعيد الفواتير مرتّبةً (الأقدم أولاً) — أو يرفع
    ValueError بالسبب. يُستدعى قبل السؤال وفي الدمج نفسه."""
    ids = sorted({int(i) for i in invoice_ids if i})
    if len(ids) < 2:
        raise ValueError("اختر فاتورتين أو أكثر للدمج")
    q = ",".join("?" * len(ids))
    invs = conn.execute(
        f"SELECT * FROM invoices WHERE id IN ({q}) AND is_deleted=0"
        " ORDER BY invoice_date, id", ids).fetchall()
    if len(invs) != len(ids):
        raise ValueError("إحدى الفواتير المختارة محذوفة أو غير موجودة")
    kinds = {i["kind"] for i in invs}
    if len(kinds) != 1 or not kinds <= {"sale", "sale_return"}:
        raise ValueError("الدمج لفواتير من نوعٍ واحد: مبيعات مع مبيعات، أو"
                         " مرتجع مع مرتجع")
    if len({i["customer_id"] for i in invs}) != 1:
        raise ValueError("الفواتير لجهاتٍ مختلفة — الدمج لفواتير الجهة"
                         " الواحدة")
    if len({int(i["vat_applied"] or 0) for i in invs}) != 1:
        raise ValueError("بعض الفواتير ضريبية وبعضها لا — لا تُدمج"
                         " فيتغيّر حساب الضريبة")
    if len({(i["source_account_id"] or 0, int(i["scrap_karat"] or 0))
            for i in invs}) != 1:
        raise ValueError("الفواتير من حسابات مصدرٍ مختلفة (المشغول / صندوق"
                         " الكسر) — لا تُدمج")
    from services.fatoora import ledger as _fatoora
    from models import fiscal
    for i in invs:
        _fatoora.guard_change(conn, "invoices", i["id"], "دمج")
        fiscal.assert_open(conn, i["invoice_date"])
        dep = conn.execute(
            "SELECT note_no FROM tax_debit_notes WHERE invoice_id=?"
            " AND COALESCE(is_deleted,0)=0", (i["id"],)).fetchone()
        if dep:
            raise ValueError(f"على الفاتورة {i['invoice_no']} إشعار مدين"
                             f" ({dep['note_no']}) — لا تُدمج")
    # الطقم المفرد سطرٌ واحد في الفاتورة: بيعُ جزءين منه في فاتورتين
    # يصير سطرين له في فاتورةٍ واحدة — فيُرفض بأسمائه
    seen, dup = {}, set()
    for r in conn.execute(
            "SELECT it.invoice_id, w.work_order_no no, w.id wid"
            " FROM invoice_items it JOIN work_orders w"
            " ON w.id=it.work_order_id WHERE it.invoice_id IN"
            f" ({q}) AND COALESCE(w.is_bulk,0)=0"
            " AND COALESCE(w.is_service,0)=0", ids):
        if seen.setdefault(r["wid"], r["invoice_id"]) != r["invoice_id"]:
            dup.add(r["no"])
    if dup:
        raise ValueError("الطقم في أكثر من فاتورة من المختارة: "
                         + "، ".join(sorted(dup))
                         + "\nالطقم المفرد سطرٌ واحد في الفاتورة — فلا تُدمج"
                         " فاتورتان فيهما الطقم نفسه (بيعُ جزءين منه، أو"
                         " بيعٌ ثم مرتجعٌ ثم بيع).")
    return invs


def merge_invoices(conn, invoice_ids, username, keep_id=None, notes=""):
    """يدمج فاتورتين أو أكثر من نوعٍ واحد (مبيعات أو مرتجع) لجهةٍ واحدة في
    **فاتورةٍ واحدة** تحمل أطقمها كلها — برقم «الباقية» وتاريخها (الأقدم
    افتراضاً، أو `keep_id`).

    البنود **تنتقل** إليها كما هي (أوزانها وأجورها وعيارها وحسابها)
    وقيدها يُعاد بناؤه منها، والمدموجة تُحذف منطقياً بقيودها. فلا يتحرّك
    المخزون ولا رصيد الرقم التجميعي: ما خرج خرج، وإنما يتوحّد مستنده.

    **حركة الطقم**: البنود تنتقل إلى تاريخ الباقية — فإن جعل ذلك سلسلة
    طقمٍ غير منتظمة (بيعٌ يسبق مرتجعاً كان قبله) رُفض الدمج كله بأسماء
    الأطقم ولم يُحفظ شيء. وتُضبط حالة كل طقمٍ من سلسلته بعده (`resync`).
    """
    from models import wo_moves
    from services import gold_math, zatca
    import config
    invs = merge_check(conn, invoice_ids)
    keep = next((i for i in invs if keep_id and i["id"] == int(keep_id)),
                invs[0])
    others = [i for i in invs if i["id"] != keep["id"]]
    ids = [i["id"] for i in invs]
    q = ",".join("?" * len(ids))
    wos = sorted({r[0] for r in conn.execute(
        f"SELECT work_order_id FROM invoice_items WHERE invoice_id IN ({q})",
        ids)})
    singles = wo_moves._singles(conn, wos)

    def _broken():
        out = set()
        for wid in singles:
            wo = wo_moves._wo(conn, wid)
            if wo_moves.violations(wo_moves.moves_of(conn, wid),
                                   wo_moves.birth(wo), wo_moves._full(wo)):
                out.add(wid)
        return out
    bad_before = _broken()

    for o in others:
        conn.execute("UPDATE invoice_items SET invoice_id=? WHERE"
                     " invoice_id=?", (keep["id"], o["id"]))
        conn.execute("INSERT OR IGNORE INTO invoice_assets(invoice_id, sha)"
                     " SELECT ?, sha FROM invoice_assets WHERE invoice_id=?",
                     (keep["id"], o["id"]))
        conn.execute("UPDATE scrap_moves SET is_deleted=1"
                     " WHERE ref_table='invoices' AND ref_id=?", (o["id"],))
        if o["entry_id"]:
            conn.execute(
                "UPDATE journal_entries SET is_deleted=1, deleted_by=?,"
                " deleted_at=datetime('now','localtime') WHERE id=?",
                (username, o["entry_id"]))
        conn.execute("UPDATE invoices SET is_deleted=1 WHERE id=?",
                     (o["id"],))
        log_action(conn, username, "merge", "invoices", o["id"],
                   f"{o['invoice_no']} دُمجت في {keep['invoice_no']}")

    # إجماليات الباقية من بنودها كلها — كما يحسبها الترحيل نفسه
    from models.entities import get_entity
    internal = get_entity(conn, keep["customer_id"])["entity_type"] \
        == "internal"
    t = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN COALESCE(w.is_service,0)=0"
        " THEN it.registered_weight END),0) tw,"
        " COALESCE(SUM(it.wages),0) tg FROM invoice_items it"
        " JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE it.invoice_id=?", (keep["id"],)).fetchone()
    tw = round(float(t["tw"] or 0), 3)
    tg = 0.0 if internal else round(float(t["tg"] or 0), 2)
    vat_on = bool(keep["vat_applied"]) and not internal
    vat = gold_math.wages_vat(tg) if vat_on else 0.0
    grand = round(tg + vat, 2)
    qr = keep["qr_base64"] or ""
    if vat_on:
        ts = f"{keep['invoice_date']}T{(keep['created_at'] or '')[11:19] or '00:00:00'}"
        qr = zatca.build_tlv_base64(config.COMPANY_NAME,
                                    config.COMPANY_VAT_NUMBER, ts, grand, vat)
    nos = "، ".join(o["invoice_no"] for o in others)
    desc = ((keep["description"] or "").strip()
            + f" [دُمجت فيها: {nos}]").strip()
    conn.execute(
        "UPDATE invoices SET total_weight=?, total_wages=?, vat_amount=?,"
        " grand_total=?, qr_base64=?, description=? WHERE id=?",
        (tw, tg, vat, grand, qr, desc, keep["id"]))
    _aw = invoices._rebuild_invoice_entry(conn, keep["id"])
    _src = keep["source_account_id"]
    invoices._sync_scrap_moves(
        conn, keep["id"], invoices._scrap_acc(conn, _aw, _src),
        int(keep["scrap_karat"] or 0), invoices._scrap_weight(conn, _aw),
        keep["kind"])

    # حركة الطقم: لا دمج يكسر سلسلةً كانت منتظمة
    newly = _broken() - bad_before
    if newly:
        names = [r[0] for r in conn.execute(
            "SELECT work_order_no FROM work_orders WHERE id IN"
            f" ({','.join('?' * len(newly))})", sorted(newly))]
        raise ValueError(
            "الدمج ينقل الأطقم إلى تاريخ الفاتورة "
            f"{keep['invoice_no']} ({keep['invoice_date']}) فتصير حركتها"
            " غير منتظمة: " + "، ".join(names)
            + "\nاختر فاتورةً أحدث تبقى، أو ادمج غيرها.")
    wo_moves.resync(conn, wos, username)
    n = conn.execute("SELECT COUNT(*) FROM invoice_items WHERE invoice_id=?",
                     (keep["id"],)).fetchone()[0]
    log_action(conn, username, "merge", "invoices", keep["id"],
               f"{keep['invoice_no']} ← {nos} | {n} بنداً"
               + (f" | {notes}" if notes else ""))
    return {"id": keep["id"], "invoice_no": keep["invoice_no"],
            "invoice_date": keep["invoice_date"],
            "merged": [o["invoice_no"] for o in others], "items": n,
            "total_weight": tw, "total_wages": tg, "vat": vat,
            "grand_total": grand}


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
    "edit": "تعديل شامل", "resell": "فاتورة من مرتجع",
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
    from services.fatoora import ledger as _fatoora
    _fatoora.guard_change(conn, "invoices", invoice_id, "عكس نوع")
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
    # في مكانه داخل دفعته (4.75): لا يُحذف إخوته ولا تنقطع فواتيره عنه
    from models import inventory
    return inventory.edit_supply_item(
        conn, wo_id, gold, small_stones, big_stones, username,
        wage_per_gram=wage_per_gram, notes=notes)
