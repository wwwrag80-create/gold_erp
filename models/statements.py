# -*- coding: utf-8 -*-
"""القوائم المالية بالنهج المحاسبي المعتمد — لمراجعٍ قانوني أو لهيئة الزكاة
والضريبة والجمارك.

قائمتان تُبنيان من **دفتر الأستاذ نفسه** وبشجرة الحسابات كاملةً:

1. **ميزان المراجعة بالأرصدة والمجاميع** — الشكل الذي يطلبه كل مراجع:
   لكل حساب ثلاثة أزواج (مدين | دائن): رصيد أول المدة، حركة الفترة،
   رصيد آخر المدة. وكل زوجٍ متوازنٌ وحده: مجموع مدينه = مجموع دائنه.
   بمستوياتٍ (من الأقسام الرئيسية إلى الحساب التفصيلي) ومجموعٍ لكل
   قسم — وبُعدٍ واحدٍ في كل مرة (النقد بالريال، أو الذهب وزناً)،
   فلا يختلط رقمان من وحدتين في عمودٍ واحد.

2. **قائمة المركز المالي** (الميزانية العمومية) بترتيب معيار المحاسبة
   الدولي 1 (IAS 1) المعتمد من الهيئة السعودية للمراجعين والمحاسبين:
   الأصول غير المتداولة ثم المتداولة، ثم حقوق الملكية، ثم المطلوبات
   غير المتداولة والمتداولة — وعمود مقارنة.

   ثلاث قواعد لا تُكسر فيها:
   * **لا مقاصّة** (IAS 1.32): عميلٌ رصيده دائن مطلوبٌ علينا لا
     تخفيضٌ للذمم المدينة، ومورّدٌ رصيده مدين دفعةٌ مقدّمة لا تخفيضٌ
     للدائنين. فالجهات تُفصل حساباً حساباً بحسب إشارة رصيدها.
   * **الإيراد والمصروف لا يظهران بنوداً في الميزانية** — يظهر أثرهما
     في حقوق الملكية وحدها: صافي ربح (خسارة) الفترة الحالية، ونتائج
     السنوات التي لم تُقفل تُضمّ إلى الأرباح المبقاة.
   * **كل حساب يُصنَّف مرةً واحدة** — ومن لم يطابق بنداً معروفاً يدخل
     بند «أخرى» من جنسه. فمجموع الأصول يساوي المطلوبات وحقوق الملكية
     دائماً، ولا يضيع حسابٌ أضافه المستخدم لاحقاً.

السنة المالية سنةٌ ميلادية (كالإقفال السنوي في `models/closing.py`).
"""
from datetime import date

ROOT_ORDER = ("1000", "2000", "3000", "4000", "5000", "6000")
TYPE_AR = {"asset": "الأصول", "liability": "الخصوم والالتزامات",
           "equity": "حقوق الملكية", "revenue": "الإيرادات",
           "expense": "المصروفات", "bridge": "حسابات وسيطة"}

_EPS = {"cash": 0.005, "gold": 0.0005}


# ══════════════════════════════════════════════════════════════════
#  شجرة الحسابات
# ══════════════════════════════════════════════════════════════════

def _tree(conn):
    rows = [dict(r) for r in conn.execute(
        "SELECT id, code, name, type, parent_id, is_postable, nature,"
        " COALESCE(is_active,1) is_active FROM accounts ORDER BY code")]
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["children"] = []
    for r in rows:
        p = by_id.get(r["parent_id"])
        if p is not None:
            p["children"].append(r)
    roots = [r for r in rows if by_id.get(r["parent_id"]) is None]
    order = {c: i for i, c in enumerate(ROOT_ORDER)}
    roots.sort(key=lambda r: (order.get(r["code"], 99), r["code"]))
    for r in rows:
        r["children"].sort(key=lambda x: x["code"])
    return rows, by_id, roots


def _root_of(node, by_id):
    cur, seen = node, 0
    while by_id.get(cur["parent_id"]) is not None and seen < 20:
        cur = by_id[cur["parent_id"]]
        seen += 1
    return cur


# ══════════════════════════════════════════════════════════════════
#  1) ميزان المراجعة بالأرصدة والمجاميع
# ══════════════════════════════════════════════════════════════════

def _split(v, eps):
    """رصيدٌ صافٍ ← (مدين، دائن): الموجب مدين والسالب دائن."""
    if v > eps:
        return v, 0.0
    if v < -eps:
        return 0.0, -v
    return 0.0, 0.0


def trial_balance(conn, date_from=None, date_to=None, dim="cash",
                  max_level=9, include_zero=False):
    """ميزان المراجعة بالأرصدة والمجاميع لبُعدٍ واحد (`cash` أو `gold`).

    يعيد صفوفاً مرتّبة بشجرة الحسابات، لكل صفٍّ:
        level · code · name · type · is_group · is_root · terminal
        open_dr · open_cr · dr · cr · close_dr · close_cr
    `terminal`: الصفّ الذي تُجمع منه الإجماليات (حسابٌ بلا فروعٍ معروضة)
    — فلا يُجمع حسابٌ مع أبيه مرتين.
    """
    dim = "gold" if dim == "gold" else "cash"
    eps = _EPS[dim]
    rnd = 3 if dim == "gold" else 2
    dcol, ccol = f"{dim}_debit", f"{dim}_credit"
    p = {"df": date_from or None, "dt": date_to or None}
    before = "(:df IS NOT NULL AND e.entry_date < :df)"
    within = ("(:df IS NULL OR e.entry_date >= :df)"
              " AND (:dt IS NULL OR e.entry_date <= :dt)")
    raw = {}
    for r in conn.execute(
            "SELECT l.account_id aid,"
            f" COALESCE(SUM(CASE WHEN {before} THEN l.{dcol}-l.{ccol}"
            "  ELSE 0 END),0) op,"
            f" COALESCE(SUM(CASE WHEN {within} THEN l.{dcol} ELSE 0 END),0) dr,"
            f" COALESCE(SUM(CASE WHEN {within} THEN l.{ccol} ELSE 0 END),0) cr"
            " FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
            " GROUP BY l.account_id", p):
        raw[r["aid"]] = (r["op"] or 0.0, r["dr"] or 0.0, r["cr"] or 0.0)

    rows_all, by_id, roots = _tree(conn)

    def roll(node):
        """يجمع الحساب مع فروعه: الحركة كما هي، والأرصدة **إجمالاً** —
        مجموع المدين من فروعه ومجموع الدائن — لا صافياً. فمجموع كل
        قسم يساوي مجموع حساباته، ومجاميع الأقسام تساوي إجمالي الميزان.
        """
        op, dr, cr = raw.get(node["id"], (0.0, 0.0, 0.0))
        od, oc = _split(op, eps)
        cd, cc = _split(op + dr - cr, eps)
        for ch in node["children"]:
            v = roll(ch)
            od += v[0]
            oc += v[1]
            dr += v[2]
            cr += v[3]
            cd += v[4]
            cc += v[5]
        node["_v"] = (od, oc, dr, cr, cd, cc)
        return node["_v"]

    for r in roots:
        roll(r)

    def is_zero(node):
        return all(abs(x) <= eps for x in node["_v"])

    out = []

    def walk(node, level):
        if not include_zero and is_zero(node):
            return
        kids = [c for c in node["children"]
                if include_zero or not is_zero(c)]
        shows_kids = level < max_level and bool(kids)
        od, oc, dr, cr, cd, cc = node["_v"]
        out.append({
            "level": level, "code": node["code"], "name": node["name"],
            "type": node["type"], "is_group": bool(node["children"]),
            "is_root": level == 1, "terminal": not shows_kids,
            "open_dr": round(od, rnd), "open_cr": round(oc, rnd),
            "dr": round(dr, rnd), "cr": round(cr, rnd),
            "close_dr": round(cd, rnd), "close_cr": round(cc, rnd)})
        if shows_kids:
            for ch in kids:
                walk(ch, level + 1)

    for r in roots:
        walk(r, 1)

    keys = ("open_dr", "open_cr", "dr", "cr", "close_dr", "close_cr")
    tot = {k: round(sum(x[k] for x in out if x["terminal"]), rnd)
           for k in keys}
    tol = 0.011
    tot["ok_open"] = abs(tot["open_dr"] - tot["open_cr"]) <= tol
    tot["ok_period"] = abs(tot["dr"] - tot["cr"]) <= tol
    tot["ok_close"] = abs(tot["close_dr"] - tot["close_cr"]) <= tol
    tot["balanced"] = tot["ok_open"] and tot["ok_period"] and tot["ok_close"]
    # مجموع كل قسمٍ رئيسي (للعرض وللطباعة)
    sections = [{"code": x["code"], "name": x["name"],
                 **{k: x[k] for k in keys}}
                for x in out if x["is_root"]]
    return {"rows": out, "totals": tot, "sections": sections, "dim": dim,
            "date_from": date_from or "", "date_to": date_to or "",
            "max_level": max_level,
            "accounts": sum(1 for x in out if x["terminal"])}


