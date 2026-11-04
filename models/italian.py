# -*- coding: utf-8 -*-
"""حساب «ايطالي / نواعم» — كشف الرقمين التجميعيين 0010 و00010 (5.1.9).

الرقمان رصيدٌ وزني يزيد بالتوريد والمرتجع وينقص بالبيع، ولا حساب لهما
في الدليل (وزنهما داخل الذهب المشغول). فكشفُهما يُبنى من المستندات
نفسها، سطراً لكل حركة:

  · توريد / رصيد افتتاحي  ← سطور دفعات التوريد (`wo_batch_lines`) بقيدٍ قائم
  · بيع                   ← بنود فواتير البيع: إلى العميل (دائن)
  · مرتجع                 ← بنود فواتير المرتجع: من العميل (مدين)

والرصيد المسجَّل على بطاقتي الرقمين هو ما تعرضه لوحة التحكم ودليل
الموديلات. إن خالف مجموعَ المستندات (رصيدٌ دخل قبل أن تُحفظ سطور
الدفعات، أو تعديلٌ قديم لم يُحرّكه) ظهر الفرق سطراً أولاً باسمه —
فيتطابق آخر الكشف مع ما تعرضه الشاشات، ولا يُخفى الفرق.
"""
from models.inventory import BULK_WO_NOS

CODE = "@italian"                      # رمزه في لوحات لوحة التحكم
NAME = "ايطالي / نواعم"
EPS = 0.0005

# ترتيب حركات اليوم الواحد: الوارد قبل الصادر
_RANK = {"open": 0, "supply": 1, "return": 2, "sale": 3}
LABEL = {"open": "رصيد سابق غير مفصّل", "opening": "رصيد افتتاحي",
         "supply": "توريد", "sale": "بيع", "return": "مرتجع"}


def cards(conn):
    """بطاقتا الرقمين القائمتان: [{id, no, balance}]."""
    q = ",".join("?" * len(BULK_WO_NOS))
    return [{"id": r["id"], "no": r["work_order_no"],
             "balance": round(float(r["registered_weight"] or 0), 3)}
            for r in conn.execute(
                "SELECT id, work_order_no, registered_weight FROM work_orders"
                f" WHERE is_bulk=1 AND is_deleted=0 AND work_order_no IN ({q})"
                " ORDER BY work_order_no DESC", list(BULK_WO_NOS))]


def movements(conn, ids=None):
    """كل حركات الرقمين من المستندات — بترتيبها: [{date, kind, doc,
    party, no, debit, credit, ref}]."""
    if ids is None:
        ids = [c["id"] for c in cards(conn)]
    ids = [int(i) for i in ids]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    out = []
    for r in conn.execute(
            "SELECT e.entry_date d, e.id eid, COALESCE(e.doc_no,'') ref,"
            " e.description dsc, l.registered_weight w, l.id lid,"
            " w.work_order_no no"
            " FROM wo_batch_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
            " JOIN work_orders w ON w.id=l.work_order_id"
            f" WHERE l.work_order_id IN ({q})", ids):
        w = round(float(r["w"] or 0), 3)
        if abs(w) < EPS:
            continue
        opening = "افتتاحي" in (r["dsc"] or "")
        doc = r["ref"] or f"دفعة {r['eid']}"     # رقم الدفعة أو مرجعها
        out.append({"date": r["d"] or "", "kind": "supply",
                    "label": LABEL["opening" if opening else "supply"],
                    "doc": doc,
                    "party": ("رصيد افتتاحي مخزني" if opening
                              else "من خزينة التصنيع"),
                    "no": r["no"], "debit": max(w, 0.0),
                    "credit": max(-w, 0.0), "ref": ("entry", r["eid"]),
                    "_id": r["lid"]})
    for r in conn.execute(
            "SELECT i.invoice_date d, i.id iid, i.invoice_no inv, i.kind k,"
            " COALESCE(en.name,'—') party, it.registered_weight w,"
            " it.id itid, w.work_order_no no"
            " FROM invoice_items it"
            " JOIN invoices i ON i.id=it.invoice_id AND i.is_deleted=0"
            " LEFT JOIN entities en ON en.id=i.customer_id"
            " JOIN work_orders w ON w.id=it.work_order_id"
            f" WHERE it.work_order_id IN ({q})", ids):
        w = round(float(r["w"] or 0), 3)
        if abs(w) < EPS:
            continue
        sale = r["k"] == "sale"
        out.append({"date": r["d"] or "", "kind": "sale" if sale
                    else "return", "label": LABEL["sale" if sale
                                                   else "return"],
                    "doc": r["inv"] or "",
                    "party": ("إلى " if sale else "من ") + r["party"],
                    "no": r["no"], "debit": 0.0 if sale else w,
                    "credit": w if sale else 0.0,
                    "ref": ("invoice", r["iid"]), "_id": r["itid"]})
    out.sort(key=lambda m: (m["date"], _RANK[m["kind"]], m["_id"]))
    return out


