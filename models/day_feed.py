# -*- coding: utf-8 -*-
"""حركة اليوم للمدير (5.2.6) — كل مستندٍ في يومٍ واحد، بنوعه وتفصيله.

ما يسأله المدير كل مساء: «ماذا جرى اليوم؟ وأمس؟» — بيعٌ لمن، ومرتجعٌ
ممن، وقبضٌ بأي عيار، وصرفٌ لمن، وتوريدٌ من المصنع… هنا كلها مصنّفةً
بنوعها (المصدر نفسه: `journal.day_book` الذي تقرأ منه شاشة «الإغلاق
اليومي»)، ولكل مستندٍ تفصيله الخاص:

  · فاتورة بيع / مرتجع: موديلاتها — كم قطعة من كل موديل ووزنها، وتحت كل
    موديلٍ أرقام تشغيله بأوزانها؛ والايطالي بوزنه؛ والأجور والضريبة.
  · سند قبض / صرف: أسطره — كل عيارٍ بوزنه ومكافئه، والنقد.
  · توريد: الأطقم الواردة بموديلاتها وأوزانها.
  · غيرها: أسطر القيد — الحساب ومدينه ودائنه.

قراءةٌ محضة: لا يُنشئ شيئاً ولا يغيّر شيئاً.
"""
from models import day_close

GROUPS = (
    ("sale", "المبيعات"),
    ("sale_return", "المرتجع"),
    ("receipt", "سندات القبض"),
    ("payment", "سندات الصرف"),
    ("supply", "الوارد من التصنيع (توريد)"),
    ("purchase", "المشتريات"),
    # 5.6.0: القيد اليومي والتسكير بابان مستقلان (كانا في «عمليات أخرى»)
    ("manual", "القيود اليومية"),
    ("fixing", "التسكيرات"),
    ("other", "عمليات أخرى"),
)
GROUP_LABEL = dict(GROUPS)
LINE_LABEL = {"gold": "ذهب", "cash": "نقد", "wage": "أجور",
              "wages": "أجور", "disc": "خصم"}


def _reversals(conn):
    try:
        rows = conn.execute("SELECT src_entry_id, rev_entry_id, src_no,"
                            " rev_no FROM doc_reversals").fetchall()
    except Exception:
        return {}, {}
    return ({r["src_entry_id"]: r["rev_no"] for r in rows},
            {r["rev_entry_id"]: r["src_no"] for r in rows})


def _party(conn, entity_id):
    if not entity_id:
        return ""
    r = conn.execute("SELECT name FROM entities WHERE id=?",
                     (entity_id,)).fetchone()
    return r["name"] if r else ""


def _models(items):
    """أطقمٌ ← موديلاتٌ بقطعها: [{"model","count","weight","items"}]."""
    from models.models_catalog import model_key
    out = {}
    for i in items:
        m = out.setdefault(i["model"] or "— بلا موديل —",
                           {"model": i["model"] or "— بلا موديل —",
                            "count": 0, "weight": 0.0, "items": []})
        m["count"] += 1
        m["weight"] = round(m["weight"] + i["weight"], 3)
        m["items"].append(i)
    res = list(out.values())
    res.sort(key=lambda m: model_key(m["model"]))
    for m in res:
        m["items"].sort(key=lambda i: str(i["wo"]))
    return res


