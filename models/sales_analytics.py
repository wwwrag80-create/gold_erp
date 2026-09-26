# -*- coding: utf-8 -*-
"""تحليل مبيعات العملاء (Sales Analytical Dashboard).

أداة رقابة إدارية بأربع لوحات لكل عميل خلال فترة:

* **المبيعات**: إجمالي فواتير البيع (وزناً وأجوراً وعدداً).
* **المرتجعات**: إجمالي فواتير المرتجع.
* **المباع الفعلي (Net Sold)**: أرقام التشغيل المباعة التي لم تُرتجع
  لنفس العميل — يُحسب باستبعاد أرقام تشغيل المرتجعات من المبيعات.
* **التحصيل**: إجمالي المقبوض نقداً وذهباً من سندات القبض للعميل.

كل لوحة لها تفاصيل قابلة للعرض (رقم التشغيل والوزن المقيد).
"""


def _period_clause(alias, date_from, date_to, params):
    clause = ""
    if date_from:
        clause += f" AND {alias}>=?"
        params.append(date_from)
    if date_to:
        clause += f" AND {alias}<=?"
        params.append(date_to)
    return clause


def _opening_weight(conn, customer_id, date_from=None, date_to=None):
    """وزن الرصيد الافتتاحي ضمن الفترة — صفر خارجها."""
    r = opening_balance_row(conn, customer_id, date_from, date_to)
    return round(float(r["weight"]) if r else 0.0, 3)


def sales_panel(conn, customer_id, date_from=None, date_to=None):
    p = [customer_id]
    c = _period_clause("i.invoice_date", date_from, date_to, p)
    r = conn.execute(
        "SELECT COUNT(DISTINCT i.id) n, COALESCE(SUM(i.total_weight),0) w,"
        " COALESCE(SUM(i.total_wages),0) g"
        " FROM invoices i WHERE i.customer_id=? AND i.kind='sale'"
        " AND i.is_deleted=0" + c, p).fetchone()
    ob = _opening_weight(conn, customer_id, date_from, date_to)
    # الرصيد الافتتاحي جزء من إجمالي ما على العميل، فيُضاف للوزن
    return {"opening": ob, "count": r["n"], "weight": round(round(r["w"] + ob, 3), 3),
            "wages": round(r["g"], 2)}


def returns_panel(conn, customer_id, date_from=None, date_to=None):
    p = [customer_id]
    c = _period_clause("i.invoice_date", date_from, date_to, p)
    r = conn.execute(
        "SELECT COUNT(DISTINCT i.id) n, COALESCE(SUM(i.total_weight),0) w,"
        " COALESCE(SUM(i.total_wages),0) g"
        " FROM invoices i WHERE i.customer_id=? AND i.kind='sale_return'"
        " AND i.is_deleted=0" + c, p).fetchone()
    return {"count": r["n"], "weight": round(r["w"], 3),
            "wages": round(r["g"], 2)}


def _sold_items(conn, customer_id, date_from, date_to):
    """أرقام التشغيل المباعة (رقم التشغيل، الوزن المقيد، رقم الفاتورة)."""
    p = [customer_id]
    c = _period_clause("i.invoice_date", date_from, date_to, p)
    return conn.execute(
        "SELECT w.work_order_no wo, it.work_order_id wid,"
        " it.registered_weight rw, i.invoice_no inv"
        " FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE i.customer_id=? AND i.kind='sale' AND i.is_deleted=0" + c,
        p).fetchall()


def _returned_wo_ids(conn, customer_id, date_from, date_to):
    """مجموعة أرقام التشغيل المُرتجعة لنفس العميل."""
    p = [customer_id]
    c = _period_clause("i.invoice_date", date_from, date_to, p)
    rows = conn.execute(
        "SELECT DISTINCT it.work_order_id wid FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " WHERE i.customer_id=? AND i.kind='sale_return' AND i.is_deleted=0" + c,
        p).fetchall()
    return {r["wid"] for r in rows}


def _net_by_wo(conn, customer_id, date_from, date_to):
    """صافي كل رقم تشغيل = وزن مبيعاته − وزن مرتجعاته.

    الاستبعاد الكامل للرقم عند وجود أي مرتجع كان يُخفي الجزء المتبقي
    مباعاً. الصحيح محاسبياً هو **الصافي**: لو بيع 00010 بـ20 جم ورُدّ
    منه 5 جم فالمباع الفعلي 15 جم لا صفر.
    """
    sold = _sold_items(conn, customer_id, date_from, date_to)
    p = [customer_id]
    c = _period_clause("i.invoice_date", date_from, date_to, p)
    # التجميع **برقم التشغيل** لا بمعرّف السجل: الرقم التجميعي
    # قد يُشار إليه بأكثر من سجل (توريد قديم · طقم مرتجع مُنشأ)،
    # فالتجميع بالمعرّف يُفوّت مرتجعاته ويُظهر المباع كاملاً.
    ret = conn.execute(
        "SELECT w.work_order_no wno,"
        " COALESCE(SUM(it.registered_weight),0) rw"
        " FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id"
        " LEFT JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE i.customer_id=? AND i.kind='sale_return' AND i.is_deleted=0"
        + c + " GROUP BY w.work_order_no", p).fetchall()
    ret_w = {r["wno"]: float(r["rw"] or 0) for r in ret}

    agg = {}
    for it in sold:
        k = it["wo"]          # رقم التشغيل هو المفتاح
        a = agg.setdefault(k, {"wo": it["wo"], "sold": 0.0, "ref": it["inv"]})
        a["sold"] += float(it["rw"] or 0)
    out = []
    for wno, a in agg.items():
        net = round(a["sold"] - ret_w.get(wno, 0.0), 3)
        if abs(net) > 0.001:
            out.append({"wo": a["wo"], "weight": net, "ref": a["ref"],
                        "sold": round(a["sold"], 3),
                        "returned": round(ret_w.get(wno, 0.0), 3)})
    return sorted(out, key=lambda x: str(x["wo"]))


