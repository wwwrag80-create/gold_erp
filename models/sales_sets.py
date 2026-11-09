# -*- coding: utf-8 -*-
"""«المبيعات» — أطقم فواتير بيعٍ مختارة: أين صارت؟ (5.2.4)

يختار المستخدم فواتير مبيعاتٍ بعينها (لجهةٍ أو لعدة جهات)، فيُعرض كل طقمٍ
فيها بوزنه، وحاله بعد ذلك البيع:

  · **مباعٌ معه** — لم يُرتجع بعد بيعه له: ما زال عند الجهة نفسها.
  · **مرتجع** — رُدّ بعد هذا البيع (برقم المرتجع وتاريخه)، ومكانه الآن:
    «الخزنة»، أو «عند فلان» إن بِيع بعد رجوعه لجهةٍ أخرى (مندوبٍ آخر).
  · **ملغاة** — الفاتورة نفسها عُكست بمستندٍ عكسي (5.2.1).
  · **رقم تجميعي** — الإيطالي (0010 · 00010) رصيدٌ وزني لا قطعة تُتتبَّع.

الحكم بسلسلة حركة الطقم المنظّمة (`models.wo_moves`) لا بالحالة المخزّنة:
الحركة التالية لهذا البيع في السلسلة هي التي تقول هل رجع.
"""
from models import set_lookup, wo_moves

WITH, RETURNED, REVERSED, BULK = "with", "returned", "reversed", "bulk"
STATUS_LABEL = {WITH: "مباع معه", RETURNED: "مرتجع",
                REVERSED: "ملغاة بعكس", BULK: "رقم تجميعي"}


def _reversed_entries(conn):
    try:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT src_entry_id, rev_no FROM doc_reversals")}
    except Exception:
        return {}


def _rev_entry_ids(conn):
    try:
        return {r[0] for r in conn.execute(
            "SELECT rev_entry_id FROM doc_reversals")}
    except Exception:
        return set()


def pick_list(conn, entity_id=None, date_from=None, date_to=None):
    """فواتير المبيعات للاختيار: الأحدث أولاً، بعدد أطقمها ووزنها — بلا
    مستندات العكس (هي إلغاءٌ لا بيع)."""
    sql = ("SELECT i.id, i.invoice_no, i.invoice_date, i.entry_id,"
           " COALESCE(e.name,'—') party, i.customer_id,"
           " COUNT(it.id) n, COALESCE(SUM(CASE WHEN"
           " COALESCE(w.is_service,0)=0 THEN it.registered_weight END),0) wt"
           " FROM invoices i LEFT JOIN entities e ON e.id=i.customer_id"
           " LEFT JOIN invoice_items it ON it.invoice_id=i.id"
           " LEFT JOIN work_orders w ON w.id=it.work_order_id"
           " WHERE i.is_deleted=0 AND i.kind='sale'"
           " AND COALESCE(e.entity_type,'')<>'internal'")
    args = []
    if entity_id:
        sql += " AND i.customer_id=?"
        args.append(int(entity_id))
    if date_from:
        sql += " AND i.invoice_date>=?"
        args.append(str(date_from))
    if date_to:
        sql += " AND i.invoice_date<=?"
        args.append(str(date_to))
    sql += " GROUP BY i.id ORDER BY i.invoice_date DESC, i.id DESC"
    rev = _reversed_entries(conn)
    revs = _rev_entry_ids(conn)
    out = []
    for r in conn.execute(sql, args):
        if r["entry_id"] in revs:
            continue
        d = dict(r)
        d["reversed_by"] = rev.get(r["entry_id"], "")
        out.append(d)
    return out


def _after_sale(conn, wo, invoice_id):
    """الحركة التالية لهذا البيع في سلسلة الطقم — أو None."""
    seq = [m for m in wo_moves.order(wo_moves.moves_of(conn, wo["id"]),
                                     wo_moves.birth(wo), wo_moves._full(wo))
           if m["kind"] != wo_moves.ADJ]
    for i, m in enumerate(seq):
        if int(m["id"]) == int(invoice_id):
            return seq[i + 1] if i + 1 < len(seq) else None
    return None