def _invoice(conn, sid):
    inv = conn.execute("SELECT * FROM invoices WHERE id=?",
                       (sid,)).fetchone()
    if not inv:
        return None
    sets, italian, wages_only = [], [], []
    for r in conn.execute(
            "SELECT it.registered_weight rw, it.wages, it.wage_per_gram,"
            " COALESCE(it.line_note,'') note, w.work_order_no wo,"
            " COALESCE(TRIM(w.model_no),'') model,"
            " COALESCE(w.is_bulk,0) bulk, COALESCE(w.is_service,0) svc"
            " FROM invoice_items it LEFT JOIN work_orders w"
            " ON w.id=it.work_order_id WHERE it.invoice_id=? ORDER BY it.id",
            (sid,)):
        if r["svc"]:
            wages_only.append({"note": r["note"],
                               "amount": float(r["wages"] or 0)})
            continue
        row = {"wo": r["wo"] or "—", "model": r["model"],
               "weight": round(float(r["rw"] or 0), 3),
               "wages": float(r["wages"] or 0)}
        (italian if r["bulk"] else sets).append(row)
    return {
        "kind": inv["kind"], "party": _party(conn, inv["customer_id"]),
        "models": _models(sets), "italian": italian,
        "wages_only": wages_only,
        "n_sets": len(sets),
        "weight": round(sum(i["weight"] for i in sets + italian), 3),
        "set_weight": round(sum(i["weight"] for i in sets), 3),
        "italian_weight": round(sum(i["weight"] for i in italian), 3),
        "wages": float(inv["total_wages"] or 0),
        "vat": float(inv["vat_amount"] or 0),
        "grand": float(inv["grand_total"] or 0),
        "note": (inv["description"] or "").strip(),
    }


def _voucher(conn, sid):
    v = conn.execute("SELECT * FROM vouchers WHERE id=?", (sid,)).fetchone()
    if not v:
        return None
    keys = v.keys()
    party = _party(conn, v["customer_id"]) if "customer_id" in keys else ""
    # سندٌ على حسابٍ من الدليل لا على جهة (4.x): اسم الحساب المقابل
    if not party and v["target_account_id"]:
        a = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                         (v["target_account_id"],)).fetchone()
        party = f"{a['code']} — {a['name']}" if a else ""
    lines = []
    for ln in conn.execute("SELECT * FROM voucher_lines WHERE voucher_id=?"
                           " ORDER BY id", (sid,)):
        lines.append({
            "kind": ln["line_kind"] or "",
            "label": LINE_LABEL.get(ln["line_kind"] or "",
                                    ln["line_kind"] or "—"),
            "weight": round(float(ln["gold_weight"] or 0), 3),
            "karat": int(ln["gold_karat"] or 0),
            "equiv": round(float(ln["gold_equiv18"] or 0), 3),
            "amount": round(float(ln["cash_amount"] or 0), 2),
            "note": (ln["line_notes"] or "").strip()})
    if not lines:
        # سندٌ قديم بلا أسطر تفصيلية: ذهبه ونقده من رأسه
        if float(v["gold_weight"] or 0):
            lines.append({"kind": "gold", "label": "ذهب",
                          "weight": round(float(v["gold_weight"]), 3),
                          "karat": int(v["gold_karat"] or 18),
                          "equiv": round(float(v["gold_equiv18"] or 0), 3),
                          "amount": 0.0, "note": ""})
        if float(v["cash_amount"] or 0):
            lines.append({"kind": "cash", "label": "نقد", "weight": 0.0,
                          "karat": 0, "equiv": 0.0,
                          "amount": round(float(v["cash_amount"]), 2),
                          "note": ""})
    karats = {}
    for ln in lines:
        if ln["kind"] == "gold" and ln["weight"]:
            k = karats.setdefault(ln["karat"], {"karat": ln["karat"],
                                                "weight": 0.0, "equiv": 0.0})
            k["weight"] = round(k["weight"] + ln["weight"], 3)
            k["equiv"] = round(k["equiv"] + ln["equiv"], 3)
    return {
        "kind": v["kind"], "party": party, "lines": lines,
        "karats": sorted(karats.values(), key=lambda k: -k["karat"]),
        "gold_equiv": round(sum(k["equiv"] for k in karats.values()), 3),
        "cash": round(sum(ln["amount"] for ln in lines
                          if ln["kind"] == "cash"), 2),
        "note": (v["notes"] or "").strip(),
    }


