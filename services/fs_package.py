# -*- coding: utf-8 -*-
"""حزمة القوائم المالية — ملفٌ واحد يُسلَّم للمحاسب القانوني.

ملف ZIP فيه:
* `القوائم_المالية_الكاملة.html` — الغلاف والقوائم الأربع والإيضاحات،
  يُفتح في المتصفح ويُحفظ PDF.
* ملفات CSV لكل قائمة ولميزان المراجعة وللإيضاحات — تُفتح في Excel.
* `ifrs_mapping.json` — كل بندٍ رئيسي بمسمّاه في تصنيف IFRS (ifrs-full)
  وقيمته للفترة الحالية والمقارنة، ليُنقل إلى أداة XBRL التي يرفع بها
  المحاسب القانوني القوائم المدقّقة على منصة «قوائم».

**تنبيه صادق**: الملف ليس مستند XBRL مُعتمداً للرفع المباشر — الرفع على
منصة «قوائم» يتمّ للقوائم المدقّقة عبر المحاسب القانوني وأداته. الحزمة
تختصر عليه إعادة الإدخال وتحفظ اتساق الأرقام.
"""
import csv
import io
import json
import zipfile

from models import statements as st

# بند ← مسمّى IFRS. البنود المحلية (الزكاة) بامتدادٍ مصرَّحٍ به.
FP_CONCEPTS = [
    ("cash", "ifrs-full:CashAndCashEquivalents", ("cash",)),
    ("receivables", "ifrs-full:TradeAndOtherCurrentReceivables",
     ("receivables", "ecl")),
    ("inventory", "ifrs-full:Inventories", ("inventory",)),
    ("prepaid", "ifrs-full:CurrentPrepayments", ("prepaid",)),
    ("other_ca", "ifrs-full:OtherCurrentAssets",
     ("staff", "supplier_adv", "ca_other")),
    ("vat_asset", "ifrs-full:CurrentValueAddedTaxReceivables",
     ("vat_asset",)),
    ("ppe", "ifrs-full:PropertyPlantAndEquipment", ("ppe_cost", "ppe_dep")),
    ("nca_other", "ifrs-full:OtherNoncurrentAssets", ("nca_other",)),
    ("capital", "ifrs-full:IssuedCapital", ("capital",)),
    ("retained", "ifrs-full:RetainedEarnings", ("retained", "profit")),
    ("other_equity", "ifrs-full:OtherEquityInterest",
     ("partners", "opening_susp", "eq_other")),
    ("eosb", "ifrs-full:NoncurrentProvisionsForEmployeeBenefits",
     ("eosb",)),
    ("ncl_other", "ifrs-full:OtherNoncurrentLiabilities", ("ncl_other",)),
    ("payables", "ifrs-full:TradeAndOtherCurrentPayables",
     ("payables", "customer_adv", "accruals", "accrued", "cl_other")),
    ("zakat", "ksa-ext:ZakatPayable", ("zakat",)),
    ("vat_liab", "ifrs-full:CurrentValueAddedTaxPayables", ("vat_liab",)),
]
FP_TOTALS = [("nca", "ifrs-full:NoncurrentAssets"),
             ("ca", "ifrs-full:CurrentAssets"),
             ("assets", "ifrs-full:Assets"),
             ("eq", "ifrs-full:Equity"),
             ("ncl", "ifrs-full:NoncurrentLiabilities"),
             ("cl", "ifrs-full:CurrentLiabilities"),
             ("liabilities", "ifrs-full:Liabilities"),
             ("right", "ifrs-full:EquityAndLiabilities")]
IS_CONCEPTS = [
    ("net_revenue", "ifrs-full:Revenue", True),
    ("cos", "ifrs-full:CostOfSales", True),
    ("gross", "ifrs-full:GrossProfit", True),
    ("operating", "ifrs-full:ProfitLossFromOperatingActivities", True),
    ("before_zakat", "ifrs-full:ProfitLossBeforeTax", True),
    ("net", "ifrs-full:ProfitLoss", True),
    ("admin", "ifrs-full:AdministrativeExpense", False),
    ("depr", "ifrs-full:DepreciationExpense", False),
    ("ecl_exp", "ifrs-full:ImpairmentLossImpairmentGainAndReversalOf"
                "ImpairmentLossDeterminedInAccordanceWithIFRS9", False),
    ("other_income", "ifrs-full:OtherIncome", False),
    ("other_exp", "ifrs-full:OtherExpenseByFunction", False),
    ("zakat", "ksa-ext:ZakatExpense", False),
]
CF_CONCEPTS = [
    ("op", "ifrs-full:CashFlowsFromUsedInOperatingActivities"),
    ("inv", "ifrs-full:CashFlowsFromUsedInInvestingActivities"),
    ("fin", "ifrs-full:CashFlowsFromUsedInFinancingActivities"),
    ("net", "ifrs-full:IncreaseDecreaseInCashAndCashEquivalents"),
    ("closing", "ifrs-full:CashAndCashEquivalents"),
]