def statement(conn, date_from=None, date_to=None):
    """الكشف: رصيدٌ أول (ما قبل الفترة) ثم الحركات برصيدٍ جارٍ، والإجمالي.

    `gap` = رصيد البطاقتين − مجموع المستندات: يُعرض سطراً أول باسمه."""
    cs = cards(conn)
    mv = movements(conn, [c["id"] for c in cs])
    card_total = round(sum(c["balance"] for c in cs), 3)
    doc_total = round(sum(m["debit"] - m["credit"] for m in mv), 3)
    gap = round(card_total - doc_total, 3)
    d1, d2 = str(date_from or ""), str(date_to or "")
    before = [m for m in mv if d1 and m["date"] < d1]
    inside = [m for m in mv if (not d1 or m["date"] >= d1)
              and (not d2 or m["date"] <= d2)]
    opening = round(gap + sum(m["debit"] - m["credit"] for m in before), 3)
    rows, bal = [], opening
    if abs(gap) > 0.005 and not d1:
        # بلا فترة: الفرق سطرٌ أول باسمه (لا رصيدٌ أول صامت)
        rows.append({"date": "", "kind": "open", "label": LABEL["open"],
                     "doc": "", "party": "قبل تفصيل الحركة في النظام",
                     "no": "", "debit": max(gap, 0.0),
                     "credit": max(-gap, 0.0), "balance": gap, "ref": None})
        opening = 0.0
        bal = gap
    for m in inside:
        bal = round(bal + m["debit"] - m["credit"], 3)
        rows.append({**{k: v for k, v in m.items() if k != "_id"},
                     "balance": bal})
    deb = round(sum(r["debit"] for r in rows), 3)
    cred = round(sum(r["credit"] for r in rows), 3)
    return {"cards": cs, "opening": opening, "rows": rows,
            "debit": deb, "credit": cred, "closing": round(bal, 3),
            "card_total": card_total, "doc_total": doc_total, "gap": gap,
            "date_from": d1, "date_to": d2,
            "counts": {k: sum(1 for r in rows if r["kind"] == k)
                       for k in ("supply", "sale", "return")}}


def panel_row(conn, date_from=None, date_to=None):
    """صفّه في لوحة التحكم: مدين الفترة ودائنها ورصيدها — كحسابٍ عادي."""
    st = statement(conn, date_from, date_to)
    deb = st["debit"]
    cred = st["credit"]
    if st["date_from"]:
        # كالحسابات: صافي حركة الفترة (والرصيد الأول خارجها)
        bal = round(deb - cred, 3)
    else:
        bal = st["closing"]
    return {"code": CODE, "name": f"{NAME} (0010 · 00010)",
            "gold_debit": deb, "gold_credit": cred, "gold_balance": bal,
            "cash_debit": 0.0, "cash_credit": 0.0, "cash_balance": 0.0,
            "virtual": True}