def _supply(conn, eid):
    rows = conn.execute(
        "SELECT work_order_no wo, COALESCE(TRIM(model_no),'') model,"
        " registered_weight rw, gold_weight g, small_stones s,"
        " big_stones b, COALESCE(is_bulk,0) bulk FROM work_orders"
        " WHERE entry_id=? AND is_deleted=0 ORDER BY id", (eid,)).fetchall()
    items = [{"wo": r["wo"], "model": r["model"],
              "weight": round(float(r["rw"] or 0), 3)} for r in rows
             if not r["bulk"]]
    bulk = [{"wo": r["wo"], "model": r["model"],
             "weight": round(float(r["rw"] or 0), 3)} for r in rows
            if r["bulk"]]
    return {"models": _models(items), "italian": bulk,
            "n_sets": len(items), "party": _supply_source(conn, eid),
            "weight": round(sum(i["weight"] for i in items + bulk), 3)}


def _supply_source(conn, eid):
    """الطرف في الوارد هو **مصدره** لا وجهته (5.7.4): البضاعة واردةٌ من
    التصنيع، فيُكتب «خزينة التصنيع» — الحساب الدائن بالذهب في القيد —
    لا الذهب المشغول الذي دخلته."""
    from models.journal import short_name
    r = conn.execute(
        "SELECT a.code, a.name FROM journal_lines l JOIN accounts a"
        " ON a.id=l.account_id WHERE l.entry_id=? AND l.gold_credit>0"
        " ORDER BY l.gold_credit DESC, l.id LIMIT 1", (eid,)).fetchone()
    return short_name(r["code"], r["name"]) if r else "خزينة التصنيع"


def _lines(conn, eid):
    return [{"account": f"{r['code']} — {r['name']}",
             "gd": round(float(r["gold_debit"] or 0), 3),
             "gc": round(float(r["gold_credit"] or 0), 3),
             "cd": round(float(r["cash_debit"] or 0), 2),
             "cc": round(float(r["cash_credit"] or 0), 2),
             "desc": (r["line_desc"] or "").strip()}
            for r in conn.execute(
                "SELECT l.*, a.code, a.name FROM journal_lines l"
                " JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?"
                " ORDER BY l.id", (eid,))]


def _group(d):
    src, op = d.get("src"), d.get("op") or ""
    if src == "invoices":
        return "sale_return" if op == "مرتجع" else "sale"
    if src == "vouchers":
        return "receipt" if op == "قبض" else "payment"
    if src == "work_orders":
        return "supply"
    if src in ("purchases", "set_purchases"):
        return "purchase"
    if src == "fixing_ops":
        return "fixing"
    if src in (None, "", "manual"):
        return "manual"
    return "other"


def _doc(conn, d, rev_of, rev_src):
    """مستندٌ من دفتر اليومية بتفصيله — مشتركٌ بين اليوم والفترة."""
    g = _group(d)
    doc = {"no": d["doc_no"], "op": d["op"], "src": d.get("src"),
           "sid": d.get("sid"), "eid": d["eid"], "group": g,
           "date": d.get("date") or "",
           "time": (d.get("when") or "")[11:16],
           "who": d.get("who") or "", "desc": d.get("desc") or "",
           "gold": float(d.get("gold") or 0),
           "cash": float(d.get("cash") or 0),
           "accounts": d.get("accounts") or "",
           "reversed_by": rev_of.get(d["eid"], ""),
           "reverses": rev_src.get(d["eid"], ""), "party": "",
           "detail": None}
    try:
        if g in ("sale", "sale_return"):
            doc["detail"] = _invoice(conn, d["sid"])
        elif g in ("receipt", "payment"):
            doc["detail"] = _voucher(conn, d["sid"])
        elif g == "supply":
            doc["detail"] = _supply(conn, d["eid"])
    except Exception:
        doc["detail"] = None
    if doc["detail"] is None:
        doc["lines"] = _lines(conn, d["eid"])
        doc["party"] = _line_party(doc["lines"])
    else:
        doc["party"] = doc["detail"].get("party", "")
        if g in ("supply",):
            doc["lines"] = []
    doc["weight"] = _weight_of(doc)
    return doc


def _line_party(lines):
    """الطرف في قيدٍ بلا مستند: أول حسابٍ غير الصناديق والمخازن."""
    for ln in lines or []:
        code = (ln["account"] or "").split(" — ")[0]
        if code[:2] not in ("11", "12", "13", "14", "15"):
            return ln["account"]
    return (lines[0]["account"] if lines else "")


