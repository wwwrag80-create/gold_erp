# -*- coding: utf-8 -*-
"""فواتير البيع والمرتجعات — الضريبة اختيارية لكل فاتورة + QR للضريبية
فقط. الأجر مرتبط بكل رقم تشغيل ويُستدعى ديناميكياً منه (وليس رقماً
موحّداً للفاتورة كلها)، مع إمكانية تعديله يدوياً لكل سطر. الرقم
التجميعي 0001 يُباع/يُرتجع بجزء من رصيده الوزني القائم بدل قطعة كاملة.
الطرف المقابل أي جهة تعامل (عميل/مورد/شريك) أو حساب داخلي."""
from datetime import datetime

import config
from models.accounts import acc_id
from models.entities import get_entity
from models.inventory import BULK_WO_NO, adjust_bulk_wo
from services import gold_math, zatca
from services.accounting_engine import post_entry
from services.audit import log_action


def _fetch_cart_lines(conn, cart, kind, skip_ids=None):
    """يحلّ كل سطر من السلة إلى (صف الطقم، الوزن المطبَّق، أجر الجرام).
    cart: [{"work_order_id", "weight": None أو رقم للتجميعي 0001,
            "wage_override": None أو رقم}]"""
    need_status = "in_stock" if kind == "sale" else "sold"
    out = []
    for c in cart:
        wo = conn.execute("SELECT * FROM work_orders WHERE id=? AND is_deleted=0",
                          (c["work_order_id"],)).fetchone()
        if not wo:
            raise ValueError("طقم غير موجود")
        # الأجر صفر قيمة صحيحة — `or` كان يستبدله بأجر الطقم الأصلي
        _ov = c.get("wage_override")
        wage = wo["wage_per_gram"] if _ov is None or _ov == "" else float(_ov)
        if wo["is_bulk"]:
            weight = c.get("weight")
            if not weight or weight <= 0:
                raise ValueError(f"أدخل الوزن المطلوب من الرقم التجميعي {wo['work_order_no']}")
            # الرقم التجميعي رصيد وزني لا قطعة: يُسمح بتجاوز المتاح
            # فيصير سالباً — وهي حالة واقعية (بضاعة خرجت قبل تسجيل
            # توريدها). الرصيد السالب يظهر في الكشف فيُصحَّح لاحقاً،
            # والقيد المزدوج يبقى متوازناً على أي حال.
        else:
            # `skip_ids`: أطقم هذه الفاتورة نفسها عند تعديلها.
            # حالتها الحالية أثر **هذه** الفاتورة، فاشتراط الحالة
            # السابقة عليها يمنع تعديل الفاتورة التي غيّرتها أصلاً.
            if wo["id"] not in (skip_ids or ()) \
                    and wo["status"] != need_status:
                need = "بالمخزون" if need_status == "in_stock" else "مباعاً"
                raise ValueError(f"الطقم {wo['work_order_no']} ليس {need}")
            # الوزن المُدخل صراحةً يُعتمد بدل وزن البطاقة.
            # **المبرّر المحاسبي**: الطقم قد يعود بوزن مختلف عمّا
            # سُجّل (خطأ إدخال أصلي أو تصحيح ميزان)، والواقع المادي
            # هو المرجع لا السجل. والوزن الجديد يُعتمد في البطاقة
            # كذلك (أدناه) فلا ينفصل المخزون عن الدفتر.
            _w = c.get("weight")
            weight = (float(_w) if _w not in (None, "", 0)
                      else wo["registered_weight"])
        out.append({"wo": wo, "weight": round(weight, 3), "wage": wage})
    return out


