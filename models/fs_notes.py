# -*- coding: utf-8 -*-
"""الإيضاحات المتممة للقوائم المالية — تُولَّد من الدفاتر نفسها.

أرقام الإيضاحات **ثابتة** (لا تتغيّر بحسب ما يظهر منها)، فتُشير إليها
قائمة المركز المالي وقائمة الدخل في عمود «إيضاح»، ويبقى الإيضاح
موجوداً ولو خلا من الأرصدة («لا توجد أرصدة»). والنصوص الوصفية (السياسات)
قالبٌ يراجعه المحاسب القانوني ويعدّله عند الحاجة.
"""
from models import statements as st

NOTES = [
    (1, "التكوين والنشاط"),
    (2, "أسس الإعداد"),
    (3, "السياسات المحاسبية الهامة"),
    (4, "النقد وما في حكمه"),
    (5, "الذمم المدينة"),
    (6, "المخزون"),
    (7, "المصروفات المدفوعة مقدماً والأرصدة المدينة الأخرى"),
    (8, "الممتلكات والآلات والمعدات"),
    (9, "الذمم الدائنة والمستحقات والقروض"),
    (10, "ضريبة القيمة المضافة"),
    (11, "الزكاة"),
    (12, "مخصص مكافأة نهاية الخدمة للموظفين"),
    (13, "رأس المال وحقوق الملكية"),
    (14, "الإيرادات"),
    (15, "خسائر الورشة"),
    (16, "المصاريف التشغيلية"),
    (17, "اعتماد القوائم المالية"),
]

# بند القائمة ← رقم الإيضاح (للعمود «إيضاح» في المركز المالي والدخل)
NOTE_REF = {
    "cash": 4, "receivables": 5, "ecl": 5, "inventory": 6,
    "prepaid": 7, "staff": 7, "supplier_adv": 7, "ca_other": 7,
    "ppe_cost": 8, "ppe_dep": 8, "nca_other": 8,
    "payables": 9, "customer_adv": 9, "accruals": 9, "accrued": 9,
    "cl_other": 9, "loans_st": 9, "loans_lt": 9, "ncl_other": 9,
    "reserve": 13, "vat_asset": 10, "vat_liab": 10, "zakat": 11,
    "eosb": 12, "capital": 13, "partners": 13, "retained": 13,
    "opening_susp": 13, "eq_other": 13, "profit": 13,
    # قائمة الدخل
    "sales": 14, "returns": 14, "discounts": 14,
    "net_diff": 14, "other_rev": 14,
    "workshop": 15, "recovered": 15,
    "admin": 16, "labor": 16, "mgmt": 16, "materials": 16,
}


def _merge(cur, cmp_):
    """(كود، اسم، حالي، مقارنة) من تفصيلين — حساباً حساباً."""
    acc = {}
    for code, name, amt in cur:
        acc.setdefault((code, name), [0.0, 0.0])[0] += amt
    for code, name, amt in cmp_:
        acc.setdefault((code, name), [0.0, 0.0])[1] += amt
    return [(c, n, round(v[0], 2), round(v[1], 2))
            for (c, n), v in sorted(acc.items())]


def _table(title, rows, total_label="المجموع", sign=1):
    """جدول إيضاح: صفوف حسابات ومجموع."""
    rows = [(c, n, sign * a, sign * b) for c, n, a, b in rows
            if abs(a) >= 0.005 or abs(b) >= 0.005]
    return {"title": title, "rows": rows,
            "total": (total_label, round(sum(r[2] for r in rows), 2),
                      round(sum(r[3] for r in rows), 2))}