def _csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    # BOM ليفتح Excel العربية بلا تشويه
    return "﻿" + buf.getvalue()


def _facts(fp, inc, cf):
    facts = []
    c = fp["cash"]
    for ctx, vals, tots in (("current", c["values"], c["totals"]),
                            ("comparative", c.get("compare") or {},
                             c.get("compare_totals") or {})):
        if not vals:
            continue
        for key, concept, parts in FP_CONCEPTS:
            v = round(sum(vals.get(p, 0.0) for p in parts), 2)
            facts.append({"statement": "financial_position",
                          "concept": concept, "item": key,
                          "context": ctx, "value": v})
        for key, concept in FP_TOTALS:
            facts.append({"statement": "financial_position",
                          "concept": concept, "item": key,
                          "context": ctx, "value": tots.get(key, 0.0)})
    ic = inc["cash"]
    for ctx, vals, tots in (("current", ic["values"], ic["totals"]),
                            ("comparative", ic.get("compare") or {},
                             ic.get("compare_totals") or {})):
        if not tots:
            continue
        for key, concept, is_total in IS_CONCEPTS:
            v = tots.get(key, 0.0) if is_total else vals.get(key, 0.0)
            facts.append({"statement": "income_statement",
                          "concept": concept, "item": key,
                          "context": ctx, "value": round(v, 2)})
    for ctx, blk in (("current", cf.get("cur")),
                     ("comparative", cf.get("cmp"))):
        if not blk:
            continue
        for key, concept in CF_CONCEPTS:
            facts.append({"statement": "cash_flow", "concept": concept,
                          "item": key, "context": ctx,
                          "value": blk["totals"].get(key, 0.0)})
    return facts


def export(path, date_from, date_to, compare=True, method="indirect"):
    """يكتب الحزمة في `path` (zip) ويُعيد قائمة ملفاتها.

    يفتح اتصال القراءة بنفسه ويُغلقه قبل بناء المستند الكامل — فلا
    يتداخل اتصالان بالقاعدة.
    """
    import config
    from database.database import db
    from models import fs_notes
    from services import browser_print
    cmp_to = st._day_before(date_from) if compare else ""
    with db(readonly=True) as conn:
        fp = st.financial_position(conn, date_to, cmp_to)
        inc = st.income_statement(conn, date_from, date_to, bool(compare))
        cf = st.cash_flow(conn, date_from, date_to, bool(compare))
        eq = st.equity_changes(conn, date_from, date_to, bool(compare))
        tb = st.trial_balance(conn, date_from, date_to, "cash")
        nb = fs_notes.build(conn, date_from, date_to, bool(compare))
    files = {}

    has_cmp = bool(fp["compare_to"])
    rows = [["البيان", "إيضاح", f"كما في {date_to}"]
            + ([f"كما في {fp['compare_to']}"] if has_cmp else [])]
    for r in st.layout(fp):
        if r["kind"] in ("head", "sec"):
            rows.append([r["label"]])
            continue
        rows.append([r["label"], fs_notes.NOTE_REF.get(r.get("key"), "")
                     if r["kind"] == "line" else "", round(r["cash"], 2)]
                    + ([round(r["cash_cmp"], 2)] if has_cmp else []))
    files["1_financial_position.csv"] = _csv(rows)

    rows = [["البيان", "إيضاح", "الفترة الحالية"]
            + (["فترة المقارنة"] if inc["compare_from"] else [])]
    for r in st.is_layout(inc):
        if r["kind"] == "sec":
            rows.append([r["label"]])
            continue
        rows.append([r["label"], fs_notes.NOTE_REF.get(r.get("key"), "")
                     if r["kind"] == "line" else "", round(r["cash"], 2)]
                    + ([round(r["cash_cmp"], 2)]
                       if inc["compare_from"] else []))
    files["2_income_statement.csv"] = _csv(rows)

    keys = [k for k, _t in eq["columns"]] + ["total"]
    rows = [["البيان"] + [t for _k, t in eq["columns"]] + ["المجموع"]]
    for r in st.eq_layout(eq):
        if r["kind"] == "sec":
            rows.append([r["label"]])
            continue
        rows.append([r["label"]] + [round(r["values"].get(k, 0.0), 2)
                                    for k in keys])
    files["3_equity_changes.csv"] = _csv(rows)

    rows = [["البيان", "الفترة الحالية"]
            + (["فترة المقارنة"] if cf.get("cmp") else [])]
    for r in st.cf_layout(cf, method):
        if r["kind"] == "sec":
            rows.append([r["label"]])
            continue
        rows.append([r["label"], round(r["cash"], 2)]
                    + ([round(r["cash_cmp"], 2)] if cf.get("cmp") else []))
    files["4_cash_flow.csv"] = _csv(rows)

    rows = [["المستوى", "الكود", "اسم الحساب", "أول المدة مدين",
             "أول المدة دائن", "حركة مدين", "حركة دائن", "آخر المدة مدين",
             "آخر المدة دائن"]]
    for r in tb["rows"]:
        rows.append([r["level"], r["code"], r["name"], r["open_dr"],
                     r["open_cr"], r["dr"], r["cr"], r["close_dr"],
                     r["close_cr"]])
    files["5_trial_balance.csv"] = _csv(rows)

    rows = [["رقم الإيضاح", "الإيضاح", "البند", "الفترة الحالية",
             "المقارنة"]]
    for n in nb["notes"]:
        for p in n["paras"]:
            rows.append([n["no"], n["title"], p])
        for t in n["tables"]:
            for code, name, a, b in t["rows"]:
                rows.append([n["no"], n["title"],
                             f"{code} {name}".strip(), a, b])
            rows.append([n["no"], n["title"], t["total"][0],
                         t["total"][1], t["total"][2]])
        for title, m, add_l, less_l in n["moves"]:
            for lbl, v in (("أول الفترة", m["opening"]), (add_l, m["add"]),
                           (less_l, -m["less"]), ("آخر الفترة", m["closing"])):
                rows.append([n["no"], f"{n['title']} — {title}", lbl, v, ""])
    files["6_notes.csv"] = _csv(rows)

    files["ifrs_mapping.json"] = json.dumps({
        "entity": {"name": config.COMPANY_NAME,
                   "cr": getattr(config, "COMPANY_CR", ""),
                   "vat": getattr(config, "COMPANY_VAT_NUMBER", "")},
        "period": {"from": date_from, "to": date_to,
                   "comparative_fp": fp["compare_to"],
                   "comparative_from": inc["compare_from"],
                   "comparative_to": inc["compare_to"]},
        "currency": "SAR", "decimals": 2,
        "balanced": fp["balanced_cash"] and cf["balanced"]
        and eq["balanced"] and tb["totals"]["balanced"],
        "note": "مسمّيات تصنيف IFRS (ifrs-full) للبنود الرئيسية؛ ksa-ext"
                " لبنود محلية (الزكاة). ليس مستند XBRL للرفع المباشر.",
        "facts": _facts(fp, inc, cf),
    }, ensure_ascii=False, indent=1)

    html = browser_print.build_page("fs_full", 0, auto_print=False,
                                    date_from=date_from, date_to=date_to,
                                    compare=compare, method=method)
    files["القوائم_المالية_الكاملة.html"] = html
    files["اقرأني.txt"] = (
        f"حزمة القوائم المالية — {config.COMPANY_NAME}\n"
        f"الفترة: من {date_from} إلى {date_to}\n\n"
        "القوائم_المالية_الكاملة.html : افتحه في المتصفح ثم «طباعة» ← حفظ PDF.\n"
        "ملفات CSV : تُفتح في Excel — قائمةٌ لكل ملف، وميزان المراجعة، والإيضاحات.\n"
        "ifrs_mapping.json : البنود بمسمّيات تصنيف IFRS لأداة XBRL لدى المحاسب"
        " القانوني (الرفع على منصة «قوائم» يتمّ للقوائم المدقّقة عبره).\n")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text.encode("utf-8"))
    return sorted(files)


