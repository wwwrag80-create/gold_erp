# -*- coding: utf-8 -*-
"""ملف الجهة — كل ما يخصّ عميلاً في صفحةٍ واحدة.

**السؤال الذي وُجد لأجله**: يتّصل العميل، أو يدخل المكتب، أو يُعرض
اسمه في اجتماع — فيريد صاحب المصنع أن يعرف حالَه **الآن**، لا بعد
أن يفتح سبع شاشات ويجمع بينها بذاكرته:

    كم رصيده؟ · هل تجاوز سقفه؟ · كم من دينه قديم؟
    ماذا جرى معه الشهر الماضي؟ · متى آخر مرةٍ سدّد؟
    أيَّ الموديلات يأخذ؟ · كم يُرجع مما يأخذ؟
    هل أجرته كما اتُّفق؟

وكل جوابٍ من هذه موجودٌ في النظام، لكنه في شاشةٍ غير شاشة الأخرى.
وسبعُ شاشاتٍ تُفتح في مكالمةٍ هاتفية تعني أن أحداً لن يفتحها.

**ولا يُحسب هنا رقمٌ جديد**: كل قسمٍ يُستدعى من مصدره الأصلي —
الأعمار من `aging`، والجسر من `movement`، والرصيد من الدفتر —
فلا يتعارض الملف مع الكشف ولا يختلف رقمٌ عن رقم. وهذا شرطٌ لا
تحسين: تقريرٌ يجمع أرقاماً من مصادر مختلفة يصير مصدراً سادساً
للخلاف بدل أن يكون جواباً.

**ونسبة المرتجع تُقاس بالوزن لا بالعدد**: عميلٌ يُرجع طقماً صغيراً من
عشرة غير عميلٍ يُرجع نصف ما أخذ وزناً.

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
import datetime as _dt

from models import aging, entities, movement
from services.accounting_engine import account_balance

EPS_G = 0.0005
EPS_C = 0.005


def _today():
    return _dt.date.today().isoformat()


def _months_ago(as_of, n=1):
    d = _dt.date.fromisoformat(str(as_of)[:10])
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or not y % 400)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30,
                      31][m - 1])
    return _dt.date(y, m, day).isoformat()


def _top_models(conn, entity_id, date_from=None, date_to=None, limit=8):
    """أكثر ما أخذ من الموديلات — بالصافي بعد المرتجع.

    الإجمالي وحده يضلّل: موديلٌ أخذ منه عشرة وأرجع تسعة ليس موديلَه.
    """
    p = [entity_id]
    c = ""
    if date_from:
        c += " AND i.invoice_date>=?"
        p.append(date_from)
    if date_to:
        c += " AND i.invoice_date<=?"
        p.append(date_to)
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(TRIM(w.model_no),''),'— بلا موديل —') m,"
        "  SUM(CASE WHEN i.kind='sale' THEN 1 ELSE 0 END) sold,"
        "  SUM(CASE WHEN i.kind<>'sale' THEN 1 ELSE 0 END) ret,"
        "  ROUND(SUM(CASE WHEN i.kind='sale' THEN it.registered_weight"
        "             ELSE -it.registered_weight END),3) net_wt,"
        "  ROUND(SUM(CASE WHEN i.kind='sale' THEN it.wages"
        "             ELSE -it.wages END),2) net_wages"
        " FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " LEFT JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE i.is_deleted=0 AND i.customer_id=?" + c +
        " GROUP BY m ORDER BY net_wt DESC LIMIT ?", p + [limit]).fetchall()
    return [{"model": r["m"], "sold": int(r["sold"] or 0),
             "returned": int(r["ret"] or 0),
             "net_count": int(r["sold"] or 0) - int(r["ret"] or 0),
             "weight": float(r["net_wt"] or 0.0),
             "wages": float(r["net_wages"] or 0.0)} for r in rows]


def _flow(conn, entity_id, date_from=None, date_to=None):
    """ما خرج وما رجع وزناً وأجوراً — ومنه تُشتقّ نسبة المرتجع."""
    p = [entity_id]
    c = ""
    if date_from:
        c += " AND i.invoice_date>=?"
        p.append(date_from)
    if date_to:
        c += " AND i.invoice_date<=?"
        p.append(date_to)
    r = conn.execute(
        "SELECT"
        "  ROUND(SUM(CASE WHEN i.kind='sale' THEN it.registered_weight"
        "             ELSE 0 END),3) out_wt,"
        "  ROUND(SUM(CASE WHEN i.kind<>'sale' THEN it.registered_weight"
        "             ELSE 0 END),3) back_wt,"
        "  ROUND(SUM(CASE WHEN i.kind='sale' THEN it.wages ELSE 0 END),2)"
        "    out_wg,"
        "  ROUND(SUM(CASE WHEN i.kind<>'sale' THEN it.wages ELSE 0 END),2)"
        "    back_wg,"
        "  SUM(CASE WHEN i.kind='sale' THEN 1 ELSE 0 END) n_sale,"
        "  SUM(CASE WHEN i.kind<>'sale' THEN 1 ELSE 0 END) n_ret"
        " FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " WHERE i.is_deleted=0 AND i.customer_id=?" + c, p).fetchone()
    out_wt = float(r["out_wt"] or 0.0) if r else 0.0
    back_wt = float(r["back_wt"] or 0.0) if r else 0.0
    return {
        "out_weight": out_wt, "back_weight": back_wt,
        "net_weight": round(out_wt - back_wt, 3),
        "out_wages": float(r["out_wg"] or 0.0) if r else 0.0,
        "back_wages": float(r["back_wg"] or 0.0) if r else 0.0,
        "sold_lines": int(r["n_sale"] or 0) if r else 0,
        "return_lines": int(r["n_ret"] or 0) if r else 0,
        # بالوزن لا بالعدد: طقمٌ صغير من عشرة ليس كنصف ما أخذ وزناً
        "return_pct": (round(back_wt * 100.0 / out_wt, 1)
                       if out_wt > EPS_G else None),
    }


def _last_voucher(conn, entity_id, kind="receipt", as_of=None):
    """آخر سندٍ للجهة — وكم مضى عليه."""
    p = [entity_id, kind]
    c = ""
    if as_of:
        c = " AND voucher_date<=?"
        p.append(as_of)
    r = conn.execute(
        "SELECT voucher_no, voucher_date, gold_equiv18, cash_amount"
        " FROM vouchers WHERE is_deleted=0 AND customer_id=? AND kind=?"
        + c + " ORDER BY voucher_date DESC, id DESC LIMIT 1", p).fetchone()
    if not r:
        return None
    try:
        since = (_dt.date.fromisoformat(str(as_of or _today())[:10])
                 - _dt.date.fromisoformat(str(r["voucher_date"])[:10])).days
    except Exception:
        since = None
    return {"no": r["voucher_no"], "date": str(r["voucher_date"])[:10],
            "gold": round(float(r["gold_equiv18"] or 0.0), 3),
            "cash": round(float(r["cash_amount"] or 0.0), 2),
            "since": since}


def _wage_check(conn, entity_id, date_from, date_to):
    """أجرة الجهة: المتفق عليه، والمطبَّق، وأثر الفرق بالمال."""
    rows = conn.execute(
        "SELECT i.invoice_date d, i.kind, it.registered_weight wt,"
        "  it.wage_per_gram wpg"
        " FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id"
        " WHERE i.is_deleted=0 AND i.customer_id=?"
        "   AND i.invoice_date>=? AND i.invoice_date<=?",
        (entity_id, date_from, date_to)).fetchall()
    agreed_now = entities.agreed_wage(conn, entity_id)
    wt = impact = applied = 0.0
    n_dev = 0
    for r in rows:
        w = float(r["wt"] or 0.0)
        a = entities.agreed_wage_on(conn, entity_id, r["d"])
        sign = 1.0 if r["kind"] == "sale" else -1.0
        wt += w
        applied += w * float(r["wpg"] or 0.0)
        if a is None:
            continue
        d = float(r["wpg"] or 0.0) - a
        if abs(d) > 0.005:
            n_dev += 1
        impact += d * w * sign
    return {
        "agreed": agreed_now,
        "avg_applied": round(applied / wt, 2) if wt > EPS_G else None,
        "lines": len(rows), "deviations": n_dev,
        "impact": round(impact, 2),
    }


def build(conn, entity_id, date_from=None, date_to=None):
    """يجمع الملف كله — كل قسمٍ من مصدره الأصلي."""
    e = entities.get_entity(conn, entity_id)
    if not e:
        raise ValueError("الجهة غير موجودة")
    as_of = str(date_to or _today())[:10]
    d1 = str(date_from or _months_ago(as_of, 1))[:10]

    gold, cash = account_balance(conn, e["account_id"], date_to=as_of)
    lim_c, lim_g = entities.credit_limit(conn, entity_id)

    ag = aging.report(conn, e["entity_type"], as_of, entity_id=entity_id)
    age = ag[0] if ag else None

    bridge = movement.analyze(conn, e["account_id"], d1, as_of)

    return {
        "as_of": as_of, "date_from": d1,
        "entity": {"id": e["id"], "name": e["name"],
                   "type": e["entity_type"],
                   "phone": e["phone"] or "", "vat": e["vat_number"] or "",
                   "account_id": e["account_id"]},
        "balance": {"gold": round(gold, 3), "cash": round(cash, 2)},
        "limit": _limit_state(lim_c, lim_g, cash, gold),
        "aging": age,
        "bridge": bridge,
        "models": _top_models(conn, entity_id, d1, as_of),
        "models_life": _top_models(conn, entity_id),
        "flow": _flow(conn, entity_id, d1, as_of),
        "flow_life": _flow(conn, entity_id),
        "last_receipt": _last_voucher(conn, entity_id, "receipt", as_of),
        "last_payment": _last_voucher(conn, entity_id, "payment", as_of),
        "wage": _wage_check(conn, entity_id, d1, as_of),
    }


def _limit_state(lim_c, lim_g, cash, gold):
    """حالة السقف: صفرٌ يعني بلا حدّ لا حدّاً صفرياً."""
    def _one(limit, used):
        if limit <= 0:
            return {"limit": 0.0, "used": round(used, 3), "pct": None,
                    "over": False, "free": None}
        pct = round(used * 100.0 / limit, 1)
        return {"limit": round(limit, 3), "used": round(used, 3),
                "pct": pct, "over": used > limit,
                "free": round(limit - used, 3)}
    return {"cash": _one(lim_c, cash), "gold": _one(lim_g, gold)}


def verdict(d, fmt=None, money=None):
    """جملٌ تُقرأ قبل الأرقام — والمنسِّق من الواجهة."""
    fmt = fmt or (lambda v: f"{v:,.3f}")
    money = money or (lambda v: f"{v:,.2f}")
    out = []
    b = d["balance"]
    if abs(b["gold"]) < EPS_G and abs(b["cash"]) < EPS_C:
        out.append("الحساب متزن — لا شيء له ولا عليه.")
    else:
        # **كل بعدٍ بجهته**: قد يكون الوزن عليه والنقد له — وهي حالة
        # شائعة في مصنع ذهب. جملةٌ واحدة تجمعهما بجهةٍ واحدة تقلب
        # معنى أحدهما، فيقرأ المدير «عليه» وهو دائن.
        parts = []
        if abs(b["gold"]) >= EPS_G:
            parts.append(
                ("عليه " if b["gold"] > 0 else "له عندنا ")
                + f"{fmt(abs(b['gold']))} وزناً")
        if abs(b["cash"]) >= EPS_C:
            parts.append(
                ("وعليه " if b["cash"] > 0 else "وله عندنا ")
                + f"{money(abs(b['cash']))} ريالاً")
        out.append(" ".join(parts) + ".")

    for dim, label, f in (("gold", "الوزني", fmt), ("cash", "النقدي", money)):
        st = d["limit"][dim]
        if st["over"]:
            out.append(
                f"⚠ تجاوز سقفه {label}: {f(st['used'])} مقابل سقف "
                f"{f(st['limit'])} ({st['pct']:,.0f}%).")
        elif st["pct"] is not None and st["pct"] >= 85:
            out.append(
                f"اقترب من سقفه {label}: {st['pct']:,.0f}% منه مستهلك.")

    a = d["aging"]
    if a and a["days"] >= 90:
        out.append(
            f"أقدم دينٍ عليه منذ {a['days']:,} يوماً "
            f"({a['oldest']}) — فوق التسعين.")
    elif a and a["days"]:
        out.append(f"أقدم دينٍ عليه منذ {a['days']:,} يوماً.")

    lr = d["last_receipt"]
    if lr is None:
        out.append("ولم يُسدَّد منه شيءٌ قط.")
    elif lr["since"] is not None and lr["since"] > 45:
        out.append(f"وآخر تحصيلٍ منه قبل {lr['since']:,} يوماً "
                   f"({lr['date']}).")
    else:
        out.append(f"وآخر تحصيلٍ منه في {lr['date']}.")

    fl = d["flow"]
    if fl["return_pct"] is not None and fl["return_pct"] >= 20:
        out.append(
            f"نسبة مرتجعه في الفترة {fl['return_pct']:,.1f}% من وزن ما "
            "أخذ — مرتفعة، راجع الموديلات أو الاتفاق.")

    w = d["wage"]
    if w["impact"] < -0.005:
        out.append(
            f"وأجرته أقلّ من المتفق عليه بـ {money(abs(w['impact']))} ريال "
            f"في {w['deviations']:,} سطراً.")
    elif w["impact"] > 0.005:
        out.append(
            f"وأجرته أعلى من المتفق عليه بـ {money(w['impact'])} ريال.")

    top = d["models"] or d["models_life"]
    if top:
        out.append("وأكثر ما يأخذ: "
                   + "، ".join(m["model"] for m in top[:3]) + ".")
    return out