def _move(conn, code, d1, d2, credit_nature=True):
    """حركة حسابٍ في الفترة: أول المدة · إضافات · استبعادات · آخر المدة."""
    from models.accounts import subtree_ids
    r = conn.execute("SELECT id FROM accounts WHERE code=?",
                     (code,)).fetchone()
    if not r:
        return None
    ids = subtree_ids(conn, r["id"]) or [r["id"]]
    ph = ",".join("?" * len(ids))
    q = conn.execute(
        "SELECT"
        " COALESCE(SUM(CASE WHEN e.entry_date<? THEN"
        "  l.cash_debit-l.cash_credit END),0) op,"
        " COALESCE(SUM(CASE WHEN e.entry_date BETWEEN ? AND ? THEN"
        "  l.cash_debit END),0) dr,"
        " COALESCE(SUM(CASE WHEN e.entry_date BETWEEN ? AND ? THEN"
        "  l.cash_credit END),0) cr"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " AND e.is_deleted=0"
        f" WHERE l.account_id IN ({ph}) AND NOT {st._BOOK_PAIR}",
        [d1, d1, d2, d1, d2] + list(ids)).fetchone()
    s = -1 if credit_nature else 1
    op = s * (q["op"] or 0.0)
    inc = (q["cr"] if credit_nature else q["dr"]) or 0.0
    dec = (q["dr"] if credit_nature else q["cr"]) or 0.0
    return {"opening": round(op, 2) + 0.0, "add": round(inc, 2) + 0.0,
            "less": round(dec, 2) + 0.0,
            "closing": round(op + inc - dec, 2) + 0.0}


