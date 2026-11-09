# -*- coding: utf-8 -*-
"""أين الطقم الآن؟ والأطقم القريبة من وزنٍ معيّن (5.2.4).

* `where_now`: في الخزنة، أو عند جهةٍ باسمها (آخر بيعٍ أخرجه ولم يعد)،
  أو بعضُه هنا وبعضُه هناك (بيعُ جزءٍ من طقمٍ مفرد).
* `near_weight`: من يتذكّر وزن الطقم لا رقمه — يكتب الوزن المقيد أو
  القائم فتظهر أرقام التشغيل الأقرب إليه، الأقرب أولاً.

الأوزان هنا مخزّنة بمكافئ 18 كما في القاعدة؛ والتحويل لعيار العرض في
الواجهة.
"""
from models import wo_moves

EPS = 0.0005
FIELDS = {"reg": "registered_weight", "standing": "standing_gold"}


def where_now(conn, wo):
    """{"place": "treasury"|"party"|"split", "label", "party", "invoice_no",
    "date", "rem", "out"} — مكان الطقم المفرد الآن."""
    try:
        bulk = bool(wo["is_bulk"])
    except (KeyError, IndexError):
        bulk = False
    if bulk:
        return {"place": "treasury", "label": "رقم تجميعي (رصيد وزني)",
                "party": "", "invoice_no": "", "date": "", "rem": None,
                "out": None}
    st = wo_moves.state(conn, wo)
    rem, out = st["rem"], st["out"]
    if out <= EPS:
        return {"place": "treasury", "label": "في الخزنة", "party": "",
                "invoice_no": "", "date": "", "rem": rem, "out": 0.0}
    lo = wo_moves.last_out(conn, wo) or {}
    party = lo.get("party") or "—"
    if rem > EPS:
        return {"place": "split",
                "label": f"بعضه في الخزنة وبعضه عند {party}",
                "party": party, "invoice_no": lo.get("invoice_no", ""),
                "date": lo.get("date", ""), "rem": rem, "out": out}
    return {"place": "party", "label": f"عند {party}", "party": party,
            "invoice_no": lo.get("invoice_no", ""),
            "date": lo.get("date", ""), "rem": 0.0, "out": out}


def details(conn, wo):
    """تفاصيل الطقم للعرض: الأوزان والموديل ومكانه الآن."""
    w = where_now(conn, wo)
    keys = wo.keys() if hasattr(wo, "keys") else []
    return {
        "work_order_no": wo["work_order_no"],
        "model_no": (wo["model_no"] if "model_no" in keys else "") or "",
        "item_type": (wo["item_type"] if "item_type" in keys else "") or "",
        "reg": float(wo["registered_weight"] or 0),
        "standing": float(wo["standing_gold"] or 0),
        "gold": float(wo["gold_weight"] or 0),
        "small": float(wo["small_stones"] or 0),     # الفصوص
        "big": float(wo["big_stones"] or 0),         # الأحجار
        "where": w,
    }


def near_weight(conn, weight, field="reg", limit=30, tol=None):
    """أرقام التشغيل المفردة الأقرب إلى `weight` (بمكافئ 18) في الوزن
    المقيد (`reg`) أو القائم (`standing`) — الأقرب أولاً.

    `tol`: أقصى فرقٍ يُقبل (None = بلا حدّ، فيُكتفى بـ`limit`)."""
    col = FIELDS.get(field)
    if not col:
        raise ValueError("نوع الوزن غير معروف")
    try:
        target = float(weight)
    except (TypeError, ValueError):
        raise ValueError("اكتب الوزن رقماً")
    if target <= 0:
        raise ValueError("اكتب وزناً أكبر من صفر")
    sql = (f"SELECT *, ABS({col}-?) diff FROM work_orders"
           " WHERE is_deleted=0 AND COALESCE(is_bulk,0)=0"
           " AND COALESCE(is_service,0)=0")
    args = [target]
    if tol is not None:
        sql += f" AND ABS({col}-?)<=?"
        args += [target, float(tol)]
    sql += " ORDER BY diff, work_order_no LIMIT ?"
    args.append(int(limit))
    try:
        rows = conn.execute(sql, args).fetchall()
    except Exception:
        # قاعدةٌ قديمة بلا عمود الطقم الخدمي
        rows = conn.execute(sql.replace(" AND COALESCE(is_service,0)=0", ""),
                            args).fetchall()
    out = []
    for r in rows:
        d = details(conn, r)
        d["diff"] = round(float(r["diff"] or 0), 3)
        out.append(d)
    return out