def _verify_posted(conn, invoice_id, entry_id):
    """يتحقق أن الفاتورة وقيدها كُتبا فعلاً قبل إنهاء المعاملة.

    لو فشل الترحيل صامتاً لأي سبب يُرفع خطأ فوراً فتتراجع المعاملة
    بالكامل — فلا تبقى فاتورة أو حركة طقم بلا قيد مالي.
    """
    if not entry_id:
        raise RuntimeError("فشل ترحيل القيد المالي للفاتورة")
    ok = conn.execute(
        "SELECT COUNT(*) c FROM journal_lines WHERE entry_id=?",
        (entry_id,)).fetchone()["c"]
    if ok < 2:
        raise RuntimeError(
            f"القيد {entry_id} غير مكتمل ({ok} سطر) — أُلغيت العملية")
    inv = conn.execute(
        "SELECT entry_id FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        raise RuntimeError("لم تُحفظ الفاتورة — أُلغيت العملية")


def _sync_wo_weight(conn, wo, new_reg, username):
    """يعتمد وزناً جديداً لبطاقة الطقم — بالنسبة نفسها لمكوّناته.

    الوزن المقيد مشتقّ من الذهب والفصوص والأحجار ونسبة الخصم؛ فتغييره
    وحده يجعل البطاقة غير متسقة. نضبط المكوّنات بنفس النسبة فيبقى
    التفصيل موافقاً للإجمالي.
    """
    old = float(wo["registered_weight"] or 0)
    if abs(old) < 1e-9:
        return False
    k = float(new_reg) / old
    conn.execute(
        "UPDATE work_orders SET registered_weight=?, gold_weight=?,"
        " small_stones=?, big_stones=?, stones_after_discount=?,"
        " standing_gold=?, gross_weight=?, stones_weight=? WHERE id=?",
        (round(new_reg, 3),
         round(float(wo["gold_weight"] or 0) * k, 3),
         round(float(wo["small_stones"] or 0) * k, 3),
         round(float(wo["big_stones"] or 0) * k, 3),
         round(float(wo["stones_after_discount"] or 0) * k, 3),
         round(float(wo["standing_gold"] or 0) * k, 3),
         round(float(wo["gross_weight"] or 0) * k, 3),
         round(float(wo["stones_weight"] or 0) * k, 3),
         wo["id"]))
    log_action(conn, username, "update", "work_orders", wo["id"],
               f"اعتماد وزن عائد بالمرتجع: {old:.3f} ← {new_reg:.3f} جم")
    return True


def _save(conn, kind, entity_id, cart, invoice_date, username, apply_vat,
         description="", qr_enabled=False):
    ent = get_entity(conn, entity_id)
    if not ent:
        raise ValueError("اختر الطرف المقابل")
    if not cart:
        raise ValueError("أضف طقماً واحداً على الأقل")
    lines_info = _fetch_cart_lines(conn, cart, kind)
    internal = ent["entity_type"] == "internal"
    if internal:
        apply_vat = False
    total_w = round(sum(li["weight"] for li in lines_info), 3)

    if internal:
        item_wages = [0.0 for _ in lines_info]
        wages = vat = grand = 0.0
    else:
        item_wages = [gold_math.total_wages(li["wage"], li["weight"])
                      for li in lines_info]
        wages = round(sum(item_wages), 2)
        vat = gold_math.wages_vat(wages) if apply_vat else 0.0
        grand = round(wages + vat, 2)
    ent_acc = ent["account_id"]

    if internal:
        if kind == "sale":
            desc = f"تحويل داخلي (إعادة تشغيل) — إلى {ent['name']}"
            lines = [
                {"account_id": ent_acc, "gold_debit": total_w,
                 "line_desc": "استلام طقم لإعادة التشغيل"},
                {"account_id": acc_id(conn, "1200"), "gold_credit": total_w},
            ]
            new_status, prefix = "sold", "T"
        else:
            desc = f"عكس تحويل داخلي — من {ent['name']}"
            lines = [
                {"account_id": acc_id(conn, "1200"), "gold_debit": total_w},
                {"account_id": ent_acc, "gold_credit": total_w,
                 "line_desc": "إعادة الطقم من خزينة التصنيع"},
            ]
            new_status, prefix = "in_stock", "TR"
        qr_b64 = ""
    elif kind == "sale":
        desc = ("فاتورة بيع" + ("" if apply_vat else " (غير ضريبية)")
               + f" — {ent['name']}")
        # فصل الإيراد: الذهب في حساب مستقل عن الأجور، مع إثبات تكلفة
        # الذهب مقابل خروجه من المخزون — فيبقى الميزان سليماً والمخزون
        # صحيحاً، وصافي ربح الذهب صفراً (المصنع يربح على الأجور).
        lines = [
            {"account_id": ent_acc, "gold_debit": total_w, "cash_debit": grand,
             "line_desc": "مديونية ذهب + أجور" + (" وضريبة" if apply_vat else "")},
            {"account_id": acc_id(conn, "4110"), "gold_credit": total_w,
             "line_desc": "إيراد مبيعات ذهب (وزناً)"},
            {"account_id": acc_id(conn, "4120"), "cash_credit": wages,
             "line_desc": "إيراد مبيعات أجور"},
            {"account_id": acc_id(conn, "5150"), "gold_debit": total_w,
             "line_desc": "تكلفة مبيعات الذهب"},
            {"account_id": acc_id(conn, "1200"), "gold_credit": total_w,
             "line_desc": "خروج الذهب من المخزون"},
        ]
        if vat:
            lines.append({"account_id": acc_id(conn, "2100"), "cash_credit": vat})
        new_status, prefix = "sold", "S"
    else:
        desc = ("مرتجع بيع" + ("" if apply_vat else " (غير ضريبي)")
               + f" — {ent['name']}")
        # المرتجع: عكس الفصل نفسه عبر حسابي المردودات
        lines = [
            {"account_id": acc_id(conn, "4910"), "gold_debit": total_w,
             "line_desc": "مردودات مبيعات ذهب (وزناً)"},
            {"account_id": acc_id(conn, "4920"), "cash_debit": wages,
             "line_desc": "مردودات مبيعات أجور"},
            {"account_id": acc_id(conn, "1200"), "gold_debit": total_w,
             "line_desc": "عودة الذهب للمخزون"},
            {"account_id": acc_id(conn, "5150"), "gold_credit": total_w,
             "line_desc": "عكس تكلفة مبيعات الذهب"},
        ]
        if vat:
            lines.append({"account_id": acc_id(conn, "2100"), "cash_debit": vat})
        lines.append({"account_id": ent_acc, "gold_credit": total_w,
                      "cash_credit": grand,
                      "line_desc": "عكس مديونية الذهب والأجور"})
        new_status, prefix = "in_stock", "R"

    if apply_vat and not internal:
        ts = f"{invoice_date}T{datetime.now():%H:%M:%S}"
        qr_b64 = zatca.build_tlv_base64(config.COMPANY_NAME,
                                        config.COMPANY_VAT_NUMBER, ts, grand, vat)
    elif not internal:
        qr_b64 = ""

    cur = conn.execute(
        "INSERT INTO invoices(kind,customer_id,invoice_date,wage_per_gram,"
        "total_weight,total_wages,vat_amount,grand_total,qr_base64,vat_applied,"
        "qr_enabled,description,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, entity_id, invoice_date, 0.0 if internal else
         (lines_info[0]["wage"] if lines_info else 0.0),
         total_w, wages, vat, grand, qr_b64, int(apply_vat),
         int(bool(qr_enabled)), description.strip(), username))
    inv_id = cur.lastrowid
    inv_no = f"{prefix}-{inv_id:05d}"
    entry_id = post_entry(conn, invoice_date, f"{desc} — {inv_no}", lines,
                          source_table="invoices", source_id=inv_id,
                          username=username, note=description)
    conn.execute("UPDATE invoices SET invoice_no=?, entry_id=? WHERE id=?",
                 (inv_no, entry_id, inv_id))

    for li, w in zip(lines_info, item_wages):
        wo = li["wo"]
        conn.execute(
            "INSERT INTO invoice_items(invoice_id,work_order_id,"
            "registered_weight,wage_per_gram,wages) VALUES(?,?,?,?,?)",
            (inv_id, wo["id"], li["weight"], li["wage"], w))
        if wo["is_bulk"]:
            delta = li["weight"] if kind == "sale_return" else -li["weight"]
            adjust_bulk_wo(conn, delta, username)
        else:
            # المرتجع بوزن مختلف: تُحدَّث بطاقة الطقم بالوزن العائد
            # فعلاً — فيتطابق المخزون مع ما دخل الخزنة حقيقةً.
            if kind == "sale_return" and \
                    abs(float(li["weight"] or 0)
                        - float(wo["registered_weight"] or 0)) > 0.001:
                _sync_wo_weight(conn, wo, float(li["weight"]), username)
            conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                        (new_status, wo["id"]))

    # صورة QR **خارج** المعاملة: بناؤها استيراد مكتبة وكتابة ملف،
    # وفعلهما داخل المعاملة يحبس قفل الكتابة ويجمّد الواجهة. النص
    # (TLV) وحده يُحفظ هنا، والصورة تُبنى عند عرضها أو طباعتها.
    qr_path = None
    # تحقق صريح قبل إنهاء المعاملة: لا فاتورة بلا قيد مرحَّل فعلياً
    _verify_posted(conn, inv_id, entry_id)
    # حزمة المزامنة الذرّية: الفاتورة وبنودها وقيدها وحركة الأطقم معاً
    from services import sync_queue
    sync_queue.enqueue(conn, "invoice",
                       sync_queue.bundle_invoice(conn, inv_id))
    log_action(conn, username, "create", "invoices", inv_id,
              f"{inv_no} vat={int(apply_vat)}")
    return {"id": inv_id, "invoice_no": inv_no, "total_weight": total_w,
            "total_wages": wages, "vat": vat, "grand_total": grand,
            "qr_base64": qr_b64, "qr_path": qr_path, "entry_id": entry_id,
            "vat_applied": bool(apply_vat), "internal": internal,
            "customer_name": ent["name"]}