def opening_balance_row(conn, customer_id, date_from=None, date_to=None):
    """الرصيد الافتتاحي للعميل — **ضمن نطاق التاريخ المحدد**.

    كان يظهر مثبتاً في كل فترة مهما تغيّر التاريخ، وهذا خطأ: القيد
    الافتتاحي له تاريخ محدد، فلا يجوز إظهاره في فترة لا يقع فيها —
    وإلا اختلّت مقارنة الفترات.
    """
    r = conn.execute(
        "SELECT e.account_id FROM entities e WHERE e.id=?",
        (customer_id,)).fetchone()
    if not r or not r["account_id"]:
        return None
    p = [r["account_id"]]
    clause = ""
    if date_from:
        clause += " AND e.entry_date>=?"
        p.append(date_from)
    if date_to:
        clause += " AND e.entry_date<=?"
        p.append(date_to)
    # القاعدة الموحّدة (`models.opening`): كان يُقرأ من البيان وحده،
    # فيسقط القيد اليومي المقابل للأرصدة الافتتاحية وقيدُ فتح السنة
    from models import opening as _opening
    cond, cp = _opening.sql(conn, "e")
    row = conn.execute(
        "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
        " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0 AND l.account_id=?"
        f" AND {cond}" + clause, [p[0]] + cp + p[1:]).fetchone()
    g = round(row["g"] or 0, 3)
    c = round(row["c"] or 0, 2)
    if abs(g) < 0.001 and abs(c) < 0.01:
        return None
    return {"wo": "رصيد افتتاحي", "weight": g, "cash": c, "ref": "—"}


def net_sold_panel(conn, customer_id, date_from=None, date_to=None):
    """المباع الفعلي = صافي وزن كل رقم تشغيل بعد خصم مرتجعاته."""
    net = _net_by_wo(conn, customer_id, date_from, date_to)
    return {"count": len(net),
            "weight": round(sum(x["weight"] for x in net), 3),
            "returned_excluded": 0}


def collection_panel(conn, customer_id, date_from=None, date_to=None):
    """إجمالي التحصيل من سندات القبض للعميل (نقداً وذهباً بمعادل 18)."""
    p = [customer_id]
    c = _period_clause("v.voucher_date", date_from, date_to, p)
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(v.cash_amount),0) cash,"
        " COALESCE(SUM(v.gold_equiv18),0) gold"
        " FROM vouchers v WHERE v.customer_id=? AND v.kind='receipt'"
        " AND v.is_deleted=0" + c, p).fetchone()
    return {"count": r["n"], "cash": round(r["cash"], 2),
            "gold": round(r["gold"], 3)}


def panel_details(conn, panel, customer_id, date_from=None, date_to=None):
    """تفاصيل لوحة معيّنة: قائمة (رقم التشغيل، الوزن المقيد).

    للوحة التحصيل تُعاد قائمة سندات القبض (الرقم، النقد، الذهب).
    """
    if panel == "sales":
        rows = _sold_items(conn, customer_id, date_from, date_to)
        out = [{"wo": r["wo"], "weight": round(r["rw"], 3),
                "ref": r["inv"]} for r in rows]
        # الرصيد الافتتاحي سطر واضح في أعلى القائمة
        ob = opening_balance_row(conn, customer_id, date_from, date_to)
        if ob:
            out.insert(0, ob)
        return out
    if panel == "returns":
        p = [customer_id]
        c = _period_clause("i.invoice_date", date_from, date_to, p)
        rows = conn.execute(
            "SELECT w.work_order_no wo, it.registered_weight rw,"
            " i.invoice_no inv FROM invoice_items it"
            " JOIN invoices i ON i.id=it.invoice_id"
            " JOIN work_orders w ON w.id=it.work_order_id"
            " WHERE i.customer_id=? AND i.kind='sale_return'"
            " AND i.is_deleted=0" + c, p).fetchall()
        return [{"wo": r["wo"], "weight": round(r["rw"], 3),
                 "ref": r["inv"]} for r in rows]
    if panel == "net_sold":
        return _net_by_wo(conn, customer_id, date_from, date_to)
    if panel == "collection":
        p = [customer_id]
        c = _period_clause("v.voucher_date", date_from, date_to, p)
        rows = conn.execute(
            "SELECT v.voucher_no vn, v.cash_amount cash, v.gold_equiv18 gold,"
            " v.voucher_date d FROM vouchers v"
            " WHERE v.customer_id=? AND v.kind='receipt' AND v.is_deleted=0"
            + c, p).fetchall()
        # عمودان مستقلان: التحصيل ذهباً والتحصيل نقداً
        return [{"wo": r["vn"], "weight": round(r["gold"], 2),
                 "cash": round(r["cash"], 2),
                 "ref": f"{r['cash']:,.2f}"} for r in rows]
    return []


def all_panels(conn, customer_id, date_from=None, date_to=None):
    return {
        "sales": sales_panel(conn, customer_id, date_from, date_to),
        "returns": returns_panel(conn, customer_id, date_from, date_to),
        "net_sold": net_sold_panel(conn, customer_id, date_from, date_to),
        "collection": collection_panel(conn, customer_id, date_from, date_to),
    }
