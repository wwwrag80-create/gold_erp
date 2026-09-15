# -*- coding: utf-8 -*-
"""قائمة الأرباح والخسائر: الإيرادات النقدية − المصروفات النقدية −
تقييم البنود الوزنية (خسائر تشغيل الذهب وغيرها) بسعر الجرام المُدخل."""
from services.accounting_engine import account_balance


def income_statement(conn, date_from, date_to, gram_price):
    revenue_rows, revenue = [], 0.0
    for a in conn.execute("SELECT id, code, name FROM accounts"
                          " WHERE is_postable=1 AND type='revenue'"
                          " ORDER BY code"):
        _, c = account_balance(conn, a["id"], date_from, date_to)
        amt = round(-c, 2)  # الإيراد رصيده دائن
        if amt:
            revenue_rows.append((f"{a['code']} — {a['name']}", amt))
            revenue = round(revenue + amt, 2)

    cash_rows, cash_total = [], 0.0
    gold_rows, gold_total, loss_grams = [], 0.0, 0.0
    for a in conn.execute("SELECT id, code, name FROM accounts"
                          " WHERE is_postable=1 AND type='expense'"
                          " ORDER BY code"):
        g, c = account_balance(conn, a["id"], date_from, date_to)
        label = f"{a['code']} — {a['name']}"
        if c:
            cash_rows.append((label, round(c, 2)))
            cash_total = round(cash_total + c, 2)
        if g:
            gold_rows.append((label, round(g, 3)))
            gold_total = round(gold_total + g, 3)
            if a["code"].startswith("51"):  # مجموعة خسائر تشغيل الذهب
                loss_grams = round(loss_grams + g, 3)
    valuation = round(gold_total * gram_price, 2)
    net = round(revenue - cash_total - valuation, 2)
    return {"revenue_rows": revenue_rows, "revenue": revenue,
            "cash_rows": cash_rows, "cash_total": cash_total,
            "gold_rows": gold_rows, "gold_total": gold_total,
            "loss_grams": loss_grams, "gram_price": gram_price,
            "valuation": valuation, "net": net}


def khazina_production_report(conn, date_from, date_to):
    """مطابقة خزينة التصنيع: المدخلات (ذهب من الصب/الكسر + فصوص وأحجار
    عبر قيود اليومية) مقابل المخرجات (الوزن المقيد للأطقم المُنتَجة فقط
    — دون احتساب الفاقد/التسويات ضمن هذا الرقم)."""
    khazina_id = conn.execute(
        "SELECT id FROM accounts WHERE code='1100'").fetchone()["id"]
    jewel_row = conn.execute("SELECT id FROM accounts WHERE code='1150'").fetchone()
    jewel_id = jewel_row["id"] if jewel_row else None

    opening = conn.execute(
        "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) v"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0 AND l.account_id=? AND e.entry_date<?",
        (khazina_id, date_from)).fetchone()["v"]

    debit_lines = conn.execute(
        "SELECT l.gold_debit gd, l.entry_id, e.description, e.entry_date"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0 AND l.account_id=? AND l.gold_debit>0"
        " AND e.entry_date BETWEEN ? AND ?",
        (khazina_id, date_from, date_to)).fetchall()

    gold_in, jewels_in = 0.0, 0.0
    gold_lines, jewel_lines = [], []
    for r in debit_lines:
        is_jewel = jewel_id and conn.execute(
            "SELECT 1 FROM journal_lines WHERE entry_id=? AND account_id=?"
            " AND gold_credit>0", (r["entry_id"], jewel_id)).fetchone()
        if is_jewel:
            jewels_in += r["gd"]
            jewel_lines.append(r)
        else:
            gold_in += r["gd"]
            gold_lines.append(r)

    out_row = conn.execute(
        "SELECT COALESCE(SUM(l.gold_credit),0) w, COUNT(DISTINCT e.id) n"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0 AND l.account_id=? AND e.source_table='work_orders'"
        " AND e.entry_date BETWEEN ? AND ?",
        (khazina_id, date_from, date_to)).fetchone()

    closing = account_balance(conn, khazina_id, date_to=date_to)[0]
    gold_in, jewels_in = round(gold_in, 3), round(jewels_in, 3)
    total_in = round(gold_in + jewels_in, 3)
    produced_out = round(out_row["w"], 3)
    other = round(closing - opening - total_in + produced_out, 3)
    return {"opening": round(opening, 3), "gold_in": gold_in,
            "jewels_in": jewels_in, "total_in": total_in,
            "produced_out": produced_out,
            "production_entries": out_row["n"], "closing": round(closing, 3),
            "other": other, "gold_lines": gold_lines, "jewel_lines": jewel_lines}


