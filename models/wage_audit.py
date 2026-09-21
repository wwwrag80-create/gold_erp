# -*- coding: utf-8 -*-
"""الأجرة المتفق عليها وانحرافاتها — أين يتسرّب الربح بلا أن يُرى.

**السؤال الذي وُجد لأجله**: مصدر ربح مصنع الذهب هو **الأجرة على
الجرام** لا الذهب. والمصنع يتفق مع كل عميلٍ على أجرة، ثم يُدخل
البائع الرقم في كل سطرِ فاتورةٍ من ذاكرته. فينزل عميلٌ درجةً بلا أن
يدري أحد — لا لأن أحداً غشّ، بل لأن لا أحد يجمع.

وأجرةٌ نقصت **ريالاً واحداً** على عشرة كيلوات عشرةُ آلافِ ريالٍ ضاعت
في شهر. ولا يظهر ذلك في أي تقرير: الفاتورة سليمة، والقيد متوازن،
والميزان يقفل. الخطأ ليس في المحاسبة بل في أن **أحداً لم يقارن**.

**وكل فاتورةٍ تُقاس باتفاقها يوم صدورها** لا بالاتفاق النافذ اليوم:
لو قُورن العام كلّه بآخر اتفاق لصارت كلُّ فاتورةٍ قبل آخر تعديلٍ
«انحرافاً»، فيمتلئ التقرير بما ليس بخطأ — وتقريرٌ كثير الضجيج
يُهمَل، والمُهمَل كأنه لم يُكتب.

**وأثر الانحراف بالمال لا بالفرق**: «أقلّ بريالين» لا تقول شيئاً،
و«‏٨٤٠٠ ريالٍ أقلّ من المتفق عليه» تقول كل شيء. فالأثر =
(المطبَّق − المتفق) × الوزن، وإشارتُه في المرتجع معكوسة لأن الوزن
يعود لا يخرج.

**وما لا اتفاق له ليس انحرافاً**: يُفرز في بابٍ مستقلٍّ اسمه «بلا
اتفاق» — ليس اتهاماً بل تذكيرٌ بأن يُكتب الاتفاق.

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
EPS = 0.005


def _agreements(conn):
    """كل الاتفاقات مفهرسةً بالجهة — استعلامٌ واحد لا استعلامٌ لكل سطر.

    الفاتورة الواحدة عشرةُ أسطر، والشهر مئاتُ الفواتير. استعلامٌ لكل
    سطرٍ يجعل التقرير يبطؤ مع نموّ الدفتر لا مع حجم السؤال.
    """
    out = {}
    try:
        rows = conn.execute(
            "SELECT entity_id, wage, from_date FROM wage_agreements"
            " ORDER BY entity_id, from_date, id").fetchall()
    except Exception:
        return out                        # قاعدة قبل الترقية
    for r in rows:
        out.setdefault(r["entity_id"], []).append(
            (str(r["from_date"])[:10], round(float(r["wage"]), 2)))
    return out


def _wage_on(hist, on_date):
    """آخر اتفاقٍ لا يتجاوز التاريخ — والقائمة مرتّبة تصاعدياً."""
    found = None
    d = str(on_date)[:10]
    for frm, w in hist:
        if frm <= d:
            found = w
        else:
            break
    return found


def _blank(name):
    return {"name": name, "lines": 0, "weight": 0.0, "wages": 0.0,
            "expected": 0.0, "impact": 0.0, "below": 0, "above": 0,
            "match": 0, "worst": None}


def report(conn, date_from=None, date_to=None, only_deviations=False):
    """انحرافات الأجرة سطراً سطراً، ومجمَّعةً بالعميل."""
    p = []
    c = ""
    if date_from:
        c += " AND i.invoice_date>=?"
        p.append(date_from)
    if date_to:
        c += " AND i.invoice_date<=?"
        p.append(date_to)
    rows = conn.execute(
        "SELECT i.id inv_id, i.invoice_no, i.kind, i.invoice_date,"
        "  i.customer_id, e.name party,"
        "  COALESCE(e.agreed_wage,0) cur_agreed,"
        "  it.registered_weight wt, it.wage_per_gram wpg, it.wages wg,"
        "  w.work_order_no wo, w.model_no"
        " FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " LEFT JOIN entities e ON e.id=i.customer_id"
        " LEFT JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE i.is_deleted=0" + c +
        " ORDER BY i.invoice_date, i.id, it.id", p).fetchall()

    hist = _agreements(conn)
    lines, per = [], {}
    no_deal = {}
    tot = _blank("الإجمالي")
    for r in rows:
        wt = float(r["wt"] or 0.0)
        wpg = round(float(r["wpg"] or 0.0), 2)
        sign = 1.0 if r["kind"] == "sale" else -1.0
        agreed = _wage_on(hist.get(r["customer_id"], []), r["invoice_date"])
        if agreed is None:
            agreed = round(float(r["cur_agreed"] or 0.0), 2) or None
            # عمود الجهة احتياطٌ لمن ضُبطت أجرته قبل وجود السجل؛
            # وإن كان صفراً فلا اتفاق أصلاً.
        party = r["party"] or "—"
        if agreed is None:
            d = no_deal.setdefault(r["customer_id"], _blank(party))
            d["lines"] += 1
            d["weight"] = round(d["weight"] + wt, 3)
            d["wages"] = round(d["wages"] + wt * wpg * sign, 2)
            continue

        diff = round(wpg - agreed, 2)
        impact = round(diff * wt * sign, 2)
        rec = {
            "invoice_no": r["invoice_no"], "kind": r["kind"],
            "date": str(r["invoice_date"])[:10], "party": party,
            "entity_id": r["customer_id"],
            "wo_no": r["wo"] or "—",
            "model": (r["model_no"] or "").strip() or "—",
            "weight": round(wt, 3), "applied": wpg, "agreed": agreed,
            "diff": diff, "impact": impact,
            "state": ("أقلّ من المتفق" if diff < -EPS else
                      ("أعلى من المتفق" if diff > EPS else "مطابق")),
        }
        if not only_deviations or abs(diff) > EPS:
            lines.append(rec)

        a = per.setdefault(r["customer_id"], _blank(party))
        for acc in (a, tot):
            acc["lines"] += 1
            acc["weight"] = round(acc["weight"] + wt, 3)
            acc["wages"] = round(acc["wages"] + wt * wpg * sign, 2)
            acc["expected"] = round(acc["expected"] + wt * agreed * sign, 2)
            acc["impact"] = round(acc["impact"] + impact, 2)
            if diff < -EPS:
                acc["below"] += 1
            elif diff > EPS:
                acc["above"] += 1
            else:
                acc["match"] += 1
        if a["worst"] is None or impact < a["worst"]["impact"]:
            a["worst"] = rec

    for a in list(per.values()) + [tot]:
        w = a["weight"] or 1.0
        a["avg_applied"] = round(abs(a["wages"]) / w, 2) if a["weight"] else 0
        a["avg_agreed"] = round(abs(a["expected"]) / w, 2) if a["weight"] else 0
        a["match_pct"] = round(a["match"] * 100.0 / (a["lines"] or 1), 1)

    parties = sorted(per.values(), key=lambda x: x["impact"])
    missing = sorted(no_deal.values(), key=lambda x: -x["weight"])
    lines.sort(key=lambda x: (x["impact"], x["date"]))

    return {
        "date_from": date_from, "date_to": date_to,
        "lines": lines, "parties": parties, "missing": missing,
        "total": tot,
        "loss": round(sum(x["impact"] for x in lines if x["impact"] < 0), 2),
        "gain": round(sum(x["impact"] for x in lines if x["impact"] > 0), 2),
        "deviations": sum(1 for x in lines if abs(x["diff"]) > EPS),
    }


def verdict(r, money=None, fmt=None):
    """جملةٌ تُقرأ — والمنسِّق من الواجهة كعادة النظام."""
    money = money or (lambda v: f"{v:,.2f}")
    fmt = fmt or (lambda v: f"{v:,.3f}")
    t = r["total"]
    out = []
    if not t["lines"] and not r["missing"]:
        return ["لا فواتير في هذه الفترة."]
    if not t["lines"]:
        out.append("لا جهةَ لها أجرةٌ متفق عليها بعد — "
                   "اكتب الاتفاق في بطاقة الجهة ليصير للمقارنة مرجع.")
    else:
        out.append(
            f"{t['lines']:,} سطراً قِيس، منها {t['match']:,} مطابقٌ "
            f"للمتفق عليه ({t['match_pct']:,.1f}%).")
        if r["loss"] < -0.005:
            out.append(
                f"أقلّ من المتفق عليه بـ {money(abs(r['loss']))} ريال — "
                "هذا ربحٌ لم يدخل الصندوق ولا يظهر في أي قيد.")
        if r["gain"] > 0.005:
            out.append(
                f"وأعلى من المتفق عليه بـ {money(r['gain'])} ريال — "
                "راجعها قبل أن يراجعها العميل.")
        if abs(t["impact"]) <= 0.005 and r["deviations"]:
            out.append("والصافي صفرٌ تقريباً: انحرافاتٌ يُقاصّ بعضُها "
                       "بعضاً — وهي انحرافاتٌ على أي حال.")
        worst = min((p for p in r["parties"]), key=lambda p: p["impact"],
                    default=None)
        if worst is not None and worst["impact"] < -0.005:
            out.append(
                f"أكبر فارقٍ عند «{worst['name']}»: "
                f"{money(abs(worst['impact']))} ريال — متوسط المطبَّق "
                f"{worst['avg_applied']:,.2f} مقابل "
                f"{worst['avg_agreed']:,.2f} متفقاً عليه.")
    if r["missing"]:
        names = "، ".join(x["name"] for x in r["missing"][:3])
        out.append(
            f"و{len(r['missing'])} جهةً بلا اتفاقٍ مكتوب ({names}) — "
            "لا يُقاس عليها شيء حتى تُكتب أجرتها.")
    return out