# ══════════════════════════════════════════════════════════════════
#  2) قائمة المركز المالي
# ══════════════════════════════════════════════════════════════════

# (المفتاح، العنوان، القسم) — ترتيب العرض ترتيب IAS 1
LINES = [
    # الأصول غير المتداولة
    ("ppe_cost", "الممتلكات والآلات والمعدات — بالتكلفة", "nca"),
    ("ppe_dep", "يُطرح: مجمّع الإهلاك", "nca"),
    ("nca_other", "أصول غير متداولة أخرى", "nca"),
    # الأصول المتداولة
    ("cash", "النقد وما في حكمه", "ca"),
    ("inventory", "المخزون — الذهب والفصوص والمشغولات", "ca"),
    ("receivables", "الذمم المدينة — العملاء والجهات", "ca"),
    ("ecl", "يُطرح: مخصص الخسائر الائتمانية المتوقعة", "ca"),
    ("supplier_adv", "دفعات مقدّمة للموردين", "ca"),
    ("staff", "سلف وعهد الموظفين والعمال", "ca"),
    ("prepaid", "مصروفات مدفوعة مقدماً", "ca"),
    ("vat_asset", "ضريبة القيمة المضافة المستردّة (صافي)", "ca"),
    ("ca_other", "أصول متداولة أخرى", "ca"),
    # حقوق الملكية
    ("capital", "رأس المال", "eq"),
    ("reserve", "الاحتياطيات", "eq"),
    ("partners", "جاري الشركاء", "eq"),
    ("retained", "الأرباح المبقاة (المرحّلة)", "eq"),
    ("opening_susp", "حساب تسوية الأرصدة الافتتاحية", "eq"),
    ("eq_other", "حقوق ملكية أخرى", "eq"),
    ("profit", "صافي ربح (خسارة) الفترة", "eq"),
    # المطلوبات غير المتداولة
    ("loans_lt", "قروض طويلة الأجل", "ncl"),
    ("eosb", "مخصص مكافأة نهاية الخدمة للموظفين", "ncl"),
    ("ncl_other", "مطلوبات غير متداولة أخرى", "ncl"),
    # المطلوبات المتداولة
    ("loans_st", "قروض قصيرة الأجل والجزء المتداول من القروض", "cl"),
    ("payables", "الذمم الدائنة — الموردون", "cl"),
    ("customer_adv", "دفعات مقدّمة وأمانات العملاء", "cl"),
    ("accruals", "مستحقات الموظفين والرواتب", "cl"),
    ("accrued", "مصروفات مستحقة", "cl"),
    ("zakat", "مخصص الزكاة", "cl"),
    ("vat_liab", "ضريبة القيمة المضافة المستحقة (صافي)", "cl"),
    ("cl_other", "مطلوبات متداولة أخرى", "cl"),
]
SECTIONS = [
    ("nca", "الأصول غير المتداولة", "assets"),
    ("ca", "الأصول المتداولة", "assets"),
    ("eq", "حقوق الملكية", "right"),
    ("ncl", "المطلوبات غير المتداولة", "right"),
    ("cl", "المطلوبات المتداولة", "right"),
]

# حساب ← بند (بالأقرب في الشجرة). الجهات تُفصل بالإشارة.
_MAP = {
    "1790": "ppe_dep", "1700": "ppe_cost",
    "1010": "cash", "1400": "cash", "1410": "cash", "1500": "cash",
    "1020": "inventory",
    "1950": "staff", "1960": "staff", "1970": "staff",
    "1900": "vat", "2100": "vat", "2150": "vat",
    "2200": "accruals", "2250": "accruals",
    "3110": "capital", "3120": "partners",
    "3200": "retained", "3210": "retained",
    "3900": "opening_susp",
    # تسويات نهاية الفترة (4.36)
    "1680": "ecl", "1980": "prepaid", "2280": "accrued",
    "2400": "zakat", "2600": "eosb",
    # مراجعة الدليل (4.37): القروض والاحتياطيات والتأمينات، وما يُضاف
    # لاحقاً تحت «غير المتداولة» يُقرأ غير متداول لا متداولاً
    "2350": "loans_st", "2700": "loans_lt", "3300": "reserve",
    "2290": "accruals", "1690": "nca_other", "2500": "ncl_other",
}
_PARTY_ASSET = ("1600", "1650")      # عملاء وجهات
_PARTY_SUPPLIER = ("2300",)          # موردون


def _classify(node, by_id):
    """أقرب مفتاحٍ في _MAP بين الحساب وأسلافه، أو نوع الجهة."""
    cur, seen = node, 0
    while cur is not None and seen < 20:
        if cur["code"] in _PARTY_ASSET:
            return "party_customer"
        if cur["code"] in _PARTY_SUPPLIER:
            return "party_supplier"
        if cur["code"] in _MAP:
            return _MAP[cur["code"]]
        cur = by_id.get(cur["parent_id"])
        seen += 1
    return None


