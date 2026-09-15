# -*- coding: utf-8 -*-
"""السندات: تسديد ذهب (بتحويل العيار) ونقد وفرق الصافي والخصومات —
توجيه شامل: إلى (جهة تعامل: عميل/مورد/شريك/داخلي) أو (أي حساب مباشر
من شجرة الحسابات) — سداد الموردين يتم حصراً عبر سندات الصرف."""
from models.accounts import acc_id
from models.entities import get_entity
from models.inventory import BOX_CODE, add_scrap_move
from services import gold_math
from services.accounting_engine import post_entry
from services.audit import log_action


def _resolve_target(conn, entity_id, account_id):
    """يحلّ طرف السند إلى (account_id فعلي، تسمية عرض) — إما من جهة
    تعامل أو من حساب مباشر بالشجرة، أحدهما إلزامي."""
    if entity_id:
        ent = get_entity(conn, entity_id)
        if not ent:
            raise ValueError("اختر جهة تعامل صحيحة")
        return ent["account_id"], ent["name"]
    if account_id:
        row = conn.execute("SELECT id, code, name FROM accounts WHERE id=?",
                           (account_id,)).fetchone()
        if not row:
            raise ValueError("اختر حساباً صحيحاً")
        return row["id"], f"{row['code']} — {row['name']}"
    raise ValueError("اختر جهة تعامل أو حساباً مباشراً لتوجيه السند إليه")


