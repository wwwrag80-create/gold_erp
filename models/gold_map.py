# -*- coding: utf-8 -*-
"""خريطة الذهب — أين كل جرامٍ الآن، ومن يحوزه.

**السؤال الذي وُجدت لأجله**: صاحب المصنع يعرف كم ذهباً اشترى وكم
باع، ولا يعرف — في لحظةٍ واحدة — **أين ذهبه الآن**. فالذهب في مصنعٍ
حيّ ليس في مكانٍ واحد: بعضه سبائك في خزينة التصنيع، وبعضه أطقمٌ
تامّة في المعرض، وبعضه كسرٌ ينتظر الصهر، وبعضه تحت التصفية، وبعضه
**ليس في المصنع أصلاً**: عند عميلٍ أخذه ولم يسدّد، أو عند ورشةٍ
تشتغل فيه، أو عند شريكٍ سحبه.

وكل تلك أرقامٌ موجودةٌ في الدفتر، لكنها موزّعةٌ على عشرة كشوف. من
أراد أن يجمعها فتح عشر شاشاتٍ وجمع بالآلة الحاسبة — وكل جمعٍ باليد
خطأٌ ينتظر.

**الدلاء الثمانية** اختارها صاحب المصنع بنفسه، وهي مقسومةٌ قسمين:

    في يد المصنع          عند الغير
    ──────────────        ──────────────
    خزينة التصنيع 1100    ما عند العملاء    1600
    الذهب المشغول 1200    عند الجهات الأخرى 1650
    صندوق الكسر   1310    ما عند الشركاء    3100
    تحت التصفية   1350    ما عند الورشة     1970

**وكلُّ دلوٍ شجرة لا حساب**: «ما عند العملاء» ليس رقماً في حسابٍ
واحد، بل مجموع مئات الحسابات الفرعية تحت 1600. فالجمع تكراريٌّ على
الشجرة كلها — يدخل فيه العميل الذي أُنشئ اليوم بلا أن يُذكر في كود.

**ولماذا تقفل الخريطة بالضرورة**: القيد المزدوج في بُعد الذهب يوجب
أن يكون مجموع المدين مساوياً لمجموع الدائن — فمجموع أرصدة الذهب في
**كل** حسابات الدليل صفرٌ دائماً. ومن هذه الحقيقة تُبنى الخريطة:

    (الدلاء الثمانية) + (حسابات ذهبٍ خارجها) = −(بقية الحسابات)
     ───────────────────────────────────      ────────────────
              أين الذهب                            لمن هو

فلو نسي أحدٌ دلواً، أو أضاف حساب ذهبٍ جديداً لا يعرفه هذا الملف، لم
يضع رصيده: يظهر في **«خارج الخريطة»** منبّهاً عليه باسمه. الخريطة لا
تكذب ولا تُكمل بالتقريب؛ إمّا أن تقفل على الصفر أو تقول أين الخلل.

**والمقارنة بتاريخٍ سابق** هي الفائدة الثانية: الرقم المجرّد لا يقول
شيئاً، والفرق يقول كل شيء. «كان عند العملاء ٤٠ كيلو وصار ٥٢» جملةٌ
تُتَّخذ عليها قرارات، و«عند العملاء ٥٢» جملةٌ لا تُقرأ.

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""

EPS = 0.0005

# الدلاء كما سمّاها صاحب المصنع، بترتيب عرضها.
# side: "hand" ذهبٌ في يد المصنع · "out" ذهبٌ عند غيره.
BUCKETS = [
    ("1100", "خزينة التصنيع", "hand", "سبائك وأوزان تحت التشغيل"),
    ("1200", "الذهب المشغول", "hand", "أطقم تامّة جاهزة للبيع"),
    ("1310", "صندوق الكسر", "hand", "كسرٌ ينتظر الصهر"),
    ("1350", "تحت التصفية", "hand", "ذهبٌ عند المصفّاة"),
    ("1600", "ما عند العملاء", "out", "أوزانٌ خرجت ولم تُسدَّد"),
    ("1650", "ما عند الجهات الأخرى", "out", "مدينون آخرون"),
    ("3100", "ما عند الشركاء", "out", "مسحوبات الشركاء ورأس المال"),
    ("1970", "ما عند الورشة", "out", "عهدة عمال التصنيع"),
]

ASSET_ROOT = "1000"

# تصنيف الطرف المقابل — «لمن هذا الذهب»
SOURCE_GROUPS = {
    "2000": "التزامات على المصنع (موردون وغيرهم)",
    "3000": "حقوق الملكية والأرصدة الافتتاحية",
    "4000": "أثر النشاط (إيراد وتكلفة)",
    "5000": "أثر النشاط (إيراد وتكلفة)",
}
SOURCE_OTHER = "حسابات أخرى"


def _tree(conn):
    """كل الحسابات مفهرسةً بالمعرّف، وكلٌّ يعرف أبناءه."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, code, name, type, parent_id, is_postable"
        " FROM accounts ORDER BY code")]
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["kids"] = []
    for r in rows:
        p = by_id.get(r["parent_id"])
        if p is not None and p is not r:
            p["kids"].append(r)
    return rows, by_id