# قيدا «الإغلاق الدفتري» و«فتح السنة» متعاكسان ويقعان في يومين: فالمركز
# المالي بتاريخ 31-12 يرى الإغلاق وحده فيُصفّر الأصول والحقوق. فيُهملان
# معاً — وقيد إقفال النتيجة (يمسّ الإيراد والمصروف) يبقى.
# COALESCE: قيدٌ بلا مصدر (NULL) يجعل الشرط NULL فيسقط القيد كلّه
_BOOK_PAIR = ("(COALESCE(e.source_table,'')='year_open'"
              " OR (COALESCE(e.source_table,'')='year_close'"
              " AND NOT EXISTS(SELECT 1 FROM journal_lines x"
              " JOIN accounts xa ON xa.id=x.account_id"
              " WHERE x.entry_id=e.id AND xa.type IN ('revenue','expense'))))")


def _balances(conn, as_of, dim):
    col_d, col_c = f"{dim}_debit", f"{dim}_credit"
    out = {}
    for r in conn.execute(
            f"SELECT l.account_id aid, COALESCE(SUM(l.{col_d}-l.{col_c}),0) b"
            " FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
            f" WHERE e.entry_date<=? AND NOT {_BOOK_PAIR}"
            " GROUP BY l.account_id", (as_of,)):
        out[r["aid"]] = r["b"] or 0.0
    return out


def _pl(conn, d1, d2, dim):
    """صافي نتيجة الإيراد والمصروف بين تاريخين (ربحٌ موجب)."""
    col_d, col_c = f"{dim}_debit", f"{dim}_credit"
    p = [d2]
    cond = "e.entry_date<=?"
    if d1:
        cond = "e.entry_date>=? AND " + cond
        p = [d1, d2]
    r = conn.execute(
        f"SELECT COALESCE(SUM(l.{col_d}-l.{col_c}),0) b"
        " FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
        " JOIN accounts a ON a.id=l.account_id"
        f" WHERE a.type IN ('revenue','expense') AND {cond}", p).fetchone()
    return -(r["b"] or 0.0)


def _position_dim(conn, as_of, dim, rows, by_id):
    """بنود المركز المالي لبُعدٍ واحد — القيم موجبةً للعرض."""
    eps = _EPS[dim]
    bal = _balances(conn, as_of, dim)
    v = {k: 0.0 for k, _t, _s in LINES}
    detail = {k: [] for k, _t, _s in LINES}
    vat_net = 0.0
    vat_rows = []

    def add(key, amount, node):
        v[key] += amount
        if abs(amount) > eps:
            detail[key].append((node["code"], node["name"], amount))

    for node in rows:
        b = bal.get(node["id"], 0.0)
        if abs(b) <= eps:
            continue
        root = _root_of(node, by_id)
        rtype = root["type"]
        if rtype in ("revenue", "expense"):
            continue                          # أثرها في حقوق الملكية
        kind = _classify(node, by_id)
        if kind == "party_customer":
            # مدينٌ ⇒ ذمة مدينة · دائنٌ ⇒ دفعةٌ مقدّمة من العميل (مطلوب)
            add("receivables" if b > 0 else "customer_adv", abs(b), node)
        elif kind == "party_supplier":
            add("supplier_adv" if b > 0 else "payables", abs(b), node)
        elif kind == "vat":
            vat_net += b
            vat_rows.append((node["code"], node["name"], b))
        elif kind in ("ppe_dep", "ecl"):
            # دائنان بطبيعتهما: يبقيان سالبين في جانب الأصول فيُطرحان
            # من التكلفة ومن الذمم
            add(kind, b, node)
        elif kind in ("ppe_cost", "cash", "inventory", "staff", "prepaid"):
            add(kind, b, node)
        elif kind in ("accruals", "accrued", "zakat", "eosb", "loans_st",
                      "loans_lt", "ncl_other"):
            add(kind, -b, node)
        elif kind == "nca_other":
            add(kind, b, node)
        elif kind in ("capital", "partners", "retained", "opening_susp",
                      "reserve"):
            add(kind, -b, node)
        elif rtype == "asset":
            add("ca_other", b, node)
        elif rtype == "liability":
            add("cl_other", -b, node)
        elif rtype == "equity":
            add("eq_other", -b, node)
        else:
            # حسابات وسيطة (مركز التسكير): بالإشارة
            if b > 0:
                add("ca_other", b, node)
            else:
                add("cl_other", -b, node)

    # الضريبة: مقاصّةٌ مشروعة — لجهةٍ واحدة (الهيئة) وتُسدَّد بالصافي
    if vat_net > eps:
        v["vat_asset"] = vat_net
        detail["vat_asset"] = vat_rows
    elif vat_net < -eps:
        v["vat_liab"] = -vat_net
        detail["vat_liab"] = [(c, n, -x) for c, n, x in vat_rows]

    # نتيجة الفترة: من أول السنة المالية حتى التاريخ؛ وما قبلها ولم
    # يُقفل يُضمّ إلى الأرباح المبقاة
    y0 = f"{as_of[:4]}-01-01"
    v["profit"] = _pl(conn, y0, as_of, dim)
    prior = _pl(conn, None, _day_before(y0), dim)
    if abs(prior) > eps:
        v["retained"] += prior
        detail["retained"].append(("—", "نتائج سنوات سابقة لم تُقفل",
                                   prior))
    rnd = 3 if dim == "gold" else 2
    return ({k: round(x, rnd) for k, x in v.items()}, detail)


def _day_before(d):
    from datetime import timedelta
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def _totals(v, rnd):
    s = {}
    for key, _t, sec in LINES:
        s[sec] = s.get(sec, 0.0) + v[key]
    s = {k: round(x, rnd) for k, x in s.items()}
    s["assets"] = round(s.get("nca", 0) + s.get("ca", 0), rnd)
    s["liabilities"] = round(s.get("ncl", 0) + s.get("cl", 0), rnd)
    s["right"] = round(s["liabilities"] + s.get("eq", 0), rnd)
    s["diff"] = round(s["assets"] - s["right"], rnd)
    return s


def financial_position(conn, as_of=None, compare_to=None):
    """قائمة المركز المالي كما في `as_of` ومقارنةً بـ`compare_to`.

    الافتراضي للمقارنة: نهاية السنة المالية السابقة (31-12)، كما يطلب
    IAS 1. تعيد لكل بُعد (cash/gold) قيم البنود والمجاميع والتفصيل.
    """
    as_of = as_of or date.today().isoformat()
    if compare_to is None:
        compare_to = f"{int(as_of[:4]) - 1}-12-31"
    rows, by_id, _roots = _tree(conn)
    out = {"as_of": as_of, "compare_to": compare_to or "",
           "lines": LINES, "sections": SECTIONS}
    for dim in ("cash", "gold"):
        rnd = 3 if dim == "gold" else 2
        cur, det = _position_dim(conn, as_of, dim, rows, by_id)
        out[dim] = {"values": cur, "totals": _totals(cur, rnd),
                    "detail": det}
        if compare_to:
            cmp_v, _d = _position_dim(conn, compare_to, dim, rows, by_id)
            out[dim]["compare"] = cmp_v
            out[dim]["compare_totals"] = _totals(cmp_v, rnd)
    c, g = out["cash"]["totals"], out["gold"]["totals"]
    out["balanced_cash"] = abs(c["diff"]) < 0.011
    out["balanced_gold"] = abs(g["diff"]) < 0.0011
    return out