def _group_map(conn):
    """يربط كل حساب بمجموعته الرئيسية (المستوى الثاني) لتصنيف القائمة."""
    rows = conn.execute("SELECT id, code, parent_id FROM accounts").fetchall()
    by_id = {r["id"]: r for r in rows}

    def group_code(aid):
        seen = set()
        cur = by_id.get(aid)
        last = cur["code"] if cur else None
        while cur and cur["parent_id"] and cur["id"] not in seen:
            seen.add(cur["id"])
            parent = by_id.get(cur["parent_id"])
            if not parent or not parent["parent_id"]:
                return cur["code"]      # المستوى الثاني تحت الجذر
            last, cur = cur["code"], parent
        return last
    return {r["id"]: group_code(r["id"]) for r in rows}


DIRECT_GROUPS = {"5050"}
ADMIN_GROUPS = {"5800"}


def income_statement_full(conn, date_from, date_to, gram_price):
    """قائمة دخل مبوَّبة: إيرادات → مجمل الربح → تكاليف تشغيل مباشرة →
    مصاريف إدارية وعمومية → مصروفات أخرى → صافي الربح/الخسارة."""
    groups = _group_map(conn)
    revenue_rows, revenue = [], 0.0
    for a in conn.execute("SELECT id, code, name FROM accounts"
                          " WHERE is_postable=1 AND type='revenue' ORDER BY code"):
        g, c = account_balance(conn, a["id"], date_from, date_to)
        amt = round(-c, 2)
        gold_amt = round(-g, 3)
        if amt or gold_amt:
            revenue_rows.append((f"{a['code']} — {a['name']}", amt, gold_amt))
            revenue = round(revenue + amt, 2)

    direct, admin, other = [], [], []
    d_tot = a_tot = o_tot = 0.0
    gold_rows, gold_total, loss_grams = [], 0.0, 0.0
    for a in conn.execute("SELECT id, code, name FROM accounts"
                          " WHERE is_postable=1 AND type='expense' ORDER BY code"):
        g, c = account_balance(conn, a["id"], date_from, date_to)
        label = f"{a['code']} — {a['name']}"
        grp = groups.get(a["id"])
        if c:
            if grp in DIRECT_GROUPS:
                direct.append((label, round(c, 2))); d_tot = round(d_tot + c, 2)
            elif grp in ADMIN_GROUPS:
                admin.append((label, round(c, 2))); a_tot = round(a_tot + c, 2)
            else:
                other.append((label, round(c, 2))); o_tot = round(o_tot + c, 2)
        if g:
            gold_rows.append((label, round(g, 3)))
            gold_total = round(gold_total + g, 3)
            if a["code"].startswith("51"):
                loss_grams = round(loss_grams + g, 3)

    # الإيرادات الوزنية (أرباح فروقات الجرد) تُقيَّم أيضاً بسعر الجرام
    revenue_gold = round(sum(r[2] for r in revenue_rows), 3)
    gold_net = round(gold_total - revenue_gold, 3)
    valuation = round(gold_net * gram_price, 2)
    gross_profit = round(revenue - d_tot, 2)
    net = round(gross_profit - a_tot - o_tot - valuation, 2)
    return {"revenue_rows": revenue_rows, "revenue": revenue,
            "direct_rows": direct, "direct_total": d_tot,
            "admin_rows": admin, "admin_total": a_tot,
            "other_rows": other, "other_total": o_tot,
            "gold_rows": gold_rows, "gold_total": gold_total,
            "revenue_gold": revenue_gold, "gold_net": gold_net,
            "loss_grams": loss_grams, "gram_price": gram_price,
            "valuation": valuation, "gross_profit": gross_profit, "net": net}


