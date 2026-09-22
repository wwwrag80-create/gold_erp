# -*- coding: utf-8 -*-
"""تحليل حركة الرصيد — من أين جاء الرصيد وإلى أين ذهب.

**السؤال الذي وُجد لأجله**، بنصّ صاحب المصنع: «كانت مديونية العميل
٤٠ كيلو. أجيء بعد شهرٍ فأريد أن أعرف كم صارت، وماذا حصل خلال
الفترة: كم خرج وكم رجع وكم سُدّد — وفي كم يومٍ من الشهر».

وكشف الحساب لا يجيب هذا. هو **سردٌ زمني**: مئة سطرٍ مرتّبةٍ بالتاريخ،
يُقرأ منها كل شيء ولا يُفهم منها شيء. فمن أراد أن يعرف «كم سُدّد هذا
الشهر» جمع بيده، ومن أراد «هل العميل ينتظم في السداد» خمّن.

**والجواب صيغةٌ محاسبيةٌ معروفة — جسر الرصيد (roll-forward)**:

    رصيد أول المدة
      + ما زاد الدين (مبيعات · تسويات مدينة)
      − ما أنقصه (مرتجعات · تحصيل · خصومات)
      = رصيد آخر المدة

**ولماذا يُبنى بالإشارة لا بالتصنيف**: لو صُنّفت الحركات بأسمائها
(«مبيعات» موجب، «قبض» سالب) لسقط من الجسر كلُّ ما لا اسم له —
تسويةٌ يدوية، قيدُ افتتاح، نوعٌ يُضاف مستقبلاً — فلا يساوي المجموعُ
الرصيدَ الختامي، ويفقد الكشف قيمته كلها. فالأثر يُؤخذ من **مدين
ناقص دائن** دائماً، والاسم للعرض فقط. فالجسر يقفل **بالتعريف** مهما
دخل النظام من أنواع، وما لا يُعرف اسمه يظهر في «أخرى» لا يضيع.

**والأرصدة الافتتاحية ليست حركة**: الرصيد الافتتاحي والقيدُ اليومي
الذي يُدخل به المصنع أرصدةَ جهاته يقولان «هذا ما كان عنده» لا «هذا
ما جرى» — فيُضمّان إلى **رصيد أول المدة**، ويُعلَن مقدارُ ما ضُمّ
منهما في تلميح السطر فلا يُخفى شيء.

**وتحليل الأيام** هو ما سأل عنه حرفياً: في كم يومٍ من الشهر كان بيع،
وفي كم مرتجع، وفي كم تحصيل. ومنه تُشتقّ مؤشراتٌ تقول ما لا تقوله
الأرقام المجرّدة:

* **نسبة التحصيل** = المحصَّل ÷ المُباع. دون المئة يعني أن الدين
  ينمو مهما بدا التحصيل كبيراً.
* **نسبة المرتجع** = المرتجع ÷ المُباع. ارتفاعها يعني خللاً في
  البضاعة أو في الاتفاق، لا في الحساب.
* **أطول فجوةٍ بلا تحصيل** — أصدق إنذارٍ مبكّر: عميلٌ يشتري كل
  أسبوع ولم يسدّد منذ أربعين يوماً حالتُه غير عميلٍ هادئ الحركة.

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from datetime import date, timedelta

from models import journal

# ترتيب العرض في الجسر — الأكثر أثراً أولاً، و«أخرى» في الذيل.
# الاسم للعرض وحده؛ الأثر يُؤخذ من مدين ناقص دائن دائماً.
ORDER = ["مبيعات", "مرتجع", "قبض", "صرف", "تسكير", "توريد",
         "مشتريات", "صب", "تسوية"]
OTHER = "أخرى"

# **ما ليس حركةً بل رصيدُ بداية**: قيدُ الرصيد الافتتاحي، والقيدُ
# اليومي الذي يُدخِل به المصنع أرصدةَ جهاته. كلاهما يقول «هذا ما كان
# عنده»، لا «هذا ما جرى في الفترة» — فمكانهما سطرُ **أول المدة**.
#
# وكانا يقعان في «أخرى»: الافتتاحي لأن اسمه ليس في القائمة أعلاه،
# والقيدُ اليومي لأن اسمه في الدفتر «قيد يومي» والقائمة كانت تحمل
# «قيد يومية» — حرفٌ واحد جعل كلَّ قيدٍ يدوي يسقط في «أخرى» ولا
# يلتقي ببنده أبداً. فيقرأ المستخدم رصيدَ افتتاحٍ على أنه حركةٌ
# مجهولة جرت في الفترة، وهو أشدّ ما يُربك في الجسر.
#
# والجسر يبقى مقفلاً على أي حال: ما يُضاف إلى الافتتاحي يُطرح من
# الحركة بالقدر نفسه، فالمجموع لا يتغيّر.
OPENING_OPS = ("رصيد افتتاحي", "قيد يومي", "قيد يومية",
               "قيد يومية يدوي")


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def account_ids(conn, account_id):
    """الحساب وحده إن كان قابلاً للترحيل، وشجرتُه كلها إن كان تجميعياً.

    الحساب التجميعي («إجمالي العملاء») لا يُرحَّل عليه شيء، فقراءتُه
    وحده تعطي كشفاً خاوياً. والمقصود منه مجموعُ فروعه.
    """
    try:
        r = conn.execute("SELECT is_postable FROM accounts WHERE id=?",
                         (account_id,)).fetchone()
        if r is not None and not r["is_postable"]:
            from models.accounts import subtree_ids
            ids = subtree_ids(conn, account_id)
            return ids or [account_id]
    except Exception:
        pass
    return [account_id]


def analyze(conn, account_id, date_from, date_to):
    """جسر الرصيد وتحليل الأيام لحسابٍ (أو شجرةِ حسابٍ) بين تاريخين."""
    rows = journal.statement(conn, account_ids(conn, account_id),
                             date_from, date_to)

    # سطر «رصيد سابق» هو الافتتاحي — يُفصل عن الحركة. ويُضمّ إليه
    # قيدُ الرصيد الافتتاحي الواقع **داخل** الفترة: هو رصيدُ بدايةٍ
    # لا حركةٌ جرت. والجسر يبقى مقفلاً لأن ما يُضاف إلى الافتتاحي
    # يُطرح من الحركة بالقدر نفسه.
    opening_g = opening_c = 0.0
    # ما دخل الافتتاحيَّ من **داخل** الفترة — يُعلَن في تلميح السطر
    # فلا يُخفى شيء وإن لم يُفرد سطراً
    in_period_g = in_period_c = 0.0
    in_period_n = 0
    moves = []
    for r in rows:
        if r["op"] == "رصيد سابق":
            opening_g, opening_c = r["gbal"], r["cbal"]
            continue
        if r["op"] in OPENING_OPS:
            g = float(r["gd"] or 0) - float(r["gc"] or 0)
            c = float(r["cd"] or 0) - float(r["cc"] or 0)
            opening_g = round(opening_g + g, 3)
            opening_c = round(opening_c + c, 2)
            in_period_g = round(in_period_g + g, 3)
            in_period_c = round(in_period_c + c, 2)
            in_period_n += 1
            continue
        moves.append(r)

    buckets = {}
    daily = {}
    for r in moves:
        key = r["op"] if r["op"] in ORDER else OTHER
        b = buckets.setdefault(key, {
            "label": key, "gold": 0.0, "cash": 0.0,
            "gold_up": 0.0, "gold_dn": 0.0,
            "cash_up": 0.0, "cash_dn": 0.0,
            "docs": 0, "days": set()})
        gd, gc = float(r["gd"] or 0), float(r["gc"] or 0)
        cd, cc = float(r["cd"] or 0), float(r["cc"] or 0)
        # الأثر الصافي على الرصيد: مدين − دائن. بهذا يقفل الجسر
        # بالتعريف مهما كان اسم العملية.
        b["gold"] += gd - gc
        b["cash"] += cd - cc
        b["gold_up"] += gd
        b["gold_dn"] += gc
        b["cash_up"] += cd
        b["cash_dn"] += cc
        b["docs"] += 1
        b["days"].add(str(r["date"])[:10])

        d = daily.setdefault(str(r["date"])[:10], {
            "date": str(r["date"])[:10], "gold": 0.0, "cash": 0.0,
            "docs": 0, "ops": set()})
        d["gold"] += gd - gc
        d["cash"] += cd - cc
        d["docs"] += 1
        d["ops"].add(key)

    # **الأيام تُقرأ نسبةً إلى الفترة لا عدداً مجرّداً**: «٣ كيلو في
    # ٣٠ يوماً» بيعٌ منتظم، و«٣ كيلو في يومٍ واحد من ٣٠» صفقةٌ واحدة
    # — والرقم نفسه في الحالتين. فكل بندٍ يحمل مدى الفترة معه ليُعرض
    # «س من ص يوماً» أينما عُرض، في هذه الشاشة وفي غيرها.
    span = _span(date_from, date_to, daily)
    out_b = []
    for key in ORDER + [OTHER]:
        b = buckets.get(key)
        if not b:
            continue
        n = len(b["days"])
        out_b.append({
            "label": b["label"],
            "gold": round(b["gold"], 3), "cash": round(b["cash"], 2),
            "gold_up": round(b["gold_up"], 3),
            "gold_dn": round(b["gold_dn"], 3),
            "cash_up": round(b["cash_up"], 2),
            "cash_dn": round(b["cash_dn"], 2),
            "docs": b["docs"], "days": n, "span": span,
            "days_pct": round(n * 100.0 / span, 1) if span else 0.0,
            "days_label": days_label(n, span),
            "day_list": sorted(b["days"]),
        })

    move_g = round(sum(b["gold"] for b in out_b), 3)
    move_c = round(sum(b["cash"] for b in out_b), 2)
    closing_g = round(opening_g + move_g, 3)
    closing_c = round(opening_c + move_c, 2)

    # ── الجدول اليومي بالرصيد التراكمي ──
    gb, cb = opening_g, opening_c
    days_rows = []
    for k in sorted(daily):
        d = daily[k]
        gb = round(gb + d["gold"], 3)
        cb = round(cb + d["cash"], 2)
        days_rows.append({**d, "ops": sorted(d["ops"]),
                          "gold": round(d["gold"], 3),
                          "cash": round(d["cash"], 2),
                          "gbal": gb, "cbal": cb})

    return {
        "date_from": str(date_from), "date_to": str(date_to),
        "opening": {"gold": round(opening_g, 3), "cash": round(opening_c, 2)},
        # تفصيلُ الافتتاحي: ما حُمل من قبل الفترة، وما أُضيف من
        # قيودٍ افتتاحيةٍ أو يوميةٍ وقعت داخلها
        "opening_in_period": {"gold": in_period_g, "cash": in_period_c,
                              "docs": in_period_n},
        "closing": {"gold": closing_g, "cash": closing_c},
        "change": {"gold": move_g, "cash": move_c},
        "buckets": out_b,
        "daily": days_rows,
        "days": _day_stats(date_from, date_to, out_b, days_rows),
        "signals": _signals(out_b, days_rows, date_to,
                            opening_g, closing_g, opening_c, closing_c),
    }


def _span(date_from, date_to, daily):
    """عدد أيام الفترة — وطولُ الحركة إن لم يُحدَّد طرفاها."""
    a, b = _d(date_from), _d(date_to)
    return ((b - a).days + 1) if (a and b and b >= a) else len(daily)


def days_label(n, span):
    """«س من ص يوماً» — الصيغة المعتمدة لعرض الأيام في كل شاشة.

    مصدرٌ واحد للصيغة: من قرأ «٢ من ٣٠» في الجسر يقرؤها نفسها في
    نشاط الأيام وفي ملف الجهة، فلا يتعلّم قراءتين للمعنى الواحد.
    """
    if not span:
        return f"{n:,}"
    return f"{n:,} من {span:,}"


def _day_stats(date_from, date_to, buckets, daily):
    """كم يوماً في الفترة، وكم منها فيه حركة، وكم صامت."""
    span = _span(date_from, date_to, daily)
    active = len(daily)
    return {
        "span": span,
        "active": active,
        "active_label": days_label(active, span),
        "silent": max(0, span - active),
        "active_pct": round(active * 100.0 / span, 1) if span else 0.0,
        "by_op": [{"label": x["label"], "days": x["days"],
                   "span": x["span"], "days_label": x["days_label"],
                   "days_pct": x["days_pct"],
                   "docs": x["docs"], "gold": x["gold"], "cash": x["cash"]}
                  for x in buckets],
    }


def _gap_days(dates, end):
    """أطول فجوةٍ بين تواريخ متتابعة، وآخر فجوةٍ حتى نهاية الفترة.

    الفجوة الأخيرة تُحسب حتى `end` لا حتى آخر تاريخ: عميلٌ سدّد أول
    الشهر ثم انقطع لا تظهر خطورته إن قيس ما بين سداداته فقط.
    """
    ds = sorted({_d(x) for x in dates if _d(x)})
    e = _d(end)
    if not ds:
        return {"longest": None, "since": None, "last": None}
    longest = 0
    for i in range(1, len(ds)):
        longest = max(longest, (ds[i] - ds[i - 1]).days)
    since = (e - ds[-1]).days if e else None
    if since is not None:
        longest = max(longest, since)
    return {"longest": longest, "since": since,
            "last": ds[-1].isoformat()}


def _signals(buckets, daily, date_to, og, cg, oc, cc):
    """مؤشراتٌ تقول ما لا تقوله الأرقام المجرّدة."""
    by = {b["label"]: b for b in buckets}
    sold_g = by.get("مبيعات", {}).get("gold_up", 0.0)
    sold_c = by.get("مبيعات", {}).get("cash_up", 0.0)
    ret_g = by.get("مرتجع", {}).get("gold_dn", 0.0)
    ret_c = by.get("مرتجع", {}).get("cash_dn", 0.0)
    coll_g = by.get("قبض", {}).get("gold_dn", 0.0)
    coll_c = by.get("قبض", {}).get("cash_dn", 0.0)

    def pct(part, whole):
        return round(part * 100.0 / whole, 1) if whole > 0.0005 else None

    gap = _gap_days(by.get("قبض", {}).get("day_list", []), date_to)
    return {
        "collect_pct_gold": pct(coll_g, sold_g),
        "collect_pct_cash": pct(coll_c, sold_c),
        "return_pct_gold": pct(ret_g, sold_g),
        "return_pct_cash": pct(ret_c, sold_c),
        "gold_dir": round(cg - og, 3),
        "cash_dir": round(cc - oc, 2),
        "collect_gap": gap,
        "busiest": (max(daily, key=lambda d: d["docs"])["date"]
                    if daily else None),
    }


def verdict(res, dim="gold", fmt=None, unit=None):
    """جملةٌ واحدة تلخّص الفترة — تُقرأ قبل الأرقام.

    التقرير الذي يترك القارئ يستنتج لا يُقرأ. وهذه تقول الخلاصة
    صراحةً: الدين زاد أم نقص، وهل التحصيل يكفي.

    **ولماذا يُمرَّر المنسِّق من فوق**: الأوزان هنا مكافئُ عيار 18 —
    وهو ما يُخزَّن — والمستخدم يقرأ بعيار مصنعه. فلولا أن تُنسّقها
    الواجهةُ لقال المصنعُ الذي يعمل بـ21 رقماً في الجملة وآخر في
    الجدول للحركة نفسها.
    """
    fmt = fmt or (lambda v: f"{v:,.3f}")
    s = res["signals"]
    by = {b["label"]: b for b in res["buckets"]}
    d = s["gold_dir"] if dim == "gold" else s["cash_dir"]
    unit = unit or ("جم" if dim == "gold" else "ريال")
    up, dn = ("gold_up", "gold_dn") if dim == "gold" else ("cash_up",
                                                           "cash_dn")
    sold = by.get("مبيعات", {}).get(up, 0.0)
    coll = by.get("قبض", {}).get(dn, 0.0)
    rets = by.get("مرتجع", {}).get(dn, 0.0)

    if abs(d) < 0.005:
        head = "الرصيد لم يتغيّر خلال الفترة."
    elif d > 0:
        head = f"الدين **زاد** {fmt(abs(d))} {unit} خلال الفترة."
    else:
        head = f"الدين **نقص** {fmt(abs(d))} {unit} خلال الفترة."

    # **التمييز الذي يمنع الالتباس**: الدين قد ينقص بالمرتجع وحده
    # والتحصيل دون المبيعات. فيُفصل ما سُدّد نقداً/وزناً عمّا رجع
    # بضاعةً — وإلا قرأ المدير «الدين نقص» فاطمأنّ، والحقيقة أن
    # العميل لم يدفع بل أعاد ما أخذ.
    tail = ""
    if sold > 0.0005:
        cp = round(coll * 100.0 / sold, 1)
        rp = round(rets * 100.0 / sold, 1)
        tail = f" التحصيل وحده غطّى {cp:,.1f}% من المبيعات"
        tail += (f"، والمرتجعات {rp:,.1f}%." if rets > 0.0005 else ".")
        if cp < 100 and rp > cp:
            tail += (" أي أن انخفاض الدين جاء من **ردّ البضاعة** أكثر "
                     "مما جاء من السداد.")
    elif coll > 0.0005:
        tail = f" لا مبيعات في الفترة — تحصيلٌ فقط {fmt(coll)} {unit}."

    gap = s["collect_gap"]
    if not gap.get("last"):
        tail += " ولم يقع أي تحصيلٍ في الفترة."
    elif gap.get("since") is not None and gap["since"] > 30:
        tail += f" ولم يُسدَّد شيءٌ منذ {gap['since']} يوماً."
    return head + tail