def _hidden(vals, eps=0.0005):
    return all(abs(x or 0.0) <= eps for x in vals)


def layout(fp):
    """قائمة المركز المالي صفوفاً جاهزة للعرض والطباعة — ترتيب IAS 1.

    لكل صفٍّ: kind (head · sec · line · net · sub · total · grand)،
    label، key، ثم القيم cash · cash_cmp · gold · gold_cmp. البنود
    الصفرية في الأعمدة الأربعة تُحذف، والقسم الفارغ كلّه يُحذف.
    """
    c, g = fp["cash"], fp["gold"]
    has_cmp = "compare" in c

    def vals(src, key, tot=False):
        a = src["totals" if tot else "values"].get(key, 0.0)
        b = (src["compare_totals" if tot else "compare"].get(key, 0.0)
             if has_cmp else 0.0)
        return a, b

    def row(kind, label, key="", tot=False):
        ca, cb = vals(c, key, tot) if key else (0.0, 0.0)
        ga, gb = vals(g, key, tot) if key else (0.0, 0.0)
        return {"kind": kind, "label": label, "key": key,
                "cash": ca, "cash_cmp": cb, "gold": ga, "gold_cmp": gb}

    titles = {k: t for k, t, _s in LINES}
    by_sec = {}
    for k, _t, s in LINES:
        by_sec.setdefault(s, []).append(k)
    out = []

    def section(sec, title, total_label):
        lines = [row("line", titles[k], k) for k in by_sec[sec]]
        lines = [r for r in lines if not _hidden(
            (r["cash"], r["cash_cmp"], r["gold"], r["gold_cmp"]))]
        if not lines:
            return
        out.append({"kind": "sec", "label": title, "key": sec})
        for r in lines:
            out.append(r)
            if r["key"] == "ppe_dep":
                n = row("net", "صافي القيمة الدفترية للممتلكات والمعدات")
                for f in ("cash", "cash_cmp", "gold", "gold_cmp"):
                    n[f] = next((x[f] for x in lines
                                 if x["key"] == "ppe_cost"), 0.0) + r[f]
                out.append(n)
        out.append(row("sub", total_label, sec, tot=True))

    sec_t = {k: t for k, t, _p in SECTIONS}
    out.append({"kind": "head", "label": "الأصول"})
    section("nca", sec_t["nca"], "مجموع الأصول غير المتداولة")
    section("ca", sec_t["ca"], "مجموع الأصول المتداولة")
    out.append(row("grand", "مجموع الأصول", "assets", tot=True))
    out.append({"kind": "head", "label": "حقوق الملكية والمطلوبات"})
    section("eq", sec_t["eq"], "مجموع حقوق الملكية")
    section("ncl", sec_t["ncl"], "مجموع المطلوبات غير المتداولة")
    section("cl", sec_t["cl"], "مجموع المطلوبات المتداولة")
    out.append(row("total", "مجموع المطلوبات", "liabilities", tot=True))
    out.append(row("grand", "مجموع حقوق الملكية والمطلوبات", "right",
                   tot=True))
    return out


# ══════════════════════════════════════════════════════════════════
#  3) قائمة الدخل (الأرباح والخسائر)
# ══════════════════════════════════════════════════════════════════
#
# بطريقة «وظيفة المصروف» (IAS 1.103) — الأشيع في القوائم السعودية
# المدقّقة: الإيراد، ثم تكلفة الإيراد ⇒ مجمل الربح، ثم المصاريف
# الإدارية ⇒ الربح التشغيلي، ثم الإيرادات والمصروفات الأخرى ⇒ صافي
# ربح الفترة. من دفتر الأستاذ نفسه (أساس الاستحقاق) لا من الفواتير ولا
# من سندات الصرف: فالسداد لمورّد ليس مصروفاً، والضريبة ليست إيراداً.
#
# القيم «بأثرها على الربح»: الإيراد موجب والمصروف سالب — فالمجاميع
# جمعٌ مباشر، والسالب يُطبع بين قوسين.

IS_LINES = [
    ("sales", "المبيعات والإيرادات التشغيلية", "rev"),
    ("returns", "يُطرح: مردودات المبيعات", "rev"),
    ("discounts", "يُطرح: الخصم المسموح به", "rev"),
    ("cos_gold", "تكلفة الذهب المباع وفواقد التشغيل", "cos"),
    # 4.39: بندان مستقلان يراهما المراجع ولا يختلطان بالفاقد
    ("recovered", "يُطرح من الفواقد: المسترجع من التصفية", "cos"),
    ("stones", "الفصوص والأحجار المصروفة للتصنيع", "cos"),
    ("cos_labor", "رواتب وأجور التشغيل", "cos"),
    ("cos_other", "مواد ومصروفات تشغيل مباشرة", "cos"),
    ("admin", "المصاريف الإدارية والعمومية", "opex"),
    ("depr", "إهلاك الأصول الثابتة", "opex"),
    ("ecl_exp", "الخسائر الائتمانية المتوقعة", "opex"),
    ("other_income", "إيرادات أخرى", "other"),
    ("other_exp", "مصروفات أخرى", "other"),
    ("zakat", "الزكاة", "zakat"),
]
IS_SUBTOTALS = [
    # (بعد القسم، المفتاح، العنوان)
    ("rev", "net_revenue", "صافي الإيرادات"),
    ("cos", "gross", "مجمل الربح (الخسارة)"),
    ("opex", "operating", "الربح (الخسارة) التشغيلي"),
    ("other", "before_zakat", "صافي الربح (الخسارة) قبل الزكاة"),
    ("zakat", "net", "صافي ربح (خسارة) الفترة"),
]
IS_SECTIONS = {"rev": "الإيرادات", "cos": "تكلفة الإيرادات",
               "opex": "المصاريف التشغيلية",
               "other": "الإيرادات والمصروفات الأخرى",
               "zakat": "الزكاة"}

_IS_MAP = {
    "4900": "returns", "4200": "other_income", "4300": "other_income",
    "5200": "discounts", "5300": "discounts",
    "5100": "cos_gold", "5700": "cos_labor", "5710": "cos_labor",
    "5190": "recovered", "5520": "stones",
    "5050": "cos_other", "5860": "depr", "5800": "admin",
    "5900": "other_exp", "5880": "ecl_exp", "5950": "zakat",
    "4400": "other_income",
}


def _is_classify(node, by_id, root_type):
    cur, seen = node, 0
    while cur is not None and seen < 20:
        if cur["code"] in _IS_MAP:
            return _IS_MAP[cur["code"]]
        cur = by_id.get(cur["parent_id"])
        seen += 1
    return "sales" if root_type == "revenue" else "other_exp"