def create_voucher(conn, kind, voucher_date, username, *,
                   entity_id=None, account_id=None,
                   gold_weight=0.0, gold_karat=18, cash_amount=0.0,
                   cash_account_code="1400", net_diff=0.0,
                   disc_cash=0.0, disc_gold=0.0, notes="", rows=None):
    """سند قبض/صرف يقبل **أسطراً متعددة** في السند الواحد.

    `rows`: قائمة أسطر مرنة تسمح بأعيرة مختلفة ونقد معاً، مثال:
        [{"kind": "gold", "weight": 100, "karat": 21, "notes": "كسر"},
         {"kind": "gold", "weight": 50,  "karat": 18},
         {"kind": "cash", "amount": 5000, "notes": "دفعة"}]

    وإن لم تُمرَّر `rows` يعمل بالمعاملات المفردة كما كان (توافق خلفي).
    """
    target_acc, target_label = _resolve_target(conn, entity_id, account_id)
    if kind not in ("receipt", "payment"):
        raise ValueError("نوع سند غير صحيح")

    # ── تطبيع الأسطر ──
    norm = []
    if rows:
        for r in rows:
            rk = (r.get("kind") or "gold").strip()
            note = (r.get("notes") or "").strip()
            if rk == "gold":
                wt = round(float(r.get("weight") or 0), 2)
                kt = int(r.get("karat") or 18)
                if wt <= 0:
                    continue
                if kt not in BOX_CODE:
                    raise ValueError(f"عيار غير مدعوم: {kt}")
                norm.append({"kind": "gold", "weight": wt, "karat": kt,
                             "equiv": gold_math.to_base_karat(wt, kt),
                             "amount": 0.0, "notes": note})
            else:
                amt = round(float(r.get("amount") or 0), 2)
                if amt <= 0:
                    continue
                norm.append({"kind": "cash", "weight": 0.0, "karat": 0,
                             "equiv": 0.0, "amount": amt, "notes": note})
        if not norm:
            raise ValueError("أضف سطراً واحداً على الأقل في السند")
        # إجماليات ترويسة السند
        gold_weight = round(sum(x["weight"] for x in norm
                                if x["kind"] == "gold"), 2)
        cash_amount = round(sum(x["amount"] for x in norm
                                if x["kind"] == "cash"), 2)
        golds = [x for x in norm if x["kind"] == "gold"]
        gold_karat = golds[0]["karat"] if golds else 18
    if gold_karat not in BOX_CODE:
        raise ValueError("العيار يجب أن يكون 18 أو 21 أو 24")
    for v in (gold_weight, cash_amount, disc_cash, disc_gold):
        if v < 0:
            raise ValueError("القيم لا تقبل السالب (فرق الصافي فقط يقبل الإشارة)")
    if not any((gold_weight, cash_amount, net_diff, disc_cash, disc_gold)):
        raise ValueError("أدخل قيمة واحدة على الأقل في السند")
    if kind == "payment" and (disc_cash or disc_gold):
        raise ValueError("الخصومات المسموحة تخص سندات القبض فقط")

    lines = []
    if norm:
        # كل سطر ذهب يُرحَّل لصندوق عياره الخاص
        equiv = round(sum(x["equiv"] for x in norm if x["kind"] == "gold"), 2)
        for x in norm:
            if x["kind"] == "gold":
                box = acc_id(conn, BOX_CODE[x["karat"]])
                d = (f"وزن فعلي {x['weight']:.2f} جم عيار {x['karat']}"
                     f" = {x['equiv']:.2f} جم عيار 18")
                if kind == "receipt":
                    lines += [{"account_id": box, "gold_debit": x["equiv"],
                               "line_desc": d},
                              {"account_id": target_acc,
                               "gold_credit": x["equiv"],
                               "line_desc": x["notes"] or "تسديد ذهب"}]
                else:
                    lines += [{"account_id": target_acc,
                               "gold_debit": x["equiv"],
                               "line_desc": x["notes"] or "صرف ذهب"},
                              {"account_id": box, "gold_credit": x["equiv"],
                               "line_desc": d}]
            else:
                cashbox = acc_id(conn, cash_account_code)
                if kind == "receipt":
                    lines += [{"account_id": cashbox,
                               "cash_debit": x["amount"]},
                              {"account_id": target_acc,
                               "cash_credit": x["amount"],
                               "line_desc": x["notes"] or "تسديد نقدي"}]
                else:
                    lines += [{"account_id": target_acc,
                               "cash_debit": x["amount"],
                               "line_desc": x["notes"] or "صرف نقدي"},
                              {"account_id": cashbox,
                               "cash_credit": x["amount"]}]
    else:
        equiv = (gold_math.to_base_karat(gold_weight, gold_karat)
                 if gold_weight else 0.0)
        if gold_weight:
            box = acc_id(conn, BOX_CODE[gold_karat])
            d = (f"وزن فعلي {gold_weight:.2f} جم عيار {gold_karat}"
                 f" = {equiv:.2f} جم عيار 18")
            if kind == "receipt":
                lines += [{"account_id": box, "gold_debit": equiv,
                           "line_desc": d},
                          {"account_id": target_acc, "gold_credit": equiv,
                           "line_desc": "تسديد ذهب"}]
            else:
                lines += [{"account_id": target_acc, "gold_debit": equiv,
                           "line_desc": "صرف ذهب"},
                          {"account_id": box, "gold_credit": equiv,
                           "line_desc": d}]
        if cash_amount:
            cashbox = acc_id(conn, cash_account_code)
            if kind == "receipt":
                lines += [{"account_id": cashbox, "cash_debit": cash_amount},
                          {"account_id": target_acc,
                           "cash_credit": cash_amount,
                           "line_desc": "تسديد نقدي"}]
            else:
                lines += [{"account_id": target_acc,
                           "cash_debit": cash_amount,
                           "line_desc": "صرف نقدي"},
                          {"account_id": cashbox,
                           "cash_credit": cash_amount}]

    if net_diff:
        diff_acc = acc_id(conn, "5600")
        if net_diff > 0:
            lines += [{"account_id": target_acc, "cash_debit": net_diff,
                       "line_desc": "فرق الصافي (زيادة)"},
                      {"account_id": diff_acc, "cash_credit": net_diff}]
        else:
            v = abs(net_diff)
            lines += [{"account_id": diff_acc, "cash_debit": v},
                      {"account_id": target_acc, "cash_credit": v,
                       "line_desc": "فرق الصافي (تخفيض)"}]

    if disc_cash:
        lines += [{"account_id": acc_id(conn, "5200"), "cash_debit": disc_cash},
                  {"account_id": target_acc, "cash_credit": disc_cash,
                   "line_desc": "خصم مسموح نقداً"}]
    if disc_gold:
        lines += [{"account_id": acc_id(conn, "5300"), "gold_debit": disc_gold},
                  {"account_id": target_acc, "gold_credit": disc_gold,
                   "line_desc": "خصم مسموح وزناً"}]

    label = "سند قبض" if kind == "receipt" else "سند صرف"
    cur = conn.execute(
        "INSERT INTO vouchers(kind,customer_id,target_account_id,voucher_date,"
        "gold_weight,gold_karat,gold_equiv18,cash_amount,cash_account_code,"
        "net_diff,disc_cash,disc_gold,notes,created_by)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, entity_id, target_acc, voucher_date, gold_weight, gold_karat,
         equiv, cash_amount, cash_account_code, net_diff, disc_cash, disc_gold,
         notes, username))
    v_id = cur.lastrowid
    v_no = f"V-{v_id:05d}"
    entry_id = post_entry(conn, voucher_date,
                          f"{label} {v_no} — {target_label}", lines,
                          source_table="vouchers", source_id=v_id,
                          username=username, note=notes)
    conn.execute("UPDATE vouchers SET voucher_no=?, entry_id=? WHERE id=?",
                 (v_no, entry_id, v_id))
    if norm:
        for x in norm:
            conn.execute(
                "INSERT INTO voucher_lines(voucher_id,line_kind,gold_weight,"
                "gold_karat,gold_equiv18,cash_amount,line_notes)"
                " VALUES(?,?,?,?,?,?,?)",
                (v_id, x["kind"], x["weight"], x["karat"] or 18, x["equiv"],
                 x["amount"], x["notes"]))
            if x["kind"] == "gold":
                delta = x["weight"] if kind == "receipt" else -x["weight"]
                add_scrap_move(conn, x["karat"], delta, "vouchers", v_id)
    else:
        if gold_weight:
            conn.execute(
                "INSERT INTO voucher_lines(voucher_id,line_kind,gold_weight,"
                "gold_karat,gold_equiv18) VALUES(?,'gold',?,?,?)",
                (v_id, gold_weight, gold_karat, equiv))
        if cash_amount:
            conn.execute(
                "INSERT INTO voucher_lines(voucher_id,line_kind,cash_amount)"
                " VALUES(?,'cash',?)", (v_id, cash_amount))
        if gold_weight:
            delta = gold_weight if kind == "receipt" else -gold_weight
            add_scrap_move(conn, gold_karat, delta, "vouchers", v_id)
    from services import sync_queue
    sync_queue.enqueue(conn, "voucher",
                       sync_queue.bundle_voucher(conn, v_id))
    log_action(conn, username, "create", "vouchers", v_id, v_no)
    return {"id": v_id, "voucher_no": v_no, "equiv18": equiv,
            "entry_id": entry_id, "target_label": target_label}