def build(conn, date_from, date_to, compare=True):
    """الإيضاحات كاملةً: [{no, title, paras, tables, moves}]."""
    import config
    fp = st.financial_position(conn, date_to,
                               st._day_before(date_from) if compare else "")
    rows, by_id, _r = st._tree(conn)
    cur_v, cur_d = st._position_dim(conn, date_to, "cash", rows, by_id)
    cmp_to = fp["compare_to"]
    if cmp_to:
        cmp_v, cmp_d = st._position_dim(conn, cmp_to, "cash", rows, by_id)
        _gv, cmp_gd = st._position_dim(conn, cmp_to, "gold", rows, by_id)
    else:
        cmp_v = {k: 0.0 for k in cur_v}
        cmp_d = {k: [] for k in cur_d}
        cmp_gd = {k: [] for k in cur_d}
    _gv, cur_gd = st._position_dim(conn, date_to, "gold", rows, by_id)
    inc = st.income_statement(conn, date_from, date_to, bool(compare))
    c1, c2 = inc["compare_from"], inc["compare_to"]
    cur_is = st._is_period(conn, date_from, date_to, "cash", rows, by_id)
    cmp_is = (st._is_period(conn, c1, c2, "cash", rows, by_id)
              if c1 else ({}, {}, {k: [] for k, _t, _s in st.IS_LINES}))

    def det(*keys, src=(cur_d, cmp_d)):
        a, b = [], []
        for k in keys:
            a += src[0].get(k, [])
            b += src[1].get(k, [])
        return _merge(a, b)

    def isdet(*keys):
        a, b = [], []
        for k in keys:
            a += cur_is[2].get(k, [])
            b += cmp_is[2].get(k, [])
        return _merge(a, b)

    notes = {n: {"no": n, "title": t, "paras": [], "tables": [],
                 "moves": []} for n, t in NOTES}
    ent = config.COMPANY_NAME
    cr = getattr(config, "COMPANY_CR", "") or "—"
    vat = getattr(config, "COMPANY_VAT_NUMBER", "") or "—"
    addr = getattr(config, "COMPANY_ADDRESS", "") or ""
    notes[1]["paras"] = [
        f"{ent} — مسجّلة بالسجل التجاري رقم {cr}، والرقم الضريبي {vat}"
        + (f"، وعنوانها {addr}" if addr else "") + ".",
        "يتمثّل النشاط الرئيسي في تصنيع المشغولات الذهبية وتجارتها،"
        " وتقديم خدمات التصنيع مقابل أجور.",
        f"تغطي هذه القوائم الفترة من {date_from} إلى {date_to}"
        + (f"، مقارنةً بالفترة من {c1} إلى {c2}." if c1 else "."),
    ]
    notes[2]["paras"] = [
        "أُعدّت القوائم المالية وفقاً للمعايير الدولية للتقرير المالي"
        " المعتمدة في المملكة العربية السعودية والمعايير والإصدارات الأخرى"
        " المعتمدة من الهيئة السعودية للمراجعين والمحاسبين.",
        "أُعدّت على أساس التكلفة التاريخية ومبدأ الاستحقاق، وتُعرض بالريال"
        " السعودي وهو عملة النشاط والعرض.",
        "يُمسك الذهب في الدفاتر بالوزن (بمكافئ عيار 18) إلى جانب القيم"
        " النقدية؛ وتُعرض أرصدته الوزنية في الإيضاحات، ويُضاف تقويمها"
        " بالريال بسعر الجرام في تاريخ القوائم عند تفعيل تقييم الذهب.",
    ]
    rates = None
    try:
        from models import period_end as pe
        rates = pe.ecl_rates(conn)
    except Exception:
        pass
    notes[3]["paras"] = [
        "الإيرادات (IFRS 15): تُثبت عند انتقال السيطرة على البضاعة إلى"
        " العميل بتسليمها، وأجور التصنيع عند إنجاز الخدمة؛ وتُعرض بالصافي"
        " بعد المردودات والخصومات، ودون ضريبة القيمة المضافة.",
        "المخزون (IAS 2): الذهب الخام والمشغول وصناديق الكسر، يُقاس بالتكلفة"
        " أو صافي القيمة القابلة للتحقق أيهما أقل. والذهب يخرج بوزنه إلى"
        " ذمة العميل عند البيع (انتقال أصل)، وإيراد المصنع أجور التصنيع.",
        "خسائر الورشة: فواقد قسم التصنيع وفاقد التصفية والصب (ما أُرسل"
        " للتصفية ولم يعد) وفاقد بيع الذهب وفروقات الجرد تُحمَّل على"
        " قائمة الدخل عند وقوعها، ويُخصم منها المسترجع من التصفية. والفصوص"
        " والأحجار مواد تشغيل تُحمَّل عند صرفها للتصنيع.",
        "الممتلكات والآلات والمعدات (IAS 16): تُقاس بالتكلفة ناقصاً مجمّع"
        " الإهلاك، ويُحسب الإهلاك بطريقة القسط الثابت على العمر الإنتاجي"
        " المقدّر لكل أصل.",
        "الذمم المدينة (IFRS 9): تُقاس بالتكلفة المطفأة ناقصاً مخصص الخسائر"
        " الائتمانية المتوقعة وفق المنهج المبسّط بمصفوفة المخصص على أعمار"
        " الذمم" + (f" (النسب: {' · '.join(f'{r:g}%' for r in rates)} للفئات"
                   " أقل من 30 · 60 · 90 · أكثر من 90 يوماً)"
                   if rates else "") + ".",
        "مكافأة نهاية الخدمة (IAS 19): يُكوَّن مخصصها بالمبلغ المستحق"
        " للموظفين وفق المادة 84 من نظام العمل لو انتهت خدمتهم في تاريخ"
        " القوائم، ويُحمّل التغيّر على قائمة الدخل.",
        "الزكاة: تُحتسب وفق اللائحة التنفيذية لجباية الزكاة الصادرة عن"
        " هيئة الزكاة والضريبة والجمارك، وتُحمّل على قائمة الدخل بعد «الربح"
        " قبل الزكاة»، وتُسوّى الفروق عند الربط النهائي في سنة الربط.",
        "ضريبة القيمة المضافة: تُثبت ضريبة المخرجات عند التوريد وضريبة"
        " المدخلات عند الاستلام، وتُعرض بالصافي لأنها التزامٌ لجهة واحدة.",
        "النقد وما في حكمه: النقد بالصندوق والأرصدة لدى البنوك.",
        "المصروفات المدفوعة مقدماً: تُطفأ على مدة الانتفاع بها يوماً بيوم؛"
        " والمصروفات المستحقة تُثبت عند الاستهلاك ولو لم تصل فاتورتها.",
    ]
    # ── الأرصدة
    notes[4]["tables"] = [_table("", det("cash"))]
    rec = _table("", det("receivables"), "إجمالي الذمم المدينة")
    notes[5]["tables"] = [rec]
    ecl_now, ecl_prev = cur_v.get("ecl", 0.0), cmp_v.get("ecl", 0.0)
    notes[5]["tables"].append({
        "title": "", "rows": [("", "يُطرح: مخصص الخسائر الائتمانية المتوقعة",
                               round(ecl_now, 2), round(ecl_prev, 2))],
        "total": ("صافي الذمم المدينة",
                  round(rec["total"][1] + ecl_now, 2),
                  round(rec["total"][2] + ecl_prev, 2))})
    m = _move(conn, "1680", date_from, date_to)
    if m:
        notes[5]["moves"].append(("حركة مخصص الخسائر الائتمانية", m,
                                  "المكوَّن خلال الفترة",
                                  "المستخدم / المردود"))
    notes[6]["tables"] = [_table("القيمة بالريال", det("inventory"))]
    gold_rows = det("inventory", src=(cur_gd, cmp_gd))
    notes[6]["tables"].append(
        {"title": "الأرصدة الوزنية (جرام بمكافئ عيار 18)", "gold": True,
         "rows": [r for r in gold_rows
                  if abs(r[2]) >= 0.0005 or abs(r[3]) >= 0.0005],
         "total": ("مجموع الوزن",
                   round(sum(r[2] for r in gold_rows), 3),
                   round(sum(r[3] for r in gold_rows), 3))})
    notes[7]["tables"] = [_table("", det("prepaid", "staff",
                                         "supplier_adv", "ca_other"))]
    m = _move(conn, "1980", date_from, date_to, credit_nature=False)
    if m:
        notes[7]["moves"].append(("حركة المصروفات المدفوعة مقدماً", m,
                                  "المدفوع خلال الفترة", "المُطفأ"))
    notes[8]["tables"] = [_table("", det("ppe_cost", "ppe_dep", "nca_other"),
                                 "صافي القيمة الدفترية")]
    cost_ids_move = _ppe_cost_move(conn, date_from, date_to)
    if cost_ids_move:
        notes[8]["moves"].append(("حركة التكلفة", cost_ids_move,
                                  "الإضافات", "الاستبعادات"))
    m = _move(conn, "1790", date_from, date_to)
    if m:
        notes[8]["moves"].append(("حركة مجمّع الإهلاك", m,
                                  "إهلاك الفترة", "استبعادات"))
    notes[9]["tables"] = [_table("", det("payables", "customer_adv",
                                         "accruals", "accrued", "cl_other",
                                         "loans_st", "loans_lt",
                                         "ncl_other"),
                                 sign=1)]
    vat_rows = []
    a = st._balances(conn, date_to, "cash")
    b = st._balances(conn, cmp_to, "cash") if cmp_to else {}
    for code, label in (("2100", "ضريبة المخرجات"), ("1900",
                                                       "ضريبة المدخلات"),
                        ("2150", "حساب تسوية الضريبة")):
        aid = conn.execute("SELECT id FROM accounts WHERE code=?",
                           (code,)).fetchone()
        if aid:
            vat_rows.append((code, label, round(-a.get(aid["id"], 0.0), 2),
                             round(-b.get(aid["id"], 0.0), 2)))
    notes[10]["tables"] = [{"title": "(دائن موجب · مدين سالب)",
                            "rows": vat_rows,
                            "total": ("صافي الضريبة المستحقة (المستردة)",
                                      round(sum(r[2] for r in vat_rows), 2),
                                      round(sum(r[3] for r in vat_rows), 2))}]
    # ── الزكاة
    try:
        from models import period_end as pe
        z = pe.zakat_saved(conn, date_from, date_to) or pe.zakat_compute(
            conn, date_from, date_to)
        zrows = ([("", f"+ {l}", v, 0.0) for l, v in z["additions"]]
                 + [("", f"− {l}", -v, 0.0) for l, v in z["deductions"]])
        notes[11]["tables"] = [{"title": "الوعاء الزكوي", "rows": zrows,
                                "total": ("الوعاء الزكوي", z["base"], 0.0),
                                "single": True}]
        notes[11]["paras"] = [
            f"النسبة المطبّقة {z['rate'] * 100:.4f}% (2.5% للسنة الهجرية"
            " معدّلةً بعدد أيام الفترة ÷ 354)؛ والزكاة المحتسبة"
            f" {z['zakat']:,.2f} ريال."
            + (" رُفع الوعاء إلى صافي الربح المعدّل لأنه أقل منه."
               if z.get("base_floor") else "")]
    except Exception:
        pass
    m = _move(conn, "2400", date_from, date_to)
    if m:
        notes[11]["moves"].append(("حركة مخصص الزكاة", m,
                                   "المكوَّن خلال الفترة", "المسدَّد"))
    m = _move(conn, "2600", date_from, date_to)
    if m:
        notes[12]["moves"].append(("حركة المخصص", m,
                                   "المكوَّن خلال الفترة", "المدفوع"))
    try:
        from models import period_end as pe
        eos = pe.eos_compute(conn, date_to)
        notes[12]["paras"] = [
            f"عدد الموظفين المشمولين {sum(1 for r in eos['rows'] if r['counted'])}،"
            f" والالتزام المحسوب في {date_to}: {eos['required']:,.2f} ريال."]
    except Exception:
        pass
    notes[13]["tables"] = [{"title": "", "rows": [
        ("", t, round(cur_v.get(k, 0.0), 2), round(cmp_v.get(k, 0.0), 2))
        for k, t, s in st.LINES if s == "eq"
        and (abs(cur_v.get(k, 0.0)) >= 0.005
             or abs(cmp_v.get(k, 0.0)) >= 0.005)],
        "total": ("مجموع حقوق الملكية",
                  round(sum(cur_v.get(k, 0.0) for k, _t, s in st.LINES
                            if s == "eq"), 2),
                  round(sum(cmp_v.get(k, 0.0) for k, _t, s in st.LINES
                            if s == "eq"), 2))}]
    notes[13]["paras"] = ["تفصيل الحركة في «قائمة التغيرات في حقوق"
                          " الملكية»."]
    notes[14]["tables"] = [_table("", isdet("sales", "returns", "discounts",
                                            "net_diff", "other_rev"))]
    notes[15]["tables"] = [_table("", isdet("workshop", "recovered"),
                                  sign=-1)]
    notes[16]["tables"] = [_table("", isdet("admin", "labor", "mgmt",
                                                 "materials"),
                                  sign=-1)]
    notes[17]["paras"] = [
        "اعتُمدت هذه القوائم المالية والإيضاحات المرفقة من الإدارة بتاريخ"
        " ……………………، ووُقّعت نيابةً عنها."]
    return {"date_from": date_from, "date_to": date_to,
            "compare_to": cmp_to, "compare_from": c1,
            "notes": [notes[n] for n, _t in NOTES]}


