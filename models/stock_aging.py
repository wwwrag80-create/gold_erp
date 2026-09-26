# -*- coding: utf-8 -*-
"""أعمار الموديلات — ما رقد في المخزن، ومنذ متى.

**السؤال الذي وُجد لأجله**: تقرير المخزون يقول «في المخزن ٨٤٠ طقماً
وزنها ١٢ كيلو». وهذا رقمٌ لا يُتَّخذ عليه قرار. الذي يُتَّخذ عليه
قرارٌ هو: **كم منها راقدٌ منذ أكثر من تسعين يوماً**.

فالطقم الذي دخل المخزن أمس بضاعة، والطقم الذي دخله قبل سنةٍ مالٌ
مدفونٌ في الرفّ: ذهبُه مجمَّدٌ لا يدور، وأجرةُ تصنيعه صُرفت على
العامل ولم تُحصَّل من أحد. والمصنع الذي نصفُ مخزونه فوق التسعين
يشتري ذهباً جديداً وهو لا يحتاجه.

**والقياس هو قياس أعمار الديون نفسه** — الفئات نفسها والتسميات
نفسها (`models.aging.BUCKET_LABELS`)، فلا يقرأ المستخدم «أقل من ٣٠»
في شاشةٍ و«٠–٣٠» في أخرى للمعنى ذاته.

**وتاريخ الدخول يُؤخذ من القيد لا من وقت إنشاء السجل**: السجل قد
يُدخَل اليوم لدفعةٍ ورَدَت الشهر الماضي، فعمرها من تاريخ قيدها لا من
لحظة كتابتها. و`created_at` احتياطٌ لا أصل.

**والرقم التجميعي (00010 · 0010) لا عمر له**: هو رصيد وزنٍ لا قطعة — يزيد
وينقص بلا هوية، فلو عُومل كقطعةٍ عمرها عمر سجلّه لأظهر التقرير عشرات
الكيلوات «راكدة منذ سنتين» وهي تدور كل يوم. فيُفصل في سطرٍ مستقلّ
يُعلَن فيه أنه بلا عمر، ولا يدخل الفئات.

**والعرض قطعةً قطعة لا مجمَّعاً**: السؤال عن **القطعة** — أيُّها رقد
ومنذ متى — والتجميع بالفئة أو بالموديل يخفي القطعةَ التي يُراد
الوصول إليها. والفئاتُ والموديلات تبقى محسوبةً هنا لأن اللوحات
والخلاصة تُبنيان منها.

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
import datetime as _dt

from models.aging import BUCKETS, BUCKET_LABELS

NO_MODEL = "— بلا موديل —"


def _days(a, b):
    try:
        d1 = _dt.date.fromisoformat(str(a)[:10])
        d2 = _dt.date.fromisoformat(str(b)[:10])
        return max(0, (d2 - d1).days)
    except Exception:
        return 0


def _bucket(n):
    for i, (lo, hi) in enumerate(BUCKETS):
        if n >= lo and (hi is None or n <= hi):
            return i
    return len(BUCKETS) - 1


def _today():
    return _dt.date.today().isoformat()


def as_list(model):
    """يقبل المرشِّح نصّاً واحداً أو قائمةً — والفارغ يعني «الكل».

    شاشةُ التقرير تُرشِّح بموديلٍ أو بعدة موديلات، والنموذج لا يعرف
    أيَّهما جاء. فيُوحَّد هنا مرةً واحدة بدل أن يتكرّر الفحص في كل
    موضع يستعمل المرشِّح.
    """
    if not model:
        return []
    if isinstance(model, str):
        return [model.strip()] if model.strip() else []
    return [str(x).strip() for x in model if str(x).strip()]


def items(conn, as_of=None, model=None):
    """كل قطعةٍ في المخزن بعمرها — الأقدم أولاً.

    `as_of` تاريخ القياس؛ ما دخل بعده لا يُحسب، فالتقرير يُعاد بناؤه
    لأي تاريخٍ مضى كما كان يومها لا كما هو اليوم.

    `model` موديلٌ واحد أو عدة موديلات — والفارغ يعني كلَّ المخزن.
    """
    as_of = as_of or _today()
    p = [as_of]
    extra = ""
    chosen = as_list(model)
    if chosen:
        ph = ",".join("?" * len(chosen))
        extra = (f" AND COALESCE(NULLIF(TRIM(w.model_no),''),?)"
                 f" IN ({ph})")
        p += [NO_MODEL] + chosen
    rows = conn.execute(
        "SELECT w.id, w.work_order_no wo, w.model_no,"
        "  w.registered_weight wt, w.wage_per_gram wpg, w.is_bulk,"
        "  w.item_type, w.small_stones, w.big_stones,"
        "  COALESCE(e.entry_date, substr(w.created_at,1,10)) in_date"
        " FROM work_orders w"
        " LEFT JOIN journal_entries e ON e.id=w.entry_id"
        " WHERE w.is_deleted=0 AND w.status='in_stock'"
        "   AND COALESCE(e.entry_date, substr(w.created_at,1,10)) <= ?"
        + extra, p).fetchall()

    out = []
    for r in rows:
        wt = float(r["wt"] or 0.0)
        wpg = float(r["wpg"] or 0.0)
        n = _days(r["in_date"], as_of)
        out.append({
            "id": r["id"], "wo_no": r["wo"],
            "model": (r["model_no"] or "").strip() or NO_MODEL,
            "weight": round(wt, 3), "wage_per_gram": round(wpg, 2),
            "idle_wage": round(wt * wpg, 2),
            "in_date": str(r["in_date"] or "")[:10],
            "days": n, "bucket": _bucket(n),
            "is_bulk": bool(r["is_bulk"]),
            "item_type": (r["item_type"] or "").strip(),
            "small_stones": round(float(r["small_stones"] or 0.0), 2),
            "big_stones": round(float(r["big_stones"] or 0.0), 2),
        })
    out.sort(key=lambda x: (-x["days"], -x["weight"]))
    return out


def _blank():
    return {"count": 0, "weight": 0.0, "idle_wage": 0.0}


def _add(acc, it):
    acc["count"] += 1
    acc["weight"] = round(acc["weight"] + it["weight"], 3)
    acc["idle_wage"] = round(acc["idle_wage"] + it["idle_wage"], 2)


def report(conn, as_of=None, model=None):
    """أعمار الموديلات: القطع الأقدم فالأقدم، ومعها الفئات
    والموديلات لأن اللوحات والخلاصة تُبنى منها."""
    as_of = as_of or _today()
    rows = items(conn, as_of, model)
    aged = [x for x in rows if not x["is_bulk"]]
    # الأرقام التجميعية بترتيبها المعلن (00010 ثم 0010) لا بعمر سجلّها
    bulk = sorted((x for x in rows if x["is_bulk"]),
                  key=lambda x: (len(x["wo_no"] or "") * -1, x["wo_no"]))

    buckets = [dict(_blank(), label=BUCKET_LABELS[i], index=i)
               for i in range(len(BUCKETS))]
    per_model = {}
    total = _blank()
    for it in aged:
        _add(buckets[it["bucket"]], it)
        _add(total, it)
        m = per_model.setdefault(it["model"], {
            "model": it["model"], "count": 0, "weight": 0.0,
            "idle_wage": 0.0, "oldest": 0,
            "buckets": [_blank() for _ in BUCKETS]})
        _add(m, it)
        _add(m["buckets"][it["bucket"]], it)
        m["oldest"] = max(m["oldest"], it["days"])

    base_w = total["weight"] or 1.0
    for b in buckets:
        b["weight_pct"] = round(b["weight"] * 100.0 / base_w, 1)
    models = sorted(per_model.values(), key=lambda m: -m["weight"])
    for m in models:
        # **الترتيب بالوزن والتنبيه بالقِدَم**: أخطر الموديلات ما
        # كَبُر وزنُه وطال مكثه معاً، فتُحسب نسبةُ ما تجاوز التسعين
        # من كل موديل ليُفرز بها.
        m["old_weight"] = m["buckets"][-1]["weight"]
        m["old_pct"] = round(m["old_weight"] * 100.0 / (m["weight"] or 1.0), 1)

    bulk_sum = _blank()
    for it in bulk:
        _add(bulk_sum, it)

    # **ثلاثة مجاميع لا واحد**: `total` مجموع ما له عمر (وهو ما تجمعه
    # الفئات)، و`bulk` ما لا عمر له، و`grand` المخزون كلّه. لو عُرض
    # مجموعٌ واحد تحت سطر التجميعي لبدا أنه يشمله وهو لا يشمله —
    # فيُطرح الفرقُ سؤالاً على كل من قرأ الورقة.
    grand = {
        "count": total["count"] + bulk_sum["count"],
        "weight": round(total["weight"] + bulk_sum["weight"], 3),
        "idle_wage": round(total["idle_wage"] + bulk_sum["idle_wage"], 2),
    }

    return {
        "as_of": as_of, "model": model, "filter_models": as_list(model),
        "items": aged, "buckets": buckets, "models": models,
        "total": total, "bulk": bulk_sum, "bulk_rows": bulk,
        "grand": grand,
        "oldest": aged[0] if aged else None,
        "old_weight": buckets[-1]["weight"],
        "old_pct": buckets[-1]["weight_pct"],
        "avg_days": (round(sum(x["days"] * x["weight"] for x in aged)
                           / base_w, 1) if aged else 0.0),
    }


def verdict(r, fmt=None, money=None):
    """جملةٌ تُقرأ — والمنسِّق من الواجهة لأن الأوزان مكافئُ عيار 18."""
    fmt = fmt or (lambda v: f"{v:,.3f}")
    money = money or (lambda v: f"{v:,.2f}")
    out = []
    if not r["items"] and not r["bulk"]["count"]:
        return ["لا مخزون في هذا التاريخ."]
    if not r["items"]:
        out.append("لا قطعَ مفردةً في المخزن — الرصيد كلّه تجميعي.")
        return out
    out.append(
        f"{r['total']['count']:,} قطعةً وزنها {fmt(r['total']['weight'])} "
        f"— متوسط مكثها {r['avg_days']:,.1f} يوماً.")
    out.append(
        f"فوق التسعين يوماً: {fmt(r['old_weight'])} "
        f"({r['old_pct']:,.1f}% من وزن المخزون).")
    if r["old_pct"] >= 50:
        out.append(
            "أكثر من نصف المخزون راكدٌ فوق التسعين — هذا ذهبٌ لا يدور. "
            "راجع التسعير أو أعد الصهر قبل شراء ذهبٍ جديد.")
    elif r["old_pct"] >= 30:
        out.append("ثلث المخزون تقريباً فوق التسعين — راقب الموديلات "
                   "الراكدة قبل أن تُنتج منها مرة أخرى.")
    o = r["oldest"]
    if o:
        out.append(
            f"أقدم قطعة: {o['wo_no']}"
            + (f" (موديل {o['model']})" if o["model"] != NO_MODEL else "")
            + f" منذ {o['days']:,} يوماً — دخلت في {o['in_date']}.")
    slow = [m for m in r["models"] if m["old_pct"] >= 60
            and m["old_weight"] > 0.0005][:3]
    if slow:
        out.append(
            "موديلات أغلبُها راكد: "
            + "، ".join(f"{m['model']} ({m['old_pct']:,.0f}%)"
                        for m in slow) + ".")
    if r["bulk"]["count"]:
        out.append(
            f"وخارج الفئات رصيدٌ تجميعي وزنه {fmt(r['bulk']['weight'])} "
            "— رصيد وزنٍ لا قطعة، فلا عمر له.")
    return out
