# -*- coding: utf-8 -*-
"""ربحية الموديل — أيّ موديلٍ يكسب المصنع، وأيّه يشغل مكاناً بلا عائد.

**السؤال الذي تجيبه**: النظام يعرف كم طقماً أُنتج من كل موديل وكم
بِيع، ولم يكن يعرف **كم كسب** منه. فقرار «أيّ موديلٍ نُكثر منه» كان
يُتّخذ بالانطباع: ما يراه صاحب المصنع يخرج كثيراً — وهو قد يكون كثيرَ
الخروج قليلَ الأجرة.

**مصدر الربح في مصنع ذهب هو الأجرة لا الذهب**: الذهب يدخل ويخرج
بوزنه (انتقال أصلٍ لا بيع)، والمكسب أجرةُ التصنيع على كل جرام. فهذه
الشاشة تقرأ من `invoice_items` أجرةَ كل طقمٍ بِيع فعلاً — لا الأجرة
المقدَّرة وقت الإنتاج — وتطرح منها المرتجع، فيظهر صافي ما كسبه كل
موديل في الفترة.

**والحجارة تكلفة**: الفصوص والأحجار تدخل الطقم ولا تعود، فتُعرض
أوزانها المنسوبة لكل موديل بجانب أجرته — فمقارنة الأجرة بالحجر تكشف
موديلاً أجرتُه عالية وتكلفة حجره أعلى.

لا تكتب شيئاً ولا تُنشئ قيداً: قراءةٌ محضة من الفواتير.
"""


def _clause(date_from, date_to, params):
    c = ""
    if date_from:
        c += " AND i.invoice_date >= ?"
        params.append(date_from)
    if date_to:
        c += " AND i.invoice_date <= ?"
        params.append(date_to)
    return c


def by_model(conn, date_from=None, date_to=None):
    """صافي كل موديل في الفترة: العدد والوزن والأجرة، مرتّباً بالأجرة.

    البيع موجب والمرتجع سالب في البنود الثلاثة معاً — فالصافي هو ما
    بقي للمصنع فعلاً، لا ما صدرت به فواتير.
    """
    p = []
    clause = _clause(date_from, date_to, p)
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(TRIM(w.model_no),''),'— بلا موديل —') mno,"
        "  SUM(CASE WHEN i.kind='sale' THEN 1 ELSE 0 END) sold_n,"
        "  SUM(CASE WHEN i.kind='sale' THEN 0 ELSE 1 END) ret_n,"
        "  SUM(CASE WHEN i.kind='sale' THEN it.registered_weight"
        "           ELSE -it.registered_weight END) net_w,"
        "  SUM(CASE WHEN i.kind='sale' THEN it.wages"
        "           ELSE -it.wages END) net_wages,"
        "  SUM(CASE WHEN i.kind='sale' THEN COALESCE(w.small_stones,0)"
        "           ELSE -COALESCE(w.small_stones,0) END) small,"
        "  SUM(CASE WHEN i.kind='sale' THEN COALESCE(w.big_stones,0)"
        "           ELSE -COALESCE(w.big_stones,0) END) big"
        " FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE i.is_deleted=0" + clause +
        " GROUP BY mno", p).fetchall()

    out = []
    for r in rows:
        net_w = float(r["net_w"] or 0)
        net_wages = float(r["net_wages"] or 0)
        out.append({
            "model": r["mno"],
            "sold": int(r["sold_n"] or 0),
            "returned": int(r["ret_n"] or 0),
            "net_count": int(r["sold_n"] or 0) - int(r["ret_n"] or 0),
            "net_weight": net_w,
            "wages": net_wages,
            # متوسطٌ محسوبٌ من الصافي لا من أجرة الفاتورة: فاتورةٌ
            # أُعطي فيها الطقم بأجرةٍ خاصّة تظهر هنا كما هي
            "avg_wage": (net_wages / net_w) if net_w else 0.0,
            "small_stones": float(r["small"] or 0),
            "big_stones": float(r["big"] or 0),
        })
    total = sum(x["wages"] for x in out) or 0.0
    for x in out:
        x["share"] = (x["wages"] / total * 100.0) if total else 0.0
    out.sort(key=lambda x: -x["wages"])
    return out


def totals(rows):
    """إجماليات الفترة — تُحسب من الصفوف نفسها فلا تختلف عنها."""
    w = sum(r["net_weight"] for r in rows)
    g = sum(r["wages"] for r in rows)
    return {
        "models": len(rows),
        "net_count": sum(r["net_count"] for r in rows),
        "net_weight": w,
        "wages": g,
        "avg_wage": (g / w) if w else 0.0,
        "small_stones": sum(r["small_stones"] for r in rows),
        "big_stones": sum(r["big_stones"] for r in rows),
    }


def unsold(conn, date_from=None, date_to=None):
    """موديلاتٌ أُنتجت في الفترة ولم يُبَع منها شيء — مالٌ راكد.

    تُقرأ من أوامر التشغيل لا من الفواتير، فهي عمداً خارج `by_model`:
    تلك تقيس ما بِيع، وهذه تقيس ما لم يُبَع. وكلاهما سؤالٌ يُسأل.
    """
    p = []
    c = ""
    if date_from:
        c += " AND COALESCE(substr(w.created_at,1,10),'') >= ?"
        p.append(date_from)
    if date_to:
        c += " AND COALESCE(substr(w.created_at,1,10),'') <= ?"
        p.append(date_to)
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(TRIM(w.model_no),''),'— بلا موديل —') mno,"
        "  COUNT(*) n, ROUND(SUM(w.registered_weight),3) wt,"
        "  ROUND(AVG(w.wage_per_gram),2) wpg"
        " FROM work_orders w"
        " WHERE w.is_deleted=0 AND w.status='in_stock'" + c +
        " GROUP BY mno ORDER BY SUM(w.registered_weight) DESC", p).fetchall()
    return [{"model": r["mno"], "count": int(r["n"] or 0),
             "weight": float(r["wt"] or 0),
             "wage_per_gram": float(r["wpg"] or 0),
             # أجرةٌ لم تُحصَّل بعد: ما كان المصنع سيكسبه لو بِيع
             "potential": float(r["wt"] or 0) * float(r["wpg"] or 0)}
            for r in rows]