def vat_return(conn, date_from, date_to):
    """الإقرار الضريبي: ضريبة المخرجات (مبيعات) − ضريبة المدخلات
    (مشتريات) = المستحق للهيئة أو المسترد للمصنع."""
    out_acc = conn.execute("SELECT id FROM accounts WHERE code='2100'").fetchone()
    in_acc = conn.execute("SELECT id FROM accounts WHERE code='1900'").fetchone()
    output_vat = round(-account_balance(conn, out_acc["id"], date_from, date_to)[1], 2) \
        if out_acc else 0.0
    input_vat = round(account_balance(conn, in_acc["id"], date_from, date_to)[1], 2) \
        if in_acc else 0.0

    s = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='sale' THEN total_wages"
        " ELSE -total_wages END),0) base,"
        " COALESCE(SUM(CASE WHEN kind='sale' THEN vat_amount"
        " ELSE -vat_amount END),0) vat, COUNT(*) n"
        " FROM invoices WHERE is_deleted=0 AND vat_applied=1"
        " AND invoice_date BETWEEN ? AND ?", (date_from, date_to)).fetchone()
    p = conn.execute(
        "SELECT COALESCE(SUM(amount),0) base, COALESCE(SUM(vat_amount),0) vat,"
        " COUNT(*) n FROM purchases WHERE is_deleted=0 AND vat_amount>0"
        " AND purchase_date BETWEEN ? AND ?", (date_from, date_to)).fetchone()
    # ملاحظة: إشعارات المدين الضريبي (تسوية لاحقة) تُقيَّد مباشرة على
    # حساب 2100 فتدخل تلقائياً ضمن output_vat أعلاه دون ازدواج — نعرضها
    # هنا فقط للشفافية والتفصيل.
    tdn = conn.execute(
        "SELECT COALESCE(SUM(vat_amount),0) vat, COUNT(*) n"
        " FROM tax_debit_notes WHERE is_deleted=0"
        " AND note_date BETWEEN ? AND ?", (date_from, date_to)).fetchone()

    net = round(output_vat - input_vat, 2)
    return {"date_from": date_from, "date_to": date_to,
            "sales_base": round(s["base"], 2), "sales_vat": round(s["vat"], 2),
            "sales_count": s["n"], "output_vat": output_vat,
            "purchases_base": round(p["base"], 2),
            "purchases_vat": round(p["vat"], 2), "purchases_count": p["n"],
            "input_vat": input_vat, "tdn_vat": round(tdn["vat"], 2),
            "tdn_count": tdn["n"], "net": net,
            "status": "مستحق الدفع لهيئة الزكاة والضريبة والجمارك" if net > 0
                      else ("مبلغ مسترد للمنشأة" if net < 0 else "لا مستحقات")}


def production_inputs_summary(conn, date_from, date_to):
    """ملخص مدخلات الإنتاج من أوامر التشغيل خلال الفترة:
    إجمالي أوزان الذهب الصافي، والفصوص (الأحجار الصغيرة)، والأحجار
    (الكبيرة). أرقام دقيقة تُبنى مباشرة من مدخلات أوامر التشغيل."""
    r = conn.execute(
        "SELECT COALESCE(SUM(w.gold_weight),0) gold,"
        " COALESCE(SUM(w.small_stones),0) jewels,"
        " COALESCE(SUM(w.big_stones),0) stones,"
        " COUNT(*) n"
        " FROM work_orders w LEFT JOIN journal_entries e ON e.id=w.entry_id"
        " WHERE w.is_deleted=0"
        " AND COALESCE(e.entry_date, substr(w.created_at,1,10))"
        "     BETWEEN ? AND ?", (date_from, date_to)).fetchone()
    return {"gold": round(r["gold"], 3), "jewels": round(r["jewels"], 3),
            "stones": round(r["stones"], 3), "count": r["n"]}