def _weight_of(doc):
    """وزن المستند المعروض في السطر (مكافئ 18): الأطقم للفاتورة والتوريد،
    والمكافئ للسند، ومدين الذهب لغيرهما."""
    det = doc.get("detail") or {}
    if doc["group"] in ("sale", "sale_return", "supply") and det:
        return round(float(det.get("weight") or 0), 3)
    if doc["group"] in ("receipt", "payment") and det:
        return round(float(det.get("gold_equiv") or 0), 3)
    return round(float(doc.get("gold") or 0), 3)


def _totals(key, docs):
    t = {"count": len(docs)}
    dets = [x["detail"] for x in docs if x.get("detail")]
    if key in ("sale", "sale_return"):
        t["sets"] = sum(x["n_sets"] for x in dets)
        t["weight"] = round(sum(x["weight"] for x in dets), 3)
        t["wages"] = round(sum(x["wages"] for x in dets), 2)
        t["grand"] = round(sum(x["grand"] for x in dets), 2)
    elif key in ("receipt", "payment"):
        ks = {}
        for x in dets:
            for k in x["karats"]:
                a = ks.setdefault(k["karat"], {"karat": k["karat"],
                                               "weight": 0.0, "equiv": 0.0})
                a["weight"] = round(a["weight"] + k["weight"], 3)
                a["equiv"] = round(a["equiv"] + k["equiv"], 3)
        t["karats"] = sorted(ks.values(), key=lambda k: -k["karat"])
        t["gold_equiv"] = round(sum(k["equiv"] for k in ks.values()), 3)
        t["cash"] = round(sum(x["cash"] for x in dets), 2)
    elif key == "supply":
        t["sets"] = sum(x["n_sets"] for x in dets)
        t["weight"] = round(sum(x["weight"] for x in dets), 3)
    else:
        t["weight"] = round(sum(x["weight"] for x in docs), 3)
        t["cash"] = round(sum(x["cash"] for x in docs), 2)
    return t


def period(conn, date_from, date_to, group=None, limit=1500):
    """مستندات فترةٍ (يومٍ أو أكثر) بتفصيلها — وبنوعٍ واحدٍ إن طُلب (5.6.0).

    {"from","to","group","docs":[…الأحدث أولاً],"counts":{نوع: عدد},
     "totals": إجماليات النوع المختار (أو كل نوعٍ إن لم يُختر)}.
    الإحصاء (العدد بكل نوع) من الفترة كلها، والتفصيل لما يُعرض وحده."""
    from models import journal
    rows = journal.day_book(conn, date_from, date_to, limit=20000)
    rev_of, rev_src = _reversals(conn)
    counts = {k: 0 for k, _t in GROUPS}
    pick = []
    for d in rows:
        g = _group(d)
        counts[g] += 1
        if group in (None, "", "all") or g == group:
            pick.append(d)
    pick = pick[-int(limit):] if limit else pick
    docs = [_doc(conn, d, rev_of, rev_src) for d in pick]
    docs.reverse()                 # الأحدث أولاً
    by = {}
    for x in docs:
        by.setdefault(x["group"], []).append(x)
    totals = {k: _totals(k, v) for k, v in by.items()}
    return {"from": date_from, "to": date_to, "group": group or "all",
            "docs": docs, "counts": counts, "totals": totals,
            "count": len(rows), "shown": len(docs)}


def day(conn, date):
    """{"date","summary" (من الإغلاق اليومي),"groups":[{key,title,docs,
    totals}],"count"} — كل مستندات اليوم بتفاصيلها."""
    s = day_close.summary(conn, date)
    rev_of, rev_src = _reversals(conn)
    groups = {k: [] for k, _t in GROUPS}
    for d in s["docs"]:
        doc = _doc(conn, d, rev_of, rev_src)
        groups[doc["group"]].append(doc)
    out = []
    for key, title in GROUPS:
        docs = groups[key]
        if not docs:
            continue
        out.append({"key": key, "title": title, "docs": docs,
                    "totals": _totals(key, docs)})
    return {"date": s["date"], "summary": s, "groups": out,
            "count": s["count"]}
