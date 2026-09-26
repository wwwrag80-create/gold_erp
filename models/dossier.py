# -*- coding: utf-8 -*-
"""ملف الجهة — كل ما يخصّ عميلاً في صفحةٍ واحدة.

**السؤال الذي وُجد لأجله**: يتّصل العميل، أو يدخل المكتب، أو يُعرض
اسمه في اجتماع — فيريد صاحب المصنع أن يعرف حالَه **الآن**، لا بعد
أن يفتح سبع شاشات ويجمع بينها بذاكرته:

    كم رصيده؟ · هل تجاوز سقفه؟ · كم من دينه قديم؟
    ماذا جرى معه الشهر الماضي؟ · متى آخر مرةٍ سدّد؟
    أيَّ الموديلات يأخذ؟ · كم يُرجع مما يأخذ؟
    وكم سدّد ممّا كان تحت يده؟

وكل جوابٍ من هذه موجودٌ في النظام، لكنه في شاشةٍ غير شاشة الأخرى.
وسبعُ شاشاتٍ تُفتح في مكالمةٍ هاتفية تعني أن أحداً لن يفتحها.

**ولا يُحسب هنا رقمٌ جديد**: كل قسمٍ يُستدعى من مصدره الأصلي —
الأعمار من `aging`، والجسر من `movement`، والرصيد من الدفتر —
فلا يتعارض الملف مع الكشف ولا يختلف رقمٌ عن رقم. وهذا شرطٌ لا
تحسين: تقريرٌ يجمع أرقاماً من مصادر مختلفة يصير مصدراً سادساً
للخلاف بدل أن يكون جواباً.

**ونسبة المرتجع تُقاس بالوزن لا بالعدد**: عميلٌ يُرجع طقماً صغيراً من
عشرة غير عميلٍ يُرجع نصف ما أخذ وزناً.

**والنسب كلها تُقاس على «ما كان عنده»** — رصيدُ أول المدة + ما خرج
إليه فيها — لا على مبيعات الفترة وحدها: عميلٌ عليه أربعون كيلواً من
قبلُ وأخذ كيلواً هذا الشهر وسدّد كيلواً، لو قيس سدادُه على مبيعات
الشهر لقيل «سدّد ١٠٠٪» وهو لم يمسّ الأربعين.

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
import datetime as _dt

from models import aging, entities, movement
from services.accounting_engine import account_balance

EPS_G = 0.0005
EPS_C = 0.005

# «من البداية» = من أول يومٍ ممكن في الدفتر
LIFE_START = "1900-01-01"


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
    }


def _ratios(flow, bridge):
    """يملأ حركة الجهة **من الجسر** ويحسب النسب على ما كان تحت يدها.

    **ولماذا من الجسر لا من الفواتير**: الفواتير تعرف المبيعات
    والمرتجع وحدهما، والذمّة تزيد وتنقص بغيرهما — رصيدٌ افتتاحي،
    قيدٌ يدوي، سندُ صرفٍ له، تسويةٌ على حسابه. فلو بُني الأساس من
    الفواتير لسقط منه كلُّ ذلك، ولاختلف «ما كان عنده» عمّا يقوله
    كشفُ حسابه. والجسر يقرأ الدفتر كلَّه، فما يُبنى عليه لا يخالفه.

    **ولماذا الأساس «ما كان عنده» لا «مبيعات الفترة»**: عميلٌ عليه
    أربعون كيلواً من قبلُ وأخذ كيلواً هذا الشهر وسدّد كيلواً — لو
    قيست نسبة سداده على مبيعات الشهر وحدها لقيل «سدّد ١٠٠٪» وهو لم
    يمسّ الأربعين.
    """
    by = {b["label"]: b for b in bridge["buckets"]}
    op = float(bridge["opening"]["gold"] or 0.0)
    # كلُّ ما زاد الذمّة في الفترة — بأي اسمٍ زادها
    up = round(sum(b["gold_up"] for b in bridge["buckets"]), 3)
    sales = round(by.get("مبيعات", {}).get("gold_up", 0.0), 3)
    rets = round(by.get("مرتجع", {}).get("gold_dn", 0.0), 3)
    paid = by.get("قبض", {})
    # **التسكير سداد**: ذهبٌ سُوّي بسعره فانطفأ دينه الذهبي — يُضمّ
    # إلى المسدَّد وزناً (وشقّه النقدي زيادةٌ في الذمة كأي مبيعات)
    fix = by.get("تسكير", {})

    flow["opening_weight"] = round(op, 3)
    flow["out_weight"] = sales            # البضاعة: مبيعات
    flow["other_up"] = round(up - sales, 3)
    flow["held_weight"] = round(op + up, 3)
    flow["back_weight"] = rets
    flow["paid_weight"] = round(paid.get("gold_dn", 0.0)
                                + fix.get("gold_dn", 0.0), 3)
    flow["paid_cash"] = round(paid.get("cash_dn", 0.0), 2)
    flow["paid_count"] = int(paid.get("docs", 0)) + int(fix.get("docs", 0))
    flow["closing_weight"] = round(bridge["closing"]["gold"], 3)
    flow["closing_cash"] = round(bridge["closing"]["cash"], 2)
    base = flow["held_weight"]

    def _pct(part):
        return (round(part * 100.0 / base, 1) if base > EPS_G else None)

    # بالوزن لا بالعدد: طقمٌ صغير من عشرة ليس كنصف ما أخذ وزناً
    flow["return_pct"] = _pct(rets)
    flow["paid_pct"] = _pct(flow["paid_weight"])
    flow["settled_pct"] = _pct(rets + flow["paid_weight"])
    return flow


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
    # **«من البداية» جسرٌ مثله لا حسابٌ آخر**: يُقرأ من أول يومٍ في
    # الدفتر، فتقع فيه الأرصدة الافتتاحية داخل المدة فتُضمّ إلى
    # افتتاحيّه — فيكون «ما كان عنده من البداية» شاملاً لها. ولو
    # بُني من الفواتير وحدها لسقط منه الافتتاحيّ فظهرت نسبةُ سدادٍ
    # مضاعفة.
    bridge_life = movement.analyze(conn, e["account_id"], LIFE_START, as_of)

    flow = _ratios(_flow(conn, entity_id, d1, as_of), bridge)
    flow_life = _ratios(_flow(conn, entity_id), bridge_life)

    return {
        "as_of": as_of, "date_from": d1,
        "entity": {"id": e["id"], "name": e["name"],
                   "type": e["entity_type"],
                   "phone": e["phone"] or "", "vat": e["vat_number"] or "",
                   "account_id": e["account_id"]},
        "balance": {"gold": round(gold, 3), "cash": round(cash, 2)},
        "limit": _limit_state(lim_c, lim_g, cash, gold),
        "aging": age,
        "bridge": bridge, "bridge_life": bridge_life,
        "models": _top_models(conn, entity_id, d1, as_of),
        "models_life": _top_models(conn, entity_id),
        "flow": flow, "flow_life": flow_life,
        "last_receipt": _last_voucher(conn, entity_id, "receipt", as_of),
        "last_payment": _last_voucher(conn, entity_id, "payment", as_of),
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
    if fl["held_weight"] > EPS_G:
        out.append(
            f"كان تحت يده في الفترة {fmt(fl['held_weight'])} "
            f"(أول المدة {fmt(fl['opening_weight'])} + بضاعة "
            f"{fmt(fl['out_weight'])})"
            + (f"، سدّد منها {fl['paid_pct']:,.1f}%"
               if fl["paid_pct"] is not None else "")
            + (f" وأرجع {fl['return_pct']:,.1f}%."
               if fl["return_pct"] is not None else "."))
    if fl["return_pct"] is not None and fl["return_pct"] >= 20:
        out.append(
            "ونسبة مرتجعه مرتفعة — راجع الموديلات أو الاتفاق.")
    if fl["paid_pct"] is not None and fl["paid_pct"] < 20 \
            and fl["held_weight"] > EPS_G:
        out.append(
            "وسدادُه دون الخُمس ممّا كان عنده — الدين يتراكم لا ينحسر.")

    top = d["models"] or d["models_life"]
    if top:
        out.append("وأكثر ما يأخذ: "
                   + "، ".join(m["model"] for m in top[:3]) + ".")
    return out