def _is_period(conn, d1, d2, dim, rows, by_id):
    """بنود قائمة الدخل لفترة وبُعد — بأثرها على الربح."""
    eps = _EPS[dim]
    col_d, col_c = f"{dim}_debit", f"{dim}_credit"
    bal = {}
    for r in conn.execute(
            f"SELECT l.account_id aid, COALESCE(SUM(l.{col_d}-l.{col_c}),0) b"
            " FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
            " WHERE e.entry_date BETWEEN ? AND ?"
            # قيد الإقفال السنوي يصفّر النتيجة — ليس حركة تشغيل
            " AND COALESCE(e.source_table,'')<>'year_close'"
            " GROUP BY l.account_id", (d1, d2)):
        bal[r["aid"]] = r["b"] or 0.0
    v = {k: 0.0 for k, _t, _s in IS_LINES}
    detail = {k: [] for k, _t, _s in IS_LINES}
    for node in rows:
        b = bal.get(node["id"], 0.0)
        if abs(b) <= eps:
            continue
        rtype = _root_of(node, by_id)["type"]
        if rtype not in ("revenue", "expense"):
            continue
        key = _is_classify(node, by_id, rtype)
        v[key] += -b                        # أثرها على الربح
        detail[key].append((node["code"], node["name"], -b))
    rnd = 3 if dim == "gold" else 2
    v = {k: round(x, rnd) for k, x in v.items()}
    t, run = {}, 0.0
    for sec, key, _title in IS_SUBTOTALS:
        run += sum(v[k] for k, _t, s in IS_LINES if s == sec)
        t[key] = round(run, rnd)
    t["revenue_gross"] = v["sales"]
    t["cos"] = round(sum(v[k] for k, _t, s in IS_LINES if s == "cos"), rnd)
    t["opex"] = round(sum(v[k] for k, _t, s in IS_LINES if s == "opex"), rnd)
    return v, t, detail


def _shift_year(d, years=-1):
    y, m, dd = int(d[:4]) + years, int(d[5:7]), int(d[8:10])
    if m == 2 and dd == 29:
        dd = 28
    return f"{y:04d}-{m:02d}-{dd:02d}"


def income_statement(conn, date_from, date_to, compare=True):
    """قائمة الدخل للفترة، ومقارنةً بالفترة نفسها من السنة السابقة.

    `compare`: True (الفترة المماثلة من السنة السابقة) أو (من، إلى)
    صريحان أو False.
    """
    rows, by_id, _roots = _tree(conn)
    if compare is True:
        c1, c2 = _shift_year(date_from), _shift_year(date_to)
    elif compare:
        c1, c2 = compare
    else:
        c1 = c2 = ""
    out = {"date_from": date_from, "date_to": date_to,
           "compare_from": c1, "compare_to": c2,
           "lines": IS_LINES, "subtotals": IS_SUBTOTALS}
    for dim in ("cash", "gold"):
        v, t, det = _is_period(conn, date_from, date_to, dim, rows, by_id)
        out[dim] = {"values": v, "totals": t, "detail": det}
        if c1:
            cv, ct, _d = _is_period(conn, c1, c2, dim, rows, by_id)
            out[dim]["compare"] = cv
            out[dim]["compare_totals"] = ct
    return out


def is_layout(st, accounts=False):
    """قائمة الدخل صفوفاً للعرض والطباعة: sec · line · acct · sub · grand.

    `accounts`: يُدرج تحت كل بندٍ حساباته (إيضاح البند) للفترة الحالية.
    """
    c, g = st["cash"], st["gold"]
    has_cmp = "compare" in c

    def row(kind, label, key, tot=False):
        src = "totals" if tot else "values"
        csrc = "compare_totals" if tot else "compare"
        return {"kind": kind, "label": label, "key": key,
                "cash": c[src].get(key, 0.0),
                "cash_cmp": c[csrc].get(key, 0.0) if has_cmp else 0.0,
                "gold": g[src].get(key, 0.0),
                "gold_cmp": g[csrc].get(key, 0.0) if has_cmp else 0.0}

    out = []
    for sec, key, title in IS_SUBTOTALS:
        lines = [row("line", t, k) for k, t, s in IS_LINES if s == sec]
        lines = [r for r in lines if not _hidden(
            (r["cash"], r["cash_cmp"], r["gold"], r["gold_cmp"]))]
        if lines:
            out.append({"kind": "sec", "label": IS_SECTIONS[sec], "key": sec})
            for ln in lines:
                out.append(ln)
                if accounts:
                    out.extend(_is_accounts(st, ln["key"]))
        out.append(row("grand" if key == "net" else "sub", title, key,
                       tot=True))
    return out


def _is_accounts(st, key):
    acc = {}
    for dim in ("cash", "gold"):
        for code, name, amt in st[dim]["detail"].get(key, []):
            e = acc.setdefault(code, {"kind": "acct", "key": key,
                                      "label": f"{code} — {name}",
                                      "cash": 0.0, "cash_cmp": 0.0,
                                      "gold": 0.0, "gold_cmp": 0.0})
            e[dim] += amt
    return [acc[k] for k in sorted(acc)]


# ══════════════════════════════════════════════════════════════════
#  4) قائمة التدفقات النقدية (IAS 7)
# ══════════════════════════════════════════════════════════════════
#
# النقد وما في حكمه = حسابات الصندوق والبنوك (بند «النقد» في المركز
# المالي). والذهب مخزونٌ لا نقد — فالقائمة بالريال وحده.
#
# تُبنى من القيود نفسها لا من السندات: كل قيدٍ متوازن، فتغيّر النقد في
# أي قيد = سالب مجموع حركة حساباته الأخرى. فيُنسب كل ريالٍ دخل الصندوق
# أو خرج منه إلى نشاط الحساب المقابل له (تشغيلي · استثماري · تمويلي)
# — وهذه الطريقة المباشرة. والطريقة غير المباشرة تبدأ بصافي الربح ثم
# تسوّي البنود غير النقدية وتغيّرات رأس المال العامل، وتنتهي إلى الرقم
# نفسه. والتحويل بين الصندوق والبنك ليس تدفقاً (صافيه صفر).
#
# قيود الإقفال السنوي وفتح السنة تُهمل (دفتريةٌ متعاكسة)، والأرصدة
# الافتتاحية تُضمّ إلى رصيد أول الفترة لا إلى التدفقات.

CF_SECTIONS = [("op", "التدفقات النقدية من الأنشطة التشغيلية",
                "صافي النقد من (المستخدم في) الأنشطة التشغيلية"),
               ("inv", "التدفقات النقدية من الأنشطة الاستثمارية",
                "صافي النقد من (المستخدم في) الأنشطة الاستثمارية"),
               ("fin", "التدفقات النقدية من الأنشطة التمويلية",
                "صافي النقد من (المستخدم في) الأنشطة التمويلية")]