def readiness(conn, date_from, date_to):
    """قائمة التحقق قبل الرفع — (البند، جاهز؟، تفصيل)."""
    from models import fiscal, period_end as pe
    out = []
    tb = st.trial_balance(conn, date_from, date_to, "cash")
    out.append(("ميزان المراجعة متوازن", tb["totals"]["balanced"], ""))
    fp = st.financial_position(conn, date_to, "")
    out.append(("قائمة المركز المالي متوازنة", fp["balanced_cash"], ""))
    z = pe.zakat_compute(conn, date_from, date_to)
    out.append(("مخصص الزكاة مقيَّد للفترة", abs(z["due"]) < 0.01,
                f"المطلوب قيده {z['due']:,.2f}" if abs(z["due"]) >= 0.01
                else f"{z['zakat']:,.2f}"))
    e = pe.eos_compute(conn, date_to)
    ok = abs(e["due"]) < 0.01 and not e["missing_hire"]
    out.append(("مخصص مكافأة نهاية الخدمة محدَّث", ok,
                (f"ينقص تاريخ تعيين: {len(e['missing_hire'])} موظف · "
                 if e["missing_hire"] else "")
                + (f"المطلوب قيده {e['due']:,.2f}"
                   if abs(e["due"]) >= 0.01 else "")))
    c = pe.ecl_compute(conn, date_to)
    out.append(("مخصص الخسائر الائتمانية محدَّث", abs(c["due"]) < 0.01,
                f"المطلوب قيده {c['due']:,.2f}" if abs(c["due"]) >= 0.01
                else ""))
    pend = [p for p in pe.prepaid_list(conn, date_to) if abs(p["due"]) >= 0.01]
    out.append(("المصروفات المقدمة مُطفأة حتى نهاية الفترة", not pend,
                f"{len(pend)} بند بلا إطفاء" if pend else ""))
    lock = fiscal.lock_date(conn)
    out.append(("الفترة مقفلة بعد الاعتماد", bool(lock) and lock >= date_to,
                f"تاريخ القفل الحالي: {lock or 'لا يوجد'}"))
    return out
