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
        "SELECT id, code, name, type, parent_id, is_postable"
        " FROM accounts ORDER BY code")]
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
    ("supplier_adv", "دفعات مقدّمة للموردين", "ca"),
    ("staff", "سلف وعهد الموظفين والعمال", "ca"),
    ("vat_asset", "ضريبة القيمة المضافة المستردّة (صافي)", "ca"),
    ("ca_other", "أصول متداولة أخرى", "ca"),
    # حقوق الملكية
    ("capital", "رأس المال", "eq"),
    ("partners", "جاري الشركاء", "eq"),
    ("retained", "الأرباح المبقاة (المرحّلة)", "eq"),
    ("opening_susp", "حساب تسوية الأرصدة الافتتاحية", "eq"),
    ("eq_other", "حقوق ملكية أخرى", "eq"),
    ("profit", "صافي ربح (خسارة) الفترة", "eq"),
    # المطلوبات غير المتداولة
    ("ncl_other", "مطلوبات غير متداولة", "ncl"),
    # المطلوبات المتداولة
    ("payables", "الذمم الدائنة — الموردون", "cl"),
    ("customer_adv", "دفعات مقدّمة وأمانات العملاء", "cl"),
    ("accruals", "مستحقات الموظفين والرواتب", "cl"),
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


def _balances(conn, as_of, dim):
    col_d, col_c = f"{dim}_debit", f"{dim}_credit"
    out = {}
    for r in conn.execute(
            f"SELECT l.account_id aid, COALESCE(SUM(l.{col_d}-l.{col_c}),0) b"
            " FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
            " WHERE e.entry_date<=? GROUP BY l.account_id", (as_of,)):
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
        elif kind == "ppe_dep":
            # دائنٌ بطبيعته: يبقى سالباً في جانب الأصول فيُطرح من التكلفة
            add("ppe_dep", b, node)
        elif kind in ("ppe_cost", "cash", "inventory", "staff"):
            add(kind, b, node)
        elif kind == "accruals":
            add("accruals", -b, node)
        elif kind in ("capital", "partners", "retained", "opening_susp"):
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