# غير المباشرة — الأنشطة التشغيلية
CF_INDIRECT = [
    ("profit", "صافي ربح (خسارة) الفترة"),
    ("dep", "يُضاف: الإهلاك"),
    ("wc_receivables", "(الزيادة) النقص في ذمم العملاء والجهات"),
    ("wc_inventory", "(الزيادة) النقص في المخزون"),
    ("wc_staff", "(الزيادة) النقص في سلف وعهد الموظفين"),
    ("wc_payables", "الزيادة (النقص) في ذمم الموردين"),
    ("wc_accruals", "الزيادة (النقص) في مستحقات الموظفين"),
    ("wc_vat", "الزيادة (النقص) في صافي ضريبة القيمة المضافة"),
    ("wc_prepaid", "التغير في المصروفات المقدمة والمستحقة"),
    ("provisions", "يُضاف: صافي المخصصات (زكاة · نهاية خدمة · ائتمانية)"),
    ("wc_other", "التغير في أصول ومطلوبات تشغيلية أخرى"),
    ("noncash", "يُستبعد: أثر معاملات استثمارية وتمويلية غير نقدية"),
]
# المباشرة — الأنشطة التشغيلية
CF_DIRECT = [
    ("d_customers", "المتحصلات من العملاء والجهات"),
    ("d_revenue", "إيرادات مقبوضة مباشرة"),
    ("d_fixing", "تسكير الذهب نقداً (بيع/شراء الذهب)"),
    ("d_suppliers", "المدفوع للموردين"),
    ("d_inventory", "مشتريات ذهب ومواد نقداً"),
    ("d_staff", "المدفوع للموظفين والعمال"),
    ("d_expenses", "المصروفات التشغيلية المدفوعة"),
    ("d_vat", "ضريبة القيمة المضافة المسددة (المستردة)"),
    ("d_zakat", "الزكاة المسددة"),
    ("d_other", "متحصلات ومدفوعات تشغيلية أخرى"),
]
CF_INVESTING = [("i_ppe", "(شراء) بيع ممتلكات وآلات ومعدات"),
                ("i_other", "تدفقات استثمارية أخرى")]
CF_FINANCING = [("f_loans", "القروض — المحصَّل (المسدَّد)"),
                ("f_capital", "رأس المال المدفوع (المسحوب)"),
                ("f_partners", "جاري الشركاء — إيداعات (مسحوبات)"),
                ("f_retained", "توزيعات أرباح وتسويات الأرباح المبقاة"),
                ("f_opening", "حساب تسوية الأرصدة الافتتاحية"),
                ("f_other", "تدفقات تمويلية أخرى")]

_CF_IGNORE = ("year_close", "year_open")


def _cf_class(node, by_id, rows_type):
    """(نوع الحساب في التدفقات) — مفتاحٌ واحد لكل حساب."""
    rtype = rows_type
    if rtype in ("revenue", "expense"):
        cur, seen = node, 0
        while cur is not None and seen < 20:
            if cur["code"] in ("5700", "5710"):
                return "exp_staff"
            cur = by_id.get(cur["parent_id"])
            seen += 1
        return "rev" if rtype == "revenue" else "exp"
    kind = _classify(node, by_id)
    if kind == "cash":
        return "cash"
    if kind in ("party_customer", "party_supplier", "inventory", "staff",
                "accruals", "vat", "ppe_cost", "ppe_dep", "capital",
                "partners", "retained", "opening_susp", "ecl", "prepaid",
                "accrued", "zakat", "eosb", "loans_st", "loans_lt",
                "reserve", "nca_other", "ncl_other"):
        return kind
    if rtype == "equity":
        return "eq_other"
    if rtype == "bridge":
        return "bridge"
    return "other_wc"          # أصول ومطلوبات أخرى: تشغيلية


# الحساب ← (سطر المباشرة/الاستثمار/التمويل، سطر غير المباشرة، النشاط)
_CF_ROUTE = {
    "party_customer": ("d_customers", "wc_receivables", "op"),
    "party_supplier": ("d_suppliers", "wc_payables", "op"),
    "inventory": ("d_inventory", "wc_inventory", "op"),
    "staff": ("d_staff", "wc_staff", "op"),
    "accruals": ("d_staff", "wc_accruals", "op"),
    "exp_staff": ("d_staff", "profit", "op"),
    "vat": ("d_vat", "wc_vat", "op"),
    "prepaid": ("d_expenses", "wc_prepaid", "op"),
    "accrued": ("d_expenses", "wc_prepaid", "op"),
    "zakat": ("d_zakat", "provisions", "op"),
    "eosb": ("d_staff", "provisions", "op"),
    "ecl": ("d_customers", "provisions", "op"),
    "rev": ("d_revenue", "profit", "op"),
    "exp": ("d_expenses", "profit", "op"),
    "bridge": ("d_fixing", "wc_other", "op"),
    "other_wc": ("d_other", "wc_other", "op"),
    "ppe_dep": ("d_other", "dep", "op"),
    "ppe_cost": ("i_ppe", None, "inv"),
    "nca_other": ("i_other", None, "inv"),
    "loans_st": ("f_loans", None, "fin"),
    "loans_lt": ("f_loans", None, "fin"),
    "ncl_other": ("f_other", None, "fin"),
    "reserve": ("f_other", None, "fin"),
    "capital": ("f_capital", None, "fin"),
    "partners": ("f_partners", None, "fin"),
    "retained": ("f_retained", None, "fin"),
    "opening_susp": ("f_opening", None, "fin"),
    "eq_other": ("f_other", None, "fin"),
}