def khazina_tiles(conn, date_from, date_to):
    """لوحات مراقبة خزينة التصنيع الأربع — أرقام إجمالية لحظية للفترة."""
    r = khazina_production_report(conn, date_from, date_to)
    # لوحة فاقد الذهب تعكس **فقط** الفاقد التشغيلي للتصنيع والخياس من
    # واقع تقرير مدير التصنيع (5110). الفاقد الفني للصب (5120) عملية
    # مستقلة عن الورشة ولا تُدمج هنا إطلاقاً.
    loss = 0.0
    row = conn.execute("SELECT id FROM accounts WHERE code='5110'").fetchone()
    if row:
        loss = round(account_balance(conn, row["id"], date_from, date_to)[0], 3)
    return {
        "production": r["produced_out"],
        "production_entries": r["production_entries"],
        "gold_loss": loss,
        "jewels_in": r["jewels_in"],
        "gold_in": r["gold_in"],
        "opening": r["opening"], "closing": r["closing"], "other": r["other"],
        "total_in": r["total_in"],
    }


def income_statement_cashflow(conn, date_from, date_to):
    """قائمة دخل قائمة على التدفقات الفعلية حصراً (لا الاستحقاق):

    * الإيرادات = الأجور والذهب **المقبوضة** من كل سندات القبض.
    * المصروفات = الأجور النقدية **المصروفة** من كل سندات الصرف.
    * صافي الربح مفصول إلى (صافي ربح الأجور) و (صافي ربح الذهب).

    سندات القبض (receipt) تمثّل تدفقاً داخلاً، والصرف (payment) خارجاً.
    """
    rec = conn.execute(
        "SELECT COALESCE(SUM(cash_amount),0) cash,"
        " COALESCE(SUM(gold_equiv18),0) gold, COUNT(*) n"
        " FROM vouchers WHERE kind='receipt' AND is_deleted=0"
        " AND voucher_date BETWEEN ? AND ?",
        (date_from, date_to)).fetchone()
    pay = conn.execute(
        "SELECT COALESCE(SUM(cash_amount),0) cash,"
        " COALESCE(SUM(gold_equiv18),0) gold, COUNT(*) n"
        " FROM vouchers WHERE kind='payment' AND is_deleted=0"
        " AND voucher_date BETWEEN ? AND ?",
        (date_from, date_to)).fetchone()

    rev_cash = round(rec["cash"], 2)      # الأجور المقبوضة
    rev_gold = round(rec["gold"], 3)      # الذهب المقبوض
    exp_cash = round(pay["cash"], 2)      # الأجور المصروفة (إدارية وعمومية)
    exp_gold = round(pay["gold"], 3)      # الذهب المصروف

    net_wages = round(rev_cash - exp_cash, 2)     # صافي ربح الأجور
    net_gold = round(rev_gold - exp_gold, 3)      # صافي ربح الذهب

    return {
        "revenue_cash": rev_cash, "revenue_gold": rev_gold,
        "receipts_count": rec["n"],
        "total_revenue_cash": rev_cash, "total_revenue_gold": rev_gold,
        "expense_cash": exp_cash, "expense_gold": exp_gold,
        "payments_count": pay["n"],
        "total_expense_cash": exp_cash, "total_expense_gold": exp_gold,
        "net_wages": net_wages, "net_gold": net_gold,
    }


# ═══════════════ الميزانية العمومية ثنائية البعد ═══════════════

def _subtree_ids(conn, code):
    """كل معرّفات الحسابات تحت كود معيّن (الحساب نفسه وفروعه بأي عمق)."""
    root = conn.execute("SELECT id FROM accounts WHERE code=?",
                        (code,)).fetchone()
    if not root:
        return []
    ids, frontier = [root["id"]], [root["id"]]
    while frontier:
        qs = ",".join("?" * len(frontier))
        kids = [r["id"] for r in conn.execute(
            f"SELECT id FROM accounts WHERE parent_id IN ({qs})",
            frontier).fetchall()]
        ids += kids
        frontier = kids
    return ids


def _group_balance(conn, codes, date_to=None):
    """رصيد مجموعة حسابات (الحساب وكل فروعه) نقداً وذهباً.

    يُستخدم شجرة الحسابات لا بادئات الأكواد، لأن حسابات الجهات تُنشأ
    كفروع (1601، 1602 …) وقد لا تطابق البادئة النصية للأب.
    """
    ids = []
    for c in codes:
        ids += _subtree_ids(conn, c)
    ids = list(dict.fromkeys(ids))
    if not ids:
        return (0.0, 0.0)
    qs = ",".join("?" * len(ids))
    params = list(ids)
    sql = ("SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
           " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
           " FROM journal_lines l"
           " JOIN journal_entries e ON e.id=l.entry_id"
           f" WHERE l.account_id IN ({qs}) AND e.is_deleted=0")
    if date_to:
        sql += " AND e.entry_date<=?"
        params.append(date_to)
    r = conn.execute(sql, params).fetchone()
    return (round(r["g"], 3), round(r["c"], 2))