def _ppe_cost_move(conn, d1, d2):
    """حركة تكلفة الأصول الثابتة (1700 دون مجمّع الإهلاك)."""
    from models.accounts import subtree_ids
    r = conn.execute("SELECT id FROM accounts WHERE code='1700'").fetchone()
    dep = conn.execute("SELECT id FROM accounts WHERE code='1790'").fetchone()
    if not r:
        return None
    ids = [i for i in (subtree_ids(conn, r["id"]) or [r["id"]])
           if not dep or i != dep["id"]]
    ph = ",".join("?" * len(ids))
    q = conn.execute(
        "SELECT"
        " COALESCE(SUM(CASE WHEN e.entry_date<? THEN"
        "  l.cash_debit-l.cash_credit END),0) op,"
        " COALESCE(SUM(CASE WHEN e.entry_date BETWEEN ? AND ? THEN"
        "  l.cash_debit END),0) dr,"
        " COALESCE(SUM(CASE WHEN e.entry_date BETWEEN ? AND ? THEN"
        "  l.cash_credit END),0) cr"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " AND e.is_deleted=0"
        f" WHERE l.account_id IN ({ph}) AND NOT {st._BOOK_PAIR}",
        [d1, d1, d2, d1, d2] + ids).fetchone()
    op = q["op"] or 0.0
    return {"opening": round(op, 2), "add": round(q["dr"] or 0.0, 2),
            "less": round(q["cr"] or 0.0, 2),
            "closing": round(op + (q["dr"] or 0) - (q["cr"] or 0), 2)}