def _cf_period(conn, d1, d2, rows, by_id):
    from models import opening as _op
    cls = {}
    for n in rows:
        cls[n["id"]] = _cf_class(n, by_id, _root_of(n, by_id)["type"])
    cash_ids = [a for a, c in cls.items() if c == "cash"]
    ign = ",".join("?" * len(_CF_IGNORE))
    op_cond, op_params = _op.sql(conn, "e")
    base = (" FROM journal_lines l JOIN journal_entries e"
            " ON e.id=l.entry_id AND e.is_deleted=0"
            f" WHERE COALESCE(e.source_table,'') NOT IN ({ign})")
    # (1) الأرصدة: أول الفترة يشمل الأرصدة الافتتاحية المُدخلة داخلها
    cq = ",".join("?" * len(cash_ids)) or "NULL"

    def cash_sum(extra, params):
        r = conn.execute(
            "SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) b" + base
            + f" AND l.account_id IN ({cq}) AND " + extra,
            list(_CF_IGNORE) + cash_ids + params).fetchone()
        return r["b"] or 0.0

    opening_bal = (cash_sum("e.entry_date<?", [d1])
                   + cash_sum(f"e.entry_date BETWEEN ? AND ? AND {op_cond}",
                              [d1, d2] + op_params))
    closing_bal = cash_sum("e.entry_date<=?", [d2])
    # (2) الحركة: كل قيدٍ غير افتتاحي داخل الفترة
    ent = {}
    for r in conn.execute(
            "SELECT l.entry_id eid, l.account_id aid,"
            " SUM(l.cash_debit-l.cash_credit) m" + base
            + f" AND e.entry_date BETWEEN ? AND ? AND NOT {op_cond}"
            " GROUP BY l.entry_id, l.account_id",
            list(_CF_IGNORE) + [d1, d2] + op_params):
        if abs(r["m"] or 0.0) > 1e-9:
            ent.setdefault(r["eid"], []).append((r["aid"], r["m"]))
    keys = ([k for k, _t in CF_INDIRECT] + [k for k, _t in CF_DIRECT]
            + [k for k, _t in CF_INVESTING] + [k for k, _t in CF_FINANCING])
    v = {k: 0.0 for k in keys}
    act = {"op": 0.0, "inv": 0.0, "fin": 0.0}
    for lines in ent.values():
        d_cash = sum(m for a, m in lines if cls.get(a) == "cash")
        touches = abs(d_cash) > 0.0005
        for a, m in lines:
            c = cls.get(a, "other_wc")
            if c == "cash":
                continue
            direct, indirect, sec = _CF_ROUTE.get(c, _CF_ROUTE["other_wc"])
            eff = -m                       # أثره على النقد
            if indirect:
                v[indirect] += eff         # غير المباشرة: كل القيود
            if touches:
                v[direct] += eff           # المباشرة/الاستثمار/التمويل
                act[sec] += eff
    # ══ أصلٌ اشتُري بالأجل ثم سُدِّد ثمنه ══
    # السداد يمرّ بحساب المورّد فيُقرأ «مدفوعاً للموردين» (تشغيلياً)،
    # وهو في حقيقته ثمن أصلٍ ثابت ⇒ استثماري (IAS 7.16). فيُعاد تصنيف
    # ما سُدِّد لكل مورّد في حدود ما نشأ عليه من شراء أصولٍ في الفترة.
    ppe_payable, paid = {}, {}
    for lines in ent.values():
        ppe_dr = sum(m for a, m in lines if cls.get(a) == "ppe_cost"
                     and m > 0)
        d_cash = sum(m for a, m in lines if cls.get(a) == "cash")
        for a, m in lines:
            if cls.get(a) != "party_supplier":
                continue
            if ppe_dr > 0 and m < 0 and abs(d_cash) <= 0.0005:
                ppe_payable[a] = ppe_payable.get(a, 0.0) + min(ppe_dr, -m)
            if abs(d_cash) > 0.0005 and m > 0:
                paid[a] = paid.get(a, 0.0) + m
    reclass = 0.0
    for a, amt in ppe_payable.items():
        reclass += min(amt, paid.get(a, 0.0))
    if reclass > 0.0005:
        v["d_suppliers"] += reclass
        v["i_ppe"] -= reclass
        act["op"] += reclass
        act["inv"] -= reclass
    noncash_inv = sum(ppe_payable.values()) - reclass

    # غير المباشرة تنتهي إلى صافي التشغيل نفسه — والفرق أثر معاملاتٍ
    # استثمارية/تمويلية لم يمرّ فيها نقد (أصلٌ اشتُري بالأجل مثلاً)
    ind_sum = sum(v[k] for k, _t in CF_INDIRECT if k != "noncash")
    v["noncash"] = act["op"] - ind_sum
    net = act["op"] + act["inv"] + act["fin"]
    rnd = {k: round(x, 2) for k, x in v.items()}
    return {"values": rnd,
            "totals": {"op": round(act["op"], 2), "inv": round(act["inv"], 2),
                       "fin": round(act["fin"], 2), "net": round(net, 2),
                       "opening": round(opening_bal, 2),
                       "closing": round(closing_bal, 2),
                       "noncash": round(noncash_inv, 2),
                       "diff": round(opening_bal + net - closing_bal, 2)}}


def cash_flow(conn, date_from, date_to, compare=True):
    """قائمة التدفقات النقدية للفترة، ومقارنةً بالمماثلة من السنة السابقة."""
    rows, by_id, _roots = _tree(conn)
    if compare is True:
        c1, c2 = _shift_year(date_from), _shift_year(date_to)
    elif compare:
        c1, c2 = compare
    else:
        c1 = c2 = ""
    out = {"date_from": date_from, "date_to": date_to,
           "compare_from": c1, "compare_to": c2,
           "cur": _cf_period(conn, date_from, date_to, rows, by_id)}
    if c1:
        out["cmp"] = _cf_period(conn, c1, c2, rows, by_id)
    out["balanced"] = abs(out["cur"]["totals"]["diff"]) < 0.011
    return out


def cf_layout(cf, method="indirect"):
    """صفوف القائمة للعرض والطباعة — sec · line · sub · grand · bal."""
    cur, cmp_ = cf["cur"], cf.get("cmp")

    def row(kind, label, key, tot=False):
        src = "totals" if tot else "values"
        return {"kind": kind, "label": label, "key": key,
                "cash": cur[src].get(key, 0.0),
                "cash_cmp": cmp_[src].get(key, 0.0) if cmp_ else 0.0}

    def lines(spec):
        out_ = [row("line", t, k) for k, t in spec]
        return [r for r in out_
                if abs(r["cash"]) >= 0.005 or abs(r["cash_cmp"]) >= 0.005]

    out = []
    spec = {"op": CF_INDIRECT if method == "indirect" else CF_DIRECT,
            "inv": CF_INVESTING, "fin": CF_FINANCING}
    for sec, title, total in CF_SECTIONS:
        out.append({"kind": "sec", "label": title, "key": sec})
        body = lines(spec[sec])
        if sec == "op" and method == "indirect":
            # صافي الربح يظهر دائماً ولو صفراً — منه تبدأ القائمة
            if not any(r["key"] == "profit" for r in body):
                body.insert(0, row("line", CF_INDIRECT[0][1], "profit"))
        out.extend(body)
        out.append(row("sub", total, sec, tot=True))
    out.append(row("grand", "صافي الزيادة (النقص) في النقد وما في حكمه",
                   "net", tot=True))
    out.append(row("bal", "النقد وما في حكمه أول الفترة", "opening",
                   tot=True))
    out.append(row("grand", "النقد وما في حكمه آخر الفترة", "closing",
                   tot=True))
    return out


# ══════════════════════════════════════════════════════════════════
#  5) قائمة التغيرات في حقوق الملكية (IAS 1.106)
# ══════════════════════════════════════════════════════════════════
#
# عمودٌ لكل مكوّن من حقوق الملكية ومجموعٌ لها، وصفوفٌ تفسّر الانتقال
# من رصيد أول الفترة إلى آخرها: صافي ربح الفترة، ثم المعاملات مع
# الملاك (رأس المال · جاري الشركاء · التوزيعات)، ثم تحويل النتيجة عند
# الإقفال السنوي — للفترة الحالية وفترة المقارنة معاً كما يطلب المعيار.
#
# «الأرباح المبقاة» تشمل النتائج التي لم تُقفل بعد (إيرادات ومصروفات
# لم يمرّ عليها قيد الإقفال) — فمجموع العمود يطابق حقوق الملكية في
# قائمة المركز المالي، ويبقى صحيحاً قبل الإقفال السنوي وبعده.

EQ_COLS = [("capital", "رأس المال"), ("reserve", "الاحتياطيات"),
           ("partners", "جاري الشركاء"),
           ("retained", "الأرباح المبقاة"),
           ("opening_susp", "تسوية الأرصدة الافتتاحية"),
           ("eq_other", "حقوق ملكية أخرى")]