def create_sale(conn, entity_id, cart, invoice_date, username,
                apply_vat=True, description="", qr_enabled=False):
    return _save(conn, "sale", entity_id, cart, invoice_date, username,
                apply_vat, description, qr_enabled)


def create_sale_return(conn, entity_id, cart, invoice_date, username,
                       apply_vat=True, description="", qr_enabled=False):
    return _save(conn, "sale_return", entity_id, cart, invoice_date, username,
                apply_vat, description, qr_enabled)


# ملاحظة: `update_sale` القديمة أُزيلت في 4.6.0.
# كانت تُلغي الفاتورة وتُصدر أخرى برقم وتاريخ جديدين — وهو خطأ
# محاسبي يجعل تصحيح عملية يبدو عمليتين. بديلها `update_invoice`
# التي تعدّل في المكان مع الحفاظ على الرقم والتاريخ.

def get_invoice_full(conn, invoice_id):
    """الفاتورة مع كل أطقمها — لتعبئة الشاشة عند التعديل. تُستخدم
    القيم المخزَّنة تاريخياً بجدول invoice_items (وزن السطر وأجره) لا
    الأرقام الحية من work_orders (التي قد تكون تغيّرت للتجميعي 0001)."""
    inv = conn.execute(
        "SELECT i.*, e.name customer_name FROM invoices i"
        " JOIN entities e ON e.id=i.customer_id WHERE i.id=?",
        (invoice_id,)).fetchone()
    if not inv:
        return None, []
    items = conn.execute(
        "SELECT it.id item_id, it.work_order_id, it.registered_weight,"
        " it.wage_per_gram, it.wages, w.work_order_no, w.is_bulk,"
        " w.gold_weight, w.small_stones, w.big_stones, w.stones_after_discount"
        " FROM invoice_items it JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE it.invoice_id=? ORDER BY it.id", (invoice_id,)).fetchall()
    return inv, items