def balance_sheet(conn, date_to=None, date_from=None):
    """الميزانية العمومية ثنائية البعد: كل بند بعمودين (نقد/أجور) و(ذهب).

    مبنية على أرصدة دفتر الأستاذ الفعلية لا على التدفقات، لأن معادلة
    الميزانية محاسبية بحتة:

        الأصول = الخصوم + حقوق الملكية + صافي نتيجة النشاط

    ملاحظة مهمة: حسابات الجهات (عملاء/موردون) قد تكون مدينة أو دائنة
    فعلياً؛ فتُصنَّف بحسب **إشارة رصيدها الحقيقي** لا بحسب نوعها
    الاسمي — العميل ذو الرصيد الدائن يظهر ضمن الالتزامات، والمورد ذو
    الرصيد المدين يظهر ضمن الأصول. وهذا هو العرض الصحيح في مصانع
    الذهب حيث يودع العميل ذهباً لدى المصنع.
    """
    dt = date_to or "2999-12-31"
    df = date_from or "1900-01-01"

    def bal(codes):
        return _group_balance(conn, codes, dt)

    # ── أصول ثابتة القيد (تبقى أصولاً دائماً) ──
    boxes_g, boxes_c = bal(["1400", "1410", "1500"])
    vault_g, vault_c = bal(["1100", "1150", "1200", "1250", "1300", "1350"])
    # سلف الموظفين والعمال والعهد — كلها أصول متداولة
    emp_g, emp_c = bal(["1950", "1960", "1970"])
    fixed_g, fixed_c = bal(["1700"])
    # حساب جسر التسكير (6100): يحمل رصيدي ذهب ونقد متقابلين أثناء
    # عمليات التسكير. إغفاله يجعل الميزانية تبدو غير متوازنة رغم
    # سلامة القيود، فيُدرج ضمن الأصول بإشارته الطبيعية.
    bridge_g, bridge_c = bal(["6100"])
    vat_in_g, vat_in_c = bal(["1900"])

    # ── حسابات الجهات: تُقسَّم بحسب إشارة رصيد كل حساب فرعي ──
    def split_parties(parent_codes):
        """يفصل الأرصدة المدينة (أصول) عن الدائنة (خصوم) لكل جهة."""
        ids = []
        for c in parent_codes:
            ids += _subtree_ids(conn, c)
        ids = list(dict.fromkeys(ids))
        if not ids:
            return (0.0, 0.0, 0.0, 0.0)
        qs = ",".join("?" * len(ids))
        rows = conn.execute(
            "SELECT l.account_id,"
            " ROUND(SUM(l.gold_debit-l.gold_credit),3) g,"
            " ROUND(SUM(l.cash_debit-l.cash_credit),2) c"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            f" WHERE l.account_id IN ({qs}) AND e.is_deleted=0"
            " AND e.entry_date<=? GROUP BY l.account_id",
            ids + [dt]).fetchall()
        dg = dc = cg = cc = 0.0
        for r in rows:
            if (r["g"] or 0) > 0:
                dg += r["g"]
            else:
                cg += -r["g"]
            if (r["c"] or 0) > 0:
                dc += r["c"]
            else:
                cc += -r["c"]
        return (round(dg, 3), round(dc, 2), round(cg, 3), round(cc, 2))

    cust_dg, cust_dc, cust_cg, cust_cc = split_parties(["1600", "1650"])
    sup_dg, sup_dc, sup_cg, sup_cc = split_parties(["2300"])

    assets = [
        ("الصناديق والبنوك", boxes_c, boxes_g),
        ("الخزائن (ذهب خام ومشغول وفصوص)", vault_c, vault_g),
        ("أرصدة العملاء المدينة", cust_dc, cust_dg),
        ("أرصدة موردين مدينة (دفعات مقدمة)", sup_dc, sup_dg),
        ("سلف وعهد الموظفين", emp_c, emp_g),
        ("الأصول الثابتة", fixed_c, fixed_g),
        ("ضريبة المدخلات", vat_in_c, vat_in_g),
        ("مركز التسكير (ذهب ↔ نقد)", bridge_c, bridge_g),
    ]
    ta_c = round(sum(x[1] for x in assets), 2)
    ta_g = round(sum(x[2] for x in assets), 3)

    accr_g, accr_c = bal(["2200", "2900"])
    vat_out_g, vat_out_c = bal(["2100", "2150"])

    liabilities = [
        ("أرصدة الموردين الدائنة", sup_cc, sup_cg),
        ("أرصدة العملاء الدائنة (ذهب/نقد لدينا لهم)", cust_cc, cust_cg),
        ("مستحقات وتسويات", round(-accr_c, 2), round(-accr_g, 3)),
        ("الالتزامات الضريبية", round(-vat_out_c, 2), round(-vat_out_g, 3)),
    ]
    tl_c = round(sum(x[1] for x in liabilities), 2)
    tl_g = round(sum(x[2] for x in liabilities), 3)

    # ── حقوق الملكية (أرصدة دائنة تُعرض موجبة) ──
    cap_g, cap_c = bal(["3110"])
    part_g, part_c = bal(["3120"])
    ret_g, ret_c = bal(["3200"])
    cur_g, cur_c = bal(["3210"])
    susp_g, susp_c = bal(["3900"])

    # صافي نتيجة النشاط من حسابات الإيراد والمصروف الفعلية
    rev_g, rev_c = bal(["4000"])
    exp_g, exp_c = bal(["5000"])
    net_c = round(-rev_c - exp_c, 2)      # الإيراد دائن (سالب) والمصروف مدين
    net_g = round(-rev_g - exp_g, 3)

    equity = [
        ("رأس المال", round(-cap_c, 2), round(-cap_g, 3)),
        ("جاري الشركاء", round(-part_c, 2), round(-part_g, 3)),
        ("الأرباح المحتجزة", round(-ret_c, 2), round(-ret_g, 3)),
        ("أرباح وخسائر العام الحالي", round(-cur_c, 2), round(-cur_g, 3)),
        ("الأرصدة الافتتاحية", round(-susp_c, 2), round(-susp_g, 3)),
        ("صافي نتيجة النشاط (إيرادات − مصروفات)", net_c, net_g),
    ]
    te_c = round(sum(x[1] for x in equity), 2)
    te_g = round(sum(x[2] for x in equity), 3)

    diff_c = round(ta_c - (tl_c + te_c), 2)
    diff_g = round(ta_g - (tl_g + te_g), 3)

    # قائمة الدخل بنموذج التصريف تُعرض إعلامياً بجانب الميزانية:
    # صافي الربح النقدي وصافي فاقد الذهب — كما تظهر في شاشة قائمة الدخل.
    cons = income_statement_consignment(conn, df, dt)

    return {
        "assets": assets, "total_assets": (ta_c, ta_g),
        "liabilities": liabilities, "total_liabilities": (tl_c, tl_g),
        "equity": equity, "total_equity": (te_c, te_g),
        "diff_cash": diff_c, "diff_gold": diff_g,
        "balanced_cash": abs(diff_c) < 0.011,
        "balanced_gold": abs(diff_g) < 0.011,
        "net_income": (net_c, net_g),
        "consignment_net_cash": cons["net_profit_cash"],
        "consignment_gold_loss": cons["net_gold_movement"],
    }