def recent_vouchers(conn, limit=20):
    return conn.execute(
        "SELECT v.*, COALESCE(e.name, a.code || ' — ' || a.name) target_label"
        " FROM vouchers v LEFT JOIN entities e ON e.id=v.customer_id"
        " JOIN accounts a ON a.id=v.target_account_id"
        " WHERE v.is_deleted=0 ORDER BY v.id DESC LIMIT ?", (limit,)).fetchall()


def search_vouchers(conn, kind=None, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT v.*, COALESCE(e.name, a.code || ' — ' || a.name) target_label"
          " FROM vouchers v LEFT JOIN entities e ON e.id=v.customer_id"
          " JOIN accounts a ON a.id=v.target_account_id WHERE v.is_deleted=0")
    params = []
    if kind:
        sql += " AND v.kind=?"; params.append(kind)
    if q:
        sql += " AND (v.voucher_no LIKE ? OR e.name LIKE ? OR a.name LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND v.voucher_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND v.voucher_date<=?"; params.append(date_to)
    sql += " ORDER BY v.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


def voucher_lines(conn, voucher_id):
    """أسطر السند التفصيلية (أعيرة متعددة ونقد)."""
    return conn.execute(
        "SELECT * FROM voucher_lines WHERE voucher_id=? ORDER BY id",
        (voucher_id,)).fetchall()