def _own_gold(conn, as_of=None):
    """رصيد ذهب كل حساب **وحده** (مدين ناقص دائن) حتى تاريخ.

    الرصيد الخاص لا المجمّع: الجمع على الشجرة يقع لاحقاً، ولو أُخذ
    المجمّع من الاستعلام لحُسب الأب مع ابنه مرّتين.
    """
    p = []
    clause = ""
    if as_of:
        clause = " AND e.entry_date<=?"
        p.append(as_of)
    out = {}
    for r in conn.execute(
            "SELECT l.account_id aid,"
            " ROUND(COALESCE(SUM(l.gold_debit-l.gold_credit),0),3) g"
            " FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0" + clause +
            " GROUP BY l.account_id", p):
        g = float(r["g"] or 0.0)
        if abs(g) > EPS:
            out[r["aid"]] = g
    return out


def _walk(node, own, claimed, leaves):
    """يجمع الشجرة تكراريّاً ويسجّل كل حسابٍ ذي رصيد في `leaves`."""
    claimed.add(node["id"])
    g = own.get(node["id"], 0.0)
    if abs(g) > EPS:
        leaves.append({"code": node["code"], "name": node["name"],
                       "gold": round(g, 3)})
    total = g
    for k in node["kids"]:
        total += _walk(k, own, claimed, leaves)
    return total


def _ancestors_of(by_id, node):
    """أكواد آباء الحساب حتى الجذر — لمعرفة أهو تحت الأصول."""
    out = []
    cur, guard = node, 0
    while cur is not None and guard < 30:
        out.append(cur["code"])
        cur = by_id.get(cur["parent_id"])
        guard += 1
    return out


def _snapshot(conn, as_of=None):
    """الخريطة في لحظة: الدلاء، وما خارجها، والطرف المقابل."""
    rows, by_id = _tree(conn)
    by_code = {r["code"]: r for r in rows}
    own = _own_gold(conn, as_of)

    claimed = set()
    buckets = []
    for code, label, side, hint in BUCKETS:
        node = by_code.get(code)
        if node is None:
            buckets.append({"code": code, "label": label, "side": side,
                            "hint": hint, "name": label, "gold": 0.0,
                            "leaves": [], "missing": True})
            continue
        leaves = []
        g = _walk(node, own, claimed, leaves)
        leaves.sort(key=lambda x: -abs(x["gold"]))
        buckets.append({"code": code, "label": label, "side": side,
                        "hint": hint, "name": node["name"],
                        "gold": round(g, 3), "leaves": leaves,
                        "missing": False})

    # ما بقي من حساباتٍ ذات رصيد ذهب: إمّا أصلٌ نسيته الخريطة
    # (تنبيه)، أو الطرف المقابل الذي منه جاء الذهب (مورّد · افتتاحي).
    outside, other = [], []
    for aid, g in own.items():
        if aid in claimed:
            continue
        node = by_id.get(aid)
        if node is None:
            continue
        chain = _ancestors_of(by_id, node)
        rec = {"code": node["code"], "name": node["name"],
               "gold": round(g, 3), "type": node.get("type") or ""}
        if ASSET_ROOT in chain:
            outside.append(rec)
        else:
            rec["group"] = next((SOURCE_GROUPS[c] for c in chain
                                 if c in SOURCE_GROUPS), SOURCE_OTHER)
            other.append(rec)
    outside.sort(key=lambda x: -abs(x["gold"]))
    other.sort(key=lambda x: -abs(x["gold"]))

    hand = round(sum(b["gold"] for b in buckets if b["side"] == "hand"), 3)
    out_side = round(sum(b["gold"] for b in buckets if b["side"] == "out"), 3)
    out_sum = round(sum(r["gold"] for r in outside), 3)
    other_sum = round(sum(r["gold"] for r in other), 3)
    mapped = round(hand + out_side, 3)
    total = round(mapped + out_sum, 3)

    # **لماذا تُحسب النسب على الموجب لا على الصافي**: لو قُسّم على
    # الصافي لانفجرت النسبة كلما تقارب الموجب والسالب — دلوٌ فيه
    # مئة وآخر فيه سالب مئة يعطيان صافياً صفراً، فتصير كل نسبة
    # ألوفاً بلا معنى. والسؤال المقصود أصلاً: «من كل مئة جرامٍ
    # **موجود**، كم في اليد وكم عند الغير» — ومقامه الموجود.
    gross = round(sum(b["gold"] for b in buckets if b["gold"] > 0)
                  + max(out_sum, 0.0), 3)
    gross_hand = round(sum(b["gold"] for b in buckets
                           if b["side"] == "hand" and b["gold"] > 0), 3)
    gross_out = round(sum(b["gold"] for b in buckets
                          if b["side"] == "out" and b["gold"] > 0), 3)
    negatives = [b for b in buckets if b["gold"] < -0.0105]

    return {
        "as_of": as_of, "buckets": buckets, "outside": outside,
        "other": other, "hand": hand, "outside_hands": out_side,
        "unmapped": out_sum, "mapped": mapped, "total": total,
        "other_total": other_sum, "gross": gross,
        "gross_hand": gross_hand, "gross_out": gross_out,
        "negatives": negatives,
        # القفلة: أين الذهب + الطرف المقابل = صفر بحكم القيد المزدوج
        "diff": round(total + other_sum, 3),
    }