def track(conn, invoice_ids):
    """صفٌّ لكل طقمٍ في الفواتير المختارة، بترتيب الفواتير ثم الأطقم.

    {"invoice_id","invoice_no","date","party","wo_no","model_no","weight",
     "status","status_label","ret_no","ret_date","ret_party","where",
     "where_place"}"""
    ids = [int(i) for i in invoice_ids if i]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    rev = _reversed_entries(conn)
    invs = {r["id"]: r for r in conn.execute(
        "SELECT i.id, i.invoice_no, i.invoice_date, i.entry_id,"
        f" COALESCE(e.name,'—') party FROM invoices i LEFT JOIN entities e"
        f" ON e.id=i.customer_id WHERE i.id IN ({q}) AND i.is_deleted=0"
        " AND i.kind='sale'", ids)}
    items = conn.execute(
        "SELECT it.invoice_id, it.registered_weight wt, w.* FROM"
        " invoice_items it JOIN work_orders w ON w.id=it.work_order_id"
        f" WHERE it.invoice_id IN ({q}) AND COALESCE(w.is_service,0)=0"
        " ORDER BY it.invoice_id, it.id", ids).fetchall()
    order = {i: n for n, i in enumerate(
        sorted(invs, key=lambda k: (invs[k]["invoice_date"], k)))}
    out = []
    for it in items:
        inv = invs.get(it["invoice_id"])
        if inv is None:
            continue
        row = {"invoice_id": inv["id"], "invoice_no": inv["invoice_no"],
               "date": inv["invoice_date"], "party": inv["party"],
               "wo_no": it["work_order_no"],
               "model_no": (it["model_no"] or "").strip(),
               "weight": round(float(it["wt"] or 0), 3),
               "standing": float(it["standing_gold"] or 0),
               "ret_no": "", "ret_date": "", "ret_party": "",
               "where": "", "where_place": ""}
        if inv["entry_id"] in rev:
            row["status"] = REVERSED
            row["where"] = f"الفاتورة ملغاة بالمستند {rev[inv['entry_id']]}"
        elif it["is_bulk"]:
            row["status"] = BULK
            row["where"] = "رصيدٌ وزني — لا يُتتبَّع قطعة"
        else:
            nxt = _after_sale(conn, it, inv["id"])
            if nxt is not None and nxt["kind"] == wo_moves.RETURN:
                r = conn.execute(
                    "SELECT i.invoice_no, i.invoice_date,"
                    " COALESCE(e.name,'—') party FROM invoices i"
                    " LEFT JOIN entities e ON e.id=i.customer_id"
                    " WHERE i.id=?", (nxt["id"],)).fetchone()
                row["status"] = RETURNED
                if r:
                    row.update(ret_no=r["invoice_no"],
                               ret_date=r["invoice_date"],
                               ret_party=r["party"])
                w = set_lookup.where_now(conn, it)
                row["where_place"] = w["place"]
                row["where"] = ("الخزنة" if w["place"] == "treasury"
                                else w["label"])
            else:
                row["status"] = WITH
                row["where_place"] = "party"
                row["where"] = f"عند {inv['party']}"
        row["status_label"] = STATUS_LABEL[row["status"]]
        row["_o"] = order.get(inv["id"], 0)
        out.append(row)
    out.sort(key=lambda r: (r["_o"], r["wo_no"]))
    for r in out:
        r.pop("_o", None)
    return out


def summary(rows):
    """الإجماليات: العدد والوزن لكل حال، ومكان المرتجع."""
    def agg(rs):
        return {"n": len(rs), "w": round(sum(r["weight"] for r in rs), 3)}
    singles = [r for r in rows if r["status"] in (WITH, RETURNED)]
    ret = [r for r in rows if r["status"] == RETURNED]
    return {
        "all": agg(rows), "singles": agg(singles),
        "with": agg([r for r in rows if r["status"] == WITH]),
        "returned": agg(ret),
        "ret_treasury": agg([r for r in ret
                             if r["where_place"] == "treasury"]),
        "ret_others": agg([r for r in ret
                           if r["where_place"] in ("party", "split")]),
        "reversed": agg([r for r in rows if r["status"] == REVERSED]),
        "bulk": agg([r for r in rows if r["status"] == BULK]),
        "invoices": len({r["invoice_id"] for r in rows}),
    }