def income_statement_consignment(conn, date_from, date_to):
    """قائمة الدخل بنموذج «تسليم البضاعة للتصريف» — عمودان: نقد ووزن.

    منطق مصنع الذهب حيث تُسلَّم البضاعة للتصريف:

    * **الإيراد النقدي الحقيقي** = صافي أجور المبيعات
      (أجور فواتير البيع − أجور فواتير المرتجعات).
    * **صافي الذهب المباع** (وزناً) = وزن المبيعات − وزن المرتجعات،
      للعرض فقط أعلى الشاشة (انتقال أصل من مخزون إلى ذمم، لا ربح/خسارة).
    * **فاقد الذهب العيني** = الفاقد الفني للصب (5120) + الفاقد
      التشغيلي للتصنيع (5110)، يمثّل العجز العيني الحقيقي.
    * **المصروفات النقدية** = إجمالي المدفوع عبر كل سندات الصرف.

    النتيجة:
        صافي الربح النقدي = صافي أجور المبيعات − المصروفات التشغيلية.
        صافي حركة الذهب العينية = − إجمالي فاقد الذهب (عجز عيني).
    """
    # ── المبيعات والمرتجعات (أجوراً ووزناً) ──
    sales = conn.execute(
        "SELECT COALESCE(SUM(total_wages),0) wages,"
        " COALESCE(SUM(total_weight),0) weight, COUNT(*) n"
        " FROM invoices WHERE kind='sale' AND is_deleted=0"
        " AND invoice_date BETWEEN ? AND ?", (date_from, date_to)).fetchone()
    returns = conn.execute(
        "SELECT COALESCE(SUM(total_wages),0) wages,"
        " COALESCE(SUM(total_weight),0) weight, COUNT(*) n"
        " FROM invoices WHERE kind='sale_return' AND is_deleted=0"
        " AND invoice_date BETWEEN ? AND ?", (date_from, date_to)).fetchone()

    # فصل صريح: مبيعات (ذهب/أجور) ومرتجعات (ذهب/أجور)
    sales_gold = round(sales["weight"], 2)
    sales_wages = round(sales["wages"], 2)
    returns_gold = round(returns["weight"], 2)
    returns_wages = round(returns["wages"], 2)
    net_wages = round(sales_wages - returns_wages, 2)     # الإيراد النقدي
    net_gold_sold = round(sales_gold - returns_gold, 2)   # حركة الذهب

    # ── فاقد الذهب العيني من حسابي الفاقد (وزناً) ──
    casting_g, _ = _group_balance(conn, ["5120"], date_to)     # الفاقد الفني للصب
    manuf_g, _ = _group_balance(conn, ["5110"], date_to)       # فاقد التصنيع
    # نحصر بالفترة: نعيد الحساب بحد أدنى للتاريخ أيضاً
    casting_g = _period_account_gold(conn, "5120", date_from, date_to)
    manuf_g = _period_account_gold(conn, "5110", date_from, date_to)
    total_loss = round(casting_g + manuf_g, 3)

    # ── المصروفات النقدية من سندات الصرف ──
    pay = conn.execute(
        "SELECT COALESCE(SUM(cash_amount),0) cash, COUNT(*) n"
        " FROM vouchers WHERE kind='payment' AND is_deleted=0"
        " AND voucher_date BETWEEN ? AND ?", (date_from, date_to)).fetchone()
    expenses = round(pay["cash"], 2)

    net_profit_cash = round(net_wages - expenses, 2)
    net_gold_movement = round(-total_loss, 3)      # سالب = عجز عيني

    return {
        # الإيرادات
        "sales_wages": round(sales["wages"], 2),
        "returns_wages": round(returns["wages"], 2),
        "net_wages": net_wages,
        "sales_weight": round(sales["weight"], 3),
        "returns_weight": round(returns["weight"], 3),
        "net_gold_sold": net_gold_sold,      # عرض فقط
        "sales_count": sales["n"], "returns_count": returns["n"],
        # الفاقد
        "casting_loss": round(casting_g, 3),
        "manufacturing_loss": round(manuf_g, 3),
        "total_gold_loss": total_loss,
        # المصروفات
        "expenses_cash": expenses, "payments_count": pay["n"],
        # النتيجة
        "net_profit_cash": net_profit_cash,
        "net_gold_movement": net_gold_movement,
    }


def _period_account_gold(conn, code, date_from, date_to):
    """صافي حركة الذهب (مدين−دائن) لحساب معيّن خلال فترة محددة."""
    ids = _subtree_ids(conn, code)
    if not ids:
        return 0.0
    qs = ",".join("?" * len(ids))
    r = conn.execute(
        "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        f" WHERE l.account_id IN ({qs}) AND e.is_deleted=0"
        " AND e.entry_date BETWEEN ? AND ?",
        ids + [date_from, date_to]).fetchone()
    return round(r["g"], 3)