def gold_map(conn, as_of=None, compare_to=None):
    """خريطة الذهب في تاريخ، ومقارنتها بتاريخٍ سابق اختيارياً.

    `compare_to` تاريخٌ **أقدم**؛ يُضاف لكل دلوٍ رصيدُه يومها والفرق.
    """
    cur = _snapshot(conn, as_of)
    prev = _snapshot(conn, compare_to) if compare_to else None

    if prev:
        pv = {b["code"]: b["gold"] for b in prev["buckets"]}
        for b in cur["buckets"]:
            b["prev"] = pv.get(b["code"], 0.0)
            b["change"] = round(b["gold"] - b["prev"], 3)
        cur["prev_total"] = prev["total"]
        cur["prev_hand"] = prev["hand"]
        cur["prev_outside_hands"] = prev["outside_hands"]
        cur["change_total"] = round(cur["total"] - prev["total"], 3)
        cur["change_hand"] = round(cur["hand"] - prev["hand"], 3)
        cur["change_out"] = round(
            cur["outside_hands"] - prev["outside_hands"], 3)
        movers = [b for b in cur["buckets"] if abs(b["change"]) > EPS]
        movers.sort(key=lambda b: -abs(b["change"]))
        cur["movers"] = movers
    else:
        for b in cur["buckets"]:
            b["prev"] = None
            b["change"] = None
        cur["movers"] = []
    cur["compare_to"] = compare_to

    base = cur["gross"] if cur["gross"] > 0.011 else 0.0
    for b in cur["buckets"]:
        b["share"] = (round(max(b["gold"], 0.0) / base * 100.0, 1)
                      if base else None)
    cur["out_share"] = (round(cur["gross_out"] / base * 100.0, 1)
                        if base else None)
    cur["hand_share"] = (round(cur["gross_hand"] / base * 100.0, 1)
                         if base else None)
    cur["balanced"] = abs(cur["diff"]) < 0.011
    return cur


def _plain(v):
    return f"{v:,.3f}"


def verdict(m, fmt=None):
    """جملةٌ تُقرأ — لا رقمٌ يُفسَّر.

    أهمُّ ما في الخريطة ليس مجموعها بل **نسبة ما خرج من اليد**: مصنعٌ
    نصفُ ذهبه عند عملائه مصنعٌ يموّل زبائنه بلا فائدة، مهما بدا
    رصيدُه كبيراً.

    **ولماذا يُمرَّر المنسِّق من فوق**: الأرقام هنا مكافئُ عيار 18 —
    وهو ما يُخزَّن — والمستخدم يقرأ بعيار مصنعه. لو نسّقها هذا
    الملف لقال المصنعُ الذي يعمل بـ21 رقماً في الجملة وآخر في
    الجدول للرصيد نفسه. فالتحويل من شأن الواجهة، وهي تمرّره هنا.
    """
    fmt = fmt or _plain
    out = []
    if not m["balanced"]:
        out.append(
            f"⚠ الخريطة لا تقفل: فرقٌ قدره {fmt(abs(m['diff']))} — "
            "راجع «خارج الخريطة».")
    if m["gross"] <= 0.011:
        out.append("لا رصيد ذهبٍ في هذا التاريخ.")
        return out
    out.append(
        f"من كل ١٠٠ جرام: {m['hand_share']:,.1f} في يد المصنع و"
        f"{m['out_share']:,.1f} عند الغير.")
    if m["out_share"] >= 50:
        out.append(
            "أكثر من نصف ذهب المصنع خارج يده — هذا تمويلٌ للغير من "
            "رأس المال، راجع حدود الائتمان وأعمار الديون.")
    elif m["out_share"] >= 30:
        out.append("ثلث الذهب تقريباً خارج اليد — راقب أعمار الديون.")
    if m["negatives"]:
        names = "، ".join(f"«{b['label']}» {fmt(b['gold'])}"
                          for b in m["negatives"][:3])
        out.append(
            f"رصيدٌ سالب حيث لا يصحّ السالب: {names} — خرج وزنٌ أكثر "
            "ممّا دخل؛ راجع التوريد أو الأرصدة الافتتاحية.")
    if m["unmapped"] and abs(m["unmapped"]) > 0.011:
        names = "، ".join(r["name"] for r in m["outside"][:3])
        out.append(
            f"ذهبٌ في حساباتٍ خارج الدلاء الثمانية: "
            f"{fmt(m['unmapped'])} ({names}) — أضفه لخريطتك أو انقله.")
    if m.get("movers"):
        b = m["movers"][0]
        verb = "زاد" if b["change"] > 0 else "نقص"
        out.append(
            f"أكبر تغيّرٍ منذ تاريخ المقارنة: «{b['label']}» {verb} "
            f"{fmt(abs(b['change']))}.")
    return out