def recent_invoices(conn, limit=20):
    return conn.execute(
        "SELECT i.*, e.name customer_name FROM invoices i"
        " JOIN entities e ON e.id=i.customer_id"
        " WHERE i.is_deleted=0 ORDER BY i.id DESC LIMIT ?", (limit,)).fetchall()


def search_invoices(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT i.*, e.name customer_name, e.entity_type FROM invoices i"
          " JOIN entities e ON e.id=i.customer_id WHERE i.is_deleted=0")
    params = []
    if q:
        sql += " AND (i.invoice_no LIKE ? OR e.name LIKE ? OR i.description LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND i.invoice_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND i.invoice_date<=?"; params.append(date_to)
    sql += " ORDER BY i.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


def create_tax_debit_note(conn, invoice_id, note_date, username):
    """تسوية ضريبية لاحقة: فاتورة بيعت سابقاً بلا ضريبة ثم طُلبت لها
    فاتورة ضريبية. يُثبت القيد فقط (مدين العميل / دائن ضريبة المخرجات)
    دون أي مساس بالمخزون أو ببيانات الفاتورة الأصلية."""
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0",
                       (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    if inv["kind"] != "sale":
        raise ValueError("إشعار المدين الضريبي يخص فواتير البيع فقط")
    if inv["vat_applied"]:
        raise ValueError("الفاتورة ضريبية أصلاً — لا حاجة لإشعار مدين")
    existing = conn.execute(
        "SELECT 1 FROM tax_debit_notes WHERE invoice_id=? AND is_deleted=0",
        (invoice_id,)).fetchone()
    if existing:
        raise ValueError("سبق إصدار إشعار مدين ضريبي لهذه الفاتورة")
    ent = get_entity(conn, inv["customer_id"])
    vat = gold_math.wages_vat(inv["total_wages"])
    if vat <= 0:
        raise ValueError("لا توجد أجور تُحتسب عليها ضريبة في هذه الفاتورة")
    cur = conn.execute(
        "INSERT INTO tax_debit_notes(invoice_id,note_date,vat_amount,created_by)"
        " VALUES(?,?,?,?)", (invoice_id, note_date, vat, username))
    note_id = cur.lastrowid
    note_no = f"TDN-{note_id:05d}"
    entry_id = post_entry(
        conn, note_date,
        f"إشعار مدين ضريبي {note_no} — تسوية لاحقة لفاتورة {inv['invoice_no']} "
        f"— {ent['name']}",
        [{"account_id": ent["account_id"], "cash_debit": vat,
          "line_desc": f"ضريبة مستحقة لاحقاً على {inv['invoice_no']}"},
         {"account_id": acc_id(conn, "2100"), "cash_credit": vat}],
        source_table="tax_debit_notes", source_id=note_id, username=username)
    conn.execute("UPDATE tax_debit_notes SET note_no=?, entry_id=? WHERE id=?",
                 (note_no, entry_id, note_id))
    log_action(conn, username, "create", "tax_debit_notes", note_id,
              f"{note_no} vat={vat}")
    return {"id": note_id, "note_no": note_no, "vat_amount": vat,
            "entry_id": entry_id, "invoice_no": inv["invoice_no"]}


def search_tax_debit_notes(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT n.*, i.invoice_no, e.name customer_name FROM tax_debit_notes n"
          " JOIN invoices i ON i.id=n.invoice_id"
          " JOIN entities e ON e.id=i.customer_id WHERE n.is_deleted=0")
    params = []
    if q:
        sql += " AND (n.note_no LIKE ? OR i.invoice_no LIKE ? OR e.name LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND n.note_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND n.note_date<=?"; params.append(date_to)
    sql += " ORDER BY n.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


# ═══════════ تسوية مباشرة على رصيد الجهة (بلا تدفق نقدي) ═══════════

ADJUST_ACCOUNT = "2900"     # تسويات مباشرة على أرصدة الجهات
VAT_ACCOUNT = "2100"        # ضريبة المخرجات


def create_direct_adjustment(conn, entity_id, amount, adj_date, username,
                             contra="adjust", direction="debit", notes=""):
    """إضافة مبلغ مباشر إلى رصيد الجهة النقدي دون ربطه بأي فاتورة سابقة.

    **لا يمس حساب الصندوق ولا البنك إطلاقاً** — فهو ليس تدفقاً نقدياً
    فعلياً بل قيد تسوية دفتري:

        زيادة مديونية الجهة (direction='debit'):
            من حـ/ الجهة                       مدين
                إلى حـ/ التسوية (2900 أو 2100)  دائن

        تخفيض مديونية الجهة (direction='credit'):
            من حـ/ التسوية (2900 أو 2100)      مدين
                إلى حـ/ الجهة                  دائن

    `contra`: "adjust" لحساب التسويات المخصص، أو "vat" لحساب الضريبة.
    """
    from models.entities import get_entity
    ent = get_entity(conn, entity_id)
    if not ent:
        raise ValueError("اختر الجهة")
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        raise ValueError("أدخل مبلغاً أكبر من صفر")
    if direction not in ("debit", "credit"):
        raise ValueError("اتجاه التسوية غير صحيح")
    code = VAT_ACCOUNT if contra == "vat" else ADJUST_ACCOUNT
    contra_id = acc_id(conn, code)
    if direction == "debit":          # يزيد رصيد الجهة المدين
        lines = [
            {"account_id": ent["account_id"], "cash_debit": amount,
             "line_desc": "تسوية مباشرة — زيادة الرصيد"},
            {"account_id": contra_id, "cash_credit": amount,
             "line_desc": "الطرف المقابل للتسوية"},
        ]
    else:                             # يخفّض رصيد الجهة
        lines = [
            {"account_id": contra_id, "cash_debit": amount,
             "line_desc": "الطرف المقابل للتسوية"},
            {"account_id": ent["account_id"], "cash_credit": amount,
             "line_desc": "تسوية مباشرة — تخفيض الرصيد"},
        ]
    cur = conn.execute(
        "INSERT INTO tax_debit_notes(invoice_id,note_no,note_date,base_amount,"
        "vat_amount,created_by) VALUES(NULL,?,?,?,?,?)",
        ("", adj_date, amount, 0.0, username))
    adj_id = cur.lastrowid
    note_no = f"ADJ-{adj_id:05d}"
    entry_id = post_entry(
        conn, adj_date, f"تسوية مباشرة {note_no} — {ent['name']}", lines,
        source_table="tax_debit_notes", source_id=adj_id,
        username=username, note=notes)
    conn.execute("UPDATE tax_debit_notes SET note_no=?, entry_id=? WHERE id=?",
                 (note_no, entry_id, adj_id))
    log_action(conn, username, "create", "tax_debit_notes", adj_id,
               f"direct adjustment {amount} {direction}")
    return {"id": adj_id, "note_no": note_no, "amount": amount,
            "direction": direction, "contra_code": code,
            "entry_id": entry_id}


def is_last_movement(conn, work_order_id, invoice_id):
    """هل هذه الفاتورة **آخر حركة زمنية** لهذا الطقم؟

    **لماذا هذا السؤال هو المفصل**: تعديل فاتورة قد يعني شيئين
    مختلفين تماماً:

      • إن كانت آخر حركة للطقم → التعديل يعكس الواقع الحالي.
        حذف الطقم منها يعني أنه لم يخرج أصلاً، فيجب أن يعود
        للخزنة فوراً ليُباع من جديد.

      • إن كانت حركة قديمة سبقتها حركات أحدث → التعديل تصحيح
        تاريخي بحت. حالة الطقم اليوم نتيجة **آخر** حركة لا هذه،
        فلمسها يفسد الواقع.

    المقارنة بالتاريخ أولاً ثم بالمعرّف: فاتورتان بنفس اليوم
    ترتيبهما بمعرّفهما، وهو ترتيب إصدارهما الفعلي.
    """
    me = conn.execute(
        "SELECT invoice_date, id FROM invoices WHERE id=?",
        (invoice_id,)).fetchone()
    if not me:
        return True
    later = conn.execute(
        "SELECT 1 FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " WHERE it.work_order_id=? AND i.is_deleted=0 AND i.id<>?"
        "   AND i.kind IN ('sale','sale_return')"
        "   AND (i.invoice_date > ? OR"
        "        (i.invoice_date = ? AND i.id > ?))"
        " LIMIT 1",
        (work_order_id, invoice_id, me["invoice_date"],
         me["invoice_date"], me["id"])).fetchone()
    return later is None


def update_invoice(conn, invoice_id, cart, username, apply_vat=None,
                   description=None, preserve_stock=True):
    """يعدّل فاتورة مُرحَّلة **في مكانها** — بلا فاتورة جديدة.

    **لماذا لا نعكس ونُعيد**: العكس يُنشئ فاتورة برقم جديد ووقت جديد،
    فيبدو للمراجع أن عمليتين وقعتا لا واحدة صُحّحت. والأصل المحاسبي
    أن تصحيح مستند لا يغيّر هويته: رقمه وتاريخه يبقيان دليلاً على
    زمن العملية الحقيقي.

    المنطق التفاضلي:

      • بند **بقي** بوزنه: لا يُمسّ
      • بند **تغيّر وزنه**: يُعدَّل، والفرق يُرحَّل
      • بند **أُضيف**: يُسجَّل في الفاتورة بوزنه
      • بند **حُذف**: يُرفع من الفاتورة

    والقيد يُعدَّل بالفرق الصافي وحده — فلا يتضخّم الدفتر بقيدين
    لعملية واحدة.

    ══ حركة المخزون: تُقرَّر **لكل طقم على حدة** ══

    السؤال الفاصل: هل هذه الفاتورة آخر حركة لهذا الطقم؟

      • **نعم** → التعديل يعكس الواقع. حذف الطقم يعيده للخزنة
        فوراً فيُباع من جديد، وإضافته تُخرجه.
      • **لا** (سبقتها حركات أحدث) → تصحيح تاريخي بحت. حالة
        الطقم اليوم نتيجة آخر حركة لا هذه، فلا تُمسّ.

    فالطقم الذي حُذف من فاتورته الأخيرة يصير متاحاً، والطقم الذي
    تحرّك بعدها يبقى حيث هو.

    ══ `preserve_stock` — تعطيل المعالجة الذكية ══

    تصحيح فاتورة **قديمة** لا يجوز أن يحرّك المخزون الحالي: الطقم
    الذي بيع في تلك الفاتورة قد بيع بعدها مرة أخرى، أو رُجّع، أو خرج
    لعميل آخر. إعادة ضبط حالته على ما كانت عليه يوم الفاتورة يفسد
    الواقع الحالي ويجعل النظام يعارض ما في الخزنة فعلاً.

    لذلك — وهو الافتراضي — يُصحَّح **الأثر المالي وحده**:
      ✔ بنود الفاتورة وأوزانها وأجورها
      ✔ إجمالي الفاتورة
      ✔ حساب الجهة والقيد (بالفرق الصافي)
      ✘ حالة الطقم (مباع/بالمخزن) — تبقى كما هي اليوم
      ✘ رصيد الرقم التجميعي — يبقى كما هو

    فالدفتر يصحّ، والمخزون يبقى على حقيقته. وإن أردت تحريك المخزون
    فعلاً فالأداة الصحيحة فاتورة جديدة أو تسوية وزن، لا تعديل مستند
    قديم.
    """
    inv = conn.execute(
        "SELECT * FROM invoices WHERE id=? AND is_deleted=0",
        (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة أو محذوفة")
    kind = inv["kind"]
    if kind not in ("sale", "sale_return"):
        raise ValueError("هذا النوع من الفواتير لا يُعدَّل في مكانه")
    if not cart:
        raise ValueError("أضف طقماً واحداً على الأقل")

    entity_id = inv["customer_id"]
    ent = get_entity(conn, entity_id)
    if not ent:
        raise ValueError("جهة الفاتورة غير موجودة")
    internal = ent["entity_type"] == "internal"
    vat = bool(inv["vat_applied"]) if apply_vat is None else bool(apply_vat)

    # الحالة الحالية: بنود الفاتورة كما هي
    old = {}
    for r in conn.execute(
            "SELECT it.*, w.work_order_no wno, w.is_bulk"
            " FROM invoice_items it"
            " JOIN work_orders w ON w.id=it.work_order_id"
            " WHERE it.invoice_id=?", (invoice_id,)):
        old[r["work_order_id"]] = dict(r)

    # لا تحقق من حالة الأطقم: الفاتورة قديمة وحالتها اليوم قد تكون
    # نتيجة عمليات لاحقة لا علاقة لها بها.
    all_ids = {c.get("work_order_id") for c in cart}
    new_lines = _fetch_cart_lines(
        conn, cart, kind,
        skip_ids=(all_ids if preserve_stock else set(old.keys())))
    # حالة الطقم بعد هذه الفاتورة وقبلها
    out_status = "sold" if kind == "sale" else "in_stock"
    back_status = "in_stock" if kind == "sale" else "sold"

    seen, added, updated, removed, touched = set(), [], [], [], []
    dw = 0.0          # صافي فرق الوزن
    dg = 0.0          # صافي فرق الأجور

    for li in new_lines:
        wo = li["wo"]
        wid = wo["id"]
        seen.add(wid)
        w = round(float(li["weight"] or 0), 3)
        wage = float(li["wage"] or 0)
        wages = gold_math.total_wages(wage, w) if not internal else 0.0
        prev = old.get(wid)

        if prev is None:
            conn.execute(
                "INSERT INTO invoice_items(invoice_id,work_order_id,"
                "registered_weight,wage_per_gram,wages)"
                " VALUES(?,?,?,?,?)",
                (invoice_id, wid, w, wage, wages))
            # بند مُضاف: يحرّك المخزون فقط إن كانت هذه الفاتورة آخر
            # حركة للطقم — وإلا فحالته اليوم نتيجة حركة أحدث.
            if preserve_stock and is_last_movement(conn, wid, invoice_id):
                if wo["is_bulk"]:
                    adjust_bulk_wo(
                        conn, w if kind == "sale_return" else -w, username)
                else:
                    conn.execute(
                        "UPDATE work_orders SET status=? WHERE id=?",
                        (out_status, wid))
                touched.append(wo["work_order_no"])
            dw += w
            dg += wages
            added.append(wo["work_order_no"])
            continue

        ow = round(float(prev["registered_weight"] or 0), 3)
        og = round(float(prev["wages"] or 0), 2)
        if abs(w - ow) < 0.001 and abs(wages - og) < 0.01:
            continue
        conn.execute(
            "UPDATE invoice_items SET registered_weight=?,"
            " wage_per_gram=?, wages=? WHERE id=?",
            (w, wage, wages, prev["id"]))
        if wo["is_bulk"] and preserve_stock \
                and is_last_movement(conn, wid, invoice_id):
            d = (w - ow)
            adjust_bulk_wo(
                conn, d if kind == "sale_return" else -d, username)
            touched.append(wo["work_order_no"])
        dw += (w - ow)
        dg += (wages - og)
        updated.append(wo["work_order_no"])

    for wid, prev in old.items():
        if wid in seen:
            continue
        ow = round(float(prev["registered_weight"] or 0), 3)
        og = round(float(prev["wages"] or 0), 2)
        # بند محذوف: يعود الطقم لحالته السابقة فقط إن كانت هذه
        # الفاتورة آخر حركة له — فيصير متاحاً للبيع فوراً.
        if preserve_stock and is_last_movement(conn, wid, invoice_id):
            if prev["is_bulk"]:
                adjust_bulk_wo(
                    conn, -ow if kind == "sale_return" else ow, username)
            else:
                conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                             (back_status, wid))
            touched.append(prev["wno"])
        conn.execute("DELETE FROM invoice_items WHERE id=?",
                     (prev["id"],))
        dw -= ow
        dg -= og
        removed.append(prev["wno"])

    dw = round(dw, 3)
    dg = round(dg, 2)
    if not (added or updated or removed):
        return {"id": invoice_id, "invoice_no": inv["invoice_no"],
                "added": [], "updated": [], "removed": [],
                "stock_touched": [],
                "delta_weight": 0.0, "delta_wages": 0.0,
                "entry_id": inv["entry_id"], "unchanged": True}

    # ── إجماليات الفاتورة: تُحسب من بنودها بعد التعديل ──
    # **لماذا لا نجمع الفروق**: `القديم + الفرق` يفترض أن إجمالي
    # الفاتورة كان مطابقاً لمجموع بنودها. فإن كان بينهما فرق لأي سبب
    # سابق، ورثه الإجمالي الجديد وتفاقم مع كل تعديل — فيظهر للمستخدم
    # وزن لا يطابق ما يراه في شاشة التعديل، ولو لم يمسّ الوزن أصلاً.
    # الحساب من البنود يجعل الإجمالي **هو** مجموعها بالتعريف، ويصحّح
    # أي انحراف سابق من تلقاء نفسه.
    row = conn.execute(
        "SELECT COALESCE(SUM(registered_weight),0) w,"
        " COALESCE(SUM(wages),0) g FROM invoice_items WHERE invoice_id=?",
        (invoice_id,)).fetchone()
    tw = round(float(row["w"] or 0), 3)
    tg = round(float(row["g"] or 0), 2)
    # والفرق المُرحَّل للقيد يُشتقّ من الإجمالي الجديد لا العكس، فيبقى
    # القيد موافقاً للفاتورة تماماً.
    dw = round(tw - float(inv["total_weight"] or 0), 3)
    dg = round(tg - float(inv["total_wages"] or 0), 2)
    dvat = round(gold_math.wages_vat(dg), 2) if vat else 0.0
    tvat = round(float(inv["vat_amount"] or 0) + dvat, 2)
    tgrand = round(tg + tvat, 2)
    conn.execute(
        "UPDATE invoices SET total_weight=?, total_wages=?,"
        " vat_amount=?, grand_total=?" +
        (", description=?" if description is not None else "") +
        " WHERE id=?",
        ((tw, tg, tvat, tgrand, description, invoice_id)
         if description is not None
         else (tw, tg, tvat, tgrand, invoice_id)))

    # ── تعديل القيد بالفرق الصافي ──
    _adjust_invoice_entry(conn, inv, kind, internal, dw, dg, dvat)

    # صفحة الفاتورة على الجوال صارت غير مطابقة لها: تُعلَّم لتُعاد
    # كتابتها عقب الترحيل. والرمز المطبوع لا يتغيّر — المسار نفسه
    # يُعاد رفعه، فورقة العميل تبقى صحيحة وتعرض الجديد.
    try:
        from services import invoice_share
        invoice_share.invalidate(conn, invoice_id)
    except Exception:
        pass

    log_action(conn, username, "update", "invoices", invoice_id,
               f"تعديل {inv['invoice_no']} في مكانه: +{len(added)} · "
               f"~{len(updated)} · -{len(removed)} · "
               f"وزن {dw:+.3f} · أجور {dg:+.2f}")
    return {"id": invoice_id, "invoice_no": inv["invoice_no"],
            "added": added, "updated": updated, "removed": removed,
            "stock_touched": sorted(set(touched)),
            "delta_weight": dw, "delta_wages": dg,
            "total_weight": tw, "total_wages": tg, "vat": tvat,
            "grand_total": tgrand, "entry_id": inv["entry_id"],
            "customer_name": ent["name"], "vat_applied": vat}


def _adjust_invoice_entry(conn, inv, kind, internal, dw, dg, dvat):
    """يضيف الفرق الصافي لأسطر قيد الفاتورة القائم.

    **المبدأ**: لا نفترض بنية أسطر معيّنة — نقرأ القيد كما هو ونزيد
    كل سطر **بنسبة حصته الحالية**. فالقيد يبقى بشكله الأصلي ويظل
    متوازناً بالضرورة، مهما اختلفت حسابات البيع عن المرتجع.

    السطر الذي يحمل وزناً يتحرّك بفرق الوزن، والذي يحمل نقداً يتحرّك
    بفرق الأجور — كلٌّ بإشارته الأصلية (مدين يبقى مديناً).
    """
    entry_id = inv["entry_id"]
    if not entry_id:
        raise ValueError("الفاتورة بلا قيد محاسبي — تعذّر التعديل")

    rows = [dict(r) for r in conn.execute(
        "SELECT id, gold_debit gd, gold_credit gc,"
        " cash_debit cd, cash_credit cc"
        " FROM journal_lines WHERE entry_id=?", (entry_id,))]
    if not rows:
        raise ValueError("قيد الفاتورة بلا أسطر — تعذّر التعديل")

    old_w = round(float(inv["total_weight"] or 0), 3)
    old_g = round(float(inv["total_wages"] or 0), 2)
    old_v = round(float(inv["vat_amount"] or 0), 2)
    old_cash = round(old_g + old_v, 2)
    new_cash = round(old_cash + dg + dvat, 2)

    # معامل التغيّر: نسبة الجديد للقديم في كل بُعد
    kw = ((old_w + dw) / old_w) if abs(old_w) > 1e-9 else None
    kc = (new_cash / old_cash) if abs(old_cash) > 1e-9 else None

    if kw is None and abs(dw) > 0.001:
        raise ValueError(
            "تعذّر تعديل وزن فاتورة رصيدها الأصلي صفر — "
            "احذف الفاتورة وأعد إدخالها")
    if kc is None and abs(dg + dvat) > 0.01:
        raise ValueError(
            "تعذّر تعديل أجور فاتورة أجورها الأصلية صفر — "
            "احذف الفاتورة وأعد إدخالها")

    for r in rows:
        gd, gc = float(r["gd"] or 0), float(r["gc"] or 0)
        cd, cc = float(r["cd"] or 0), float(r["cc"] or 0)
        if kw is not None:
            gd, gc = round(gd * kw, 3), round(gc * kw, 3)
        if kc is not None:
            cd, cc = round(cd * kc, 2), round(cc * kc, 2)
        conn.execute(
            "UPDATE journal_lines SET gold_debit=?, gold_credit=?,"
            " cash_debit=?, cash_credit=? WHERE id=?",
            (gd, gc, cd, cc, r["id"]))

    # التحقق: القيد ما زال متوازناً بعد التعديل
    chk = conn.execute(
        "SELECT ROUND(SUM(gold_debit-gold_credit),3) g,"
        " ROUND(SUM(cash_debit-cash_credit),2) c"
        " FROM journal_lines WHERE entry_id=?", (entry_id,)).fetchone()
    if abs(chk["g"] or 0) > 0.011 or abs(chk["c"] or 0) > 0.011:
        raise ValueError(
            f"اختلّ توازن القيد بعد التعديل "
            f"(ذهب {chk['g']} · نقد {chk['c']}) — أُلغيت العملية")
    # تعديلٌ مشروع لمبالغ قيدٍ قائم: يُوسَم ليُعاد ختمه في سلسلة
    # البصمات عند إغلاق المعاملة، وإلا ظهر التعديل السليم «عبثاً».
    try:
        from models import integrity
        integrity.mark(conn, entry_id)
    except Exception:
        pass
    return True