def update_voucher(conn, voucher_id, username, kind=None, entity_id=None,
                   account_id=None, rows=None, gold_weight=0.0,
                   gold_karat=18, cash_amount=0.0, cash_account_code=None,
                   net_diff=0.0, disc_cash=0.0, disc_gold=0.0, notes=""):
    """يعدّل سنداً مُرحَّلاً **في مكانه** — بنفس رقمه وتاريخه.

    **لماذا لا نعكس ونُعيد**: العكس يُنشئ سنداً برقم ووقت جديدين،
    فيبدو للمراجع أن سندين صدرا لا سنداً صُحّح. والأصل المحاسبي أن
    تصحيح مستند لا يغيّر هويته.

    **كيف**: تُحذف أسطر السند وأثرها الوزني، ثم تُبنى الأسطر الجديدة
    وقيدها، ويُستبدل محتوى القيد القائم بها — فيبقى رقم السند
    وتاريخه ومعرّف قيده كما هي.
    """
    v = conn.execute(
        "SELECT * FROM vouchers WHERE id=? AND is_deleted=0",
        (voucher_id,)).fetchone()
    if not v:
        raise ValueError("السند غير موجود أو محذوف")
    entry_id = v["entry_id"]
    if not entry_id:
        raise ValueError("السند بلا قيد محاسبي — تعذّر التعديل")

    kind = kind or v["kind"]
    # صندوق النقد يُورَّث من السند الأصلي إن لم يُمرَّر صراحةً
    if not cash_account_code:
        cash_account_code = (v["cash_account_code"]
                             if "cash_account_code" in v.keys() else None) \
            or "1400"

    # ── عكس الأثر الوزني للأسطر القديمة ──
    for ln in conn.execute(
            "SELECT * FROM voucher_lines WHERE voucher_id=?",
            (voucher_id,)):
        if ln["line_kind"] == "gold" and (ln["gold_weight"] or 0):
            back = (-(ln["gold_weight"] or 0) if v["kind"] == "receipt"
                    else (ln["gold_weight"] or 0))
            add_scrap_move(conn, int(ln["gold_karat"] or 18), back,
                           "vouchers", voucher_id)
    conn.execute("DELETE FROM voucher_lines WHERE voucher_id=?",
                 (voucher_id,))

    # ── بناء السند الجديد في سجل مؤقّت ثم نقل محتواه ──
    tmp = create_voucher(
        conn, kind, v["voucher_date"], username, entity_id=entity_id,
        account_id=account_id, rows=rows, gold_weight=gold_weight,
        gold_karat=gold_karat, cash_amount=cash_amount,
        cash_account_code=cash_account_code, net_diff=net_diff,
        disc_cash=disc_cash, disc_gold=disc_gold, notes=notes)

    # أسطر السند تنتقل للسند الأصلي
    conn.execute("UPDATE voucher_lines SET voucher_id=? WHERE voucher_id=?",
                 (voucher_id, tmp["id"]))
    conn.execute("UPDATE scrap_moves SET ref_id=?"
                 " WHERE ref_table='vouchers' AND ref_id=?",
                 (voucher_id, tmp["id"]))

    # أسطر القيد تنتقل للقيد الأصلي، ويُحذف القيد المؤقّت.
    # الترتيب مهم: يُفكّ مرجع السند المؤقّت للقيد أولاً، وإلا رفض
    # القيد المرجعي حذفه.
    desc = conn.execute(
        "SELECT description FROM journal_entries WHERE id=?",
        (tmp["entry_id"],)).fetchone()["description"]
    # رأس السند المؤقّت يحمل القيم المحسوبة (الحساب المستهدف
    # والمكافئ والنقد) — ننسخها قبل حذفه.
    src = conn.execute("SELECT * FROM vouchers WHERE id=?",
                       (tmp["id"],)).fetchone()
    conn.execute("DELETE FROM journal_lines WHERE entry_id=?", (entry_id,))
    conn.execute("UPDATE journal_lines SET entry_id=? WHERE entry_id=?",
                 (entry_id, tmp["entry_id"]))
    conn.execute("UPDATE journal_entries SET description=? WHERE id=?",
                 (desc, entry_id))
    conn.execute("UPDATE vouchers SET entry_id=NULL WHERE id=?",
                 (tmp["id"],))
    conn.execute("DELETE FROM vouchers WHERE id=?", (tmp["id"],))
    conn.execute("DELETE FROM journal_entries WHERE id=?",
                 (tmp["entry_id"],))

    # رأس السند يتحدّث بالقيم الجديدة — بلا رقمه وتاريخه
    conn.execute(
        "UPDATE vouchers SET kind=?, customer_id=?, target_account_id=?,"
        " gold_weight=?, gold_karat=?, gold_equiv18=?, cash_amount=?,"
        " cash_account_code=?, net_diff=?, disc_cash=?, disc_gold=?,"
        " notes=? WHERE id=?",
        (src["kind"], src["customer_id"], src["target_account_id"],
         src["gold_weight"], src["gold_karat"], src["gold_equiv18"],
         src["cash_amount"], src["cash_account_code"],
         src["net_diff"], src["disc_cash"], src["disc_gold"],
         src["notes"], voucher_id))

    # ── حارس التوازن ──
    chk = conn.execute(
        "SELECT ROUND(SUM(gold_debit-gold_credit),3) g,"
        " ROUND(SUM(cash_debit-cash_credit),2) c"
        " FROM journal_lines WHERE entry_id=?", (entry_id,)).fetchone()
    if abs(chk["g"] or 0) > 0.011 or abs(chk["c"] or 0) > 0.011:
        raise ValueError(
            f"اختلّ توازن القيد بعد التعديل "
            f"(ذهب {chk['g']} · نقد {chk['c']}) — أُلغيت العملية")

    log_action(conn, username, "update", "vouchers", voucher_id,
               f"تعديل {v['voucher_no']} في مكانه — الرقم والتاريخ ثابتان")
    return {"id": voucher_id, "voucher_no": v["voucher_no"],
            "entry_id": entry_id, "kind": kind,
            "target_label": tmp.get("target_label", ""),
            "in_place": True}