EQ_ROWS = [("profit", "صافي ربح (خسارة) الفترة"),
           ("r_capital", "زيادة (تخفيض) رأس المال"),
           ("r_partners", "إيداعات (مسحوبات) الشركاء"),
           ("r_dividends", "توزيعات أرباح وتسويات على الأرباح المبقاة"),
           ("r_reserve", "المحوَّل إلى الاحتياطيات"),
           ("transfer", "تحويل نتيجة السنة عند الإقفال السنوي"),
           ("r_opening_adj", "تسويات حساب الأرصدة الافتتاحية"),
           ("r_other", "حركات أخرى على حقوق الملكية")]
_EQ_ROW_OF = {"capital": "r_capital", "partners": "r_partners",
              "reserve": "r_reserve",
              "retained": "r_dividends", "opening_susp": "r_opening_adj",
              "eq_other": "r_other"}


def _eq_class(node, by_id, rtype):
    """مكوّن حقوق الملكية للحساب — أو «pl» للإيراد والمصروف."""
    if rtype in ("revenue", "expense"):
        return "pl"
    if rtype != "equity":
        return None
    k = _classify(node, by_id)
    return k if k in ("capital", "partners", "retained",
                      "opening_susp", "reserve") else "eq_other"


def _eq_period(conn, d1, d2, dim, rows, by_id):
    from models import opening as _op
    eps = _EPS[dim]
    cls = {n["id"]: _eq_class(n, by_id, _root_of(n, by_id)["type"])
           for n in rows}
    rel = [a for a, c in cls.items() if c]
    if not rel:
        rel = [-1]
    pl_ids = [a for a, c in cls.items() if c == "pl"] or [-1]
    col_d, col_c = f"{dim}_debit", f"{dim}_credit"
    ph = ",".join("?" * len(rel))
    plh = ",".join("?" * len(pl_ids))
    op_cond, op_params = _op.sql(conn, "e")
    # قيود دفترية متعاكسة تُهمل: فتح السنة، وإغلاق أرصدة الميزانية
    # (قيد إقفالٍ لا يمسّ إيراداً ولا مصروفاً)
    ignore = ("(COALESCE(e.source_table,'')='year_open'"
              " OR (COALESCE(e.source_table,'')='year_close'"
              f" AND NOT EXISTS(SELECT 1 FROM journal_lines x WHERE"
              f" x.entry_id=e.id AND x.account_id IN ({plh}))))")
    base = (f"SELECT l.account_id aid, e.id eid, e.entry_date d,"
            f" COALESCE(e.source_table,'') src,"
            f" SUM(l.{col_d}-l.{col_c}) m, {op_cond} is_open"
            " FROM journal_lines l JOIN journal_entries e"
            " ON e.id=l.entry_id AND e.is_deleted=0"
            f" WHERE l.account_id IN ({ph}) AND NOT {ignore}")
    params_head = op_params + rel + pl_ids

    def comp_of(aid):
        c = cls.get(aid)
        return "retained" if c == "pl" else c

    keys = [k for k, _t in EQ_COLS]
    opening = {k: 0.0 for k in keys}
    closing = {k: 0.0 for k in keys}
    mov = {r: {k: 0.0 for k in keys} for r, _t in EQ_ROWS}
    for r in conn.execute(
            base + " AND e.entry_date<=? GROUP BY l.account_id, e.id",
            params_head + [d2]):
        m = r["m"] or 0.0
        comp = comp_of(r["aid"])
        amt = -m                              # دائنٌ = زيادة في الحقوق
        closing[comp] += amt
        if r["d"] < d1 or r["is_open"]:
            opening[comp] += amt              # الافتتاحي يُضمّ لأول الفترة
            continue
        c = cls.get(r["aid"])
        if r["src"] == "year_close":
            mov["transfer"][comp] += amt
        elif c == "pl":
            mov["profit"]["retained"] += amt
        else:
            mov[_EQ_ROW_OF[c]][comp] += amt
    rnd = 3 if dim == "gold" else 2

    def fin(dct):
        out = {k: round(v, rnd) for k, v in dct.items()}
        out["total"] = round(sum(out[k] for k in keys), rnd)
        return out

    res = {"opening": fin(opening), "closing": fin(closing),
           "rows": {r: fin(v) for r, v in mov.items()}}
    diff = {k: round(res["opening"][k]
                     + sum(res["rows"][r][k] for r, _t in EQ_ROWS)
                     - res["closing"][k], rnd) for k in keys + ["total"]}
    res["diff"] = diff
    res["balanced"] = all(abs(v) <= eps * 2 for v in diff.values())
    return res


def equity_changes(conn, date_from, date_to, compare=True, dim="cash"):
    """قائمة التغيرات في حقوق الملكية للفترة، وقبلها فترة المقارنة."""
    dim = "gold" if dim == "gold" else "cash"
    rows, by_id, _roots = _tree(conn)
    if compare is True:
        c1, c2 = _shift_year(date_from), _shift_year(date_to)
    elif compare:
        c1, c2 = compare
    else:
        c1 = c2 = ""
    out = {"date_from": date_from, "date_to": date_to, "dim": dim,
           "compare_from": c1, "compare_to": c2,
           "cur": _eq_period(conn, date_from, date_to, dim, rows, by_id)}
    if c1:
        out["cmp"] = _eq_period(conn, c1, c2, dim, rows, by_id)
    periods = [out["cur"]] + ([out["cmp"]] if c1 else [])
    eps = _EPS[dim]
    out["columns"] = [(k, t) for k, t in EQ_COLS
                      if any(abs(p[s][k]) > eps
                             for p in periods for s in ("opening", "closing"))
                      or any(abs(p["rows"][r][k]) > eps
                             for p in periods for r, _t in EQ_ROWS)]
    out["balanced"] = all(p["balanced"] for p in periods)
    return out


def eq_layout(eq):
    """صفوف القائمة: فترة المقارنة ثم الحالية — كلٌّ من رصيدٍ إلى رصيد."""
    eps = _EPS[eq["dim"]]
    keys = [k for k, _t in eq["columns"]] + ["total"]

    def block(p, d1, d2):
        out = [{"kind": "bal", "label": f"الرصيد كما في {_day_before(d1)}",
                "values": p["opening"]}]
        for r, t in EQ_ROWS:
            v = p["rows"][r]
            if r == "profit" or any(abs(v[k]) > eps for k in keys):
                out.append({"kind": "line", "label": t, "key": r,
                            "values": v})
            if r == "profit":
                out.append({"kind": "sub",
                            "label": "إجمالي الدخل الشامل للفترة",
                            "key": "tci", "values": v})
        out.append({"kind": "grand", "label": f"الرصيد كما في {d2}",
                    "values": p["closing"]})
        return out

    out = []
    if eq.get("cmp"):
        out.append({"kind": "sec", "label":
                    f"فترة المقارنة: من {eq['compare_from']} إلى "
                    f"{eq['compare_to']}"})
        out += block(eq["cmp"], eq["compare_from"], eq["compare_to"])
    out.append({"kind": "sec", "label":
                f"الفترة الحالية: من {eq['date_from']} إلى {eq['date_to']}"})
    out += block(eq["cur"], eq["date_from"], eq["date_to"])
    return out
