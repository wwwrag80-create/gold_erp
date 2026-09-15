# -*- coding: utf-8 -*-
"""الميزانية العمومية الشجرية.

**العلة التي تعالجها**: الميزانية السابقة كانت تُبنى من **قائمة أكواد
ثابتة** مكتوبة في الكود. فأي حساب يضيفه المستخدم — كـ«مسترجع من
التصفية» — لا يُدرج في أي مجموعة، فيختفي رصيده من الميزانية ويظهر
عجزٌ وهمي بمقداره.

**الحل**: تُبنى الميزانية من **شجرة الحسابات نفسها**. كل حساب في
الدليل يظهر تحت جذره، مهما أُضيف مستقبلاً — فيستحيل أن يختل التوازن
بسبب حساب منسيّ.

**المستويات**: كما في أنظمة ERP، يختار المستخدم عمق العرض:
    المستوى 1 → الجذور فقط (الأصول · الخصوم · حقوق الملكية)
    المستوى 2 → المجموعات الرئيسية
    المستوى 3 → المجموعات الفرعية
    المستوى 4+ → الحسابات التفصيلية بكل فروعها
"""

# جذور الشجرة وأنواعها المحاسبية
ROOTS = [
    ("1000", "الأصول", "asset"),
    ("2000", "الخصوم والالتزامات", "liability"),
    ("3000", "حقوق الملكية", "equity"),
    ("4000", "الإيرادات", "revenue"),
    ("5000", "المصروفات", "expense"),
]


def _account_tree(conn):
    """كل الحسابات مفهرسة بالمعرّف مع أبنائها."""
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
    return rows, by_id


def _own_balances(conn, date_to, date_from=None):
    """رصيد **حركة** كل حساب على حدة (بلا أبنائه)."""
    p = []
    clause = ""
    if date_from:
        clause += " AND e.entry_date>=?"
        p.append(date_from)
    if date_to:
        clause += " AND e.entry_date<=?"
        p.append(date_to)
    out = {}
    for r in conn.execute(
            "SELECT l.account_id aid,"
            " ROUND(COALESCE(SUM(l.gold_debit-l.gold_credit),0),3) g,"
            " ROUND(COALESCE(SUM(l.cash_debit-l.cash_credit),0),2) c"
            " FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0" + clause + " GROUP BY l.account_id", p):
        out[r["aid"]] = (r["g"] or 0.0, r["c"] or 0.0)
    return out


def _roll_up(node, own):
    """يجمع رصيد الحساب مع كل فروعه — الرصيد المجمّع."""
    g, c = own.get(node["id"], (0.0, 0.0))
    for ch in node["children"]:
        cg, cc = _roll_up(ch, own)
        g += cg
        c += cc
    node["gold"] = round(g, 3)
    node["cash"] = round(c, 2)
    return node["gold"], node["cash"]


def _flatten(node, level, max_level, out, hide_zero=True):
    """يُسطّح الشجرة حتى المستوى المطلوب."""
    if hide_zero and abs(node["gold"]) < 0.001 \
            and abs(node["cash"]) < 0.01:
        return
    out.append({
        "level": level, "code": node["code"], "name": node["name"],
        "gold": node["gold"], "cash": node["cash"],
        "is_leaf": not node["children"],
        "postable": bool(node["is_postable"]),
    })
    if level >= max_level:
        return
    for ch in node["children"]:
        _flatten(ch, level + 1, max_level, out, hide_zero)


def balance_sheet_tree(conn, date_to=None, date_from=None, max_level=3,
                       hide_zero=True):
    """الميزانية العمومية الشجرية — تشمل **كل** حسابات الدليل.

    تعيد الأقسام الخمسة بصفوفها المتدرّجة، مع فحص التوازن:

        الأصول = الخصوم + حقوق الملكية + (الإيرادات − المصروفات)
    """
    dt = date_to or "2999-12-31"
    rows, by_id = _account_tree(conn)
    own = _own_balances(conn, dt, date_from)

    by_code = {r["code"]: r for r in rows}
    sections = []
    totals = {}
    for code, label, kind in ROOTS:
        node = by_code.get(code)
        if node is None:
            totals[kind] = (0.0, 0.0)
            sections.append({"code": code, "title": label, "kind": kind,
                             "gold": 0.0, "cash": 0.0, "rows": []})
            continue
        g, c = _roll_up(node, own)
        flat = []
        _flatten(node, 1, max_level, flat, hide_zero)
        totals[kind] = (g, c)
        sections.append({"code": code, "title": label, "kind": kind,
                         "gold": g, "cash": c, "rows": flat})

    # حسابات خارج الجذور الخمسة (كالجسور) — تُدرج ضمن الأصول
    orphan_g = orphan_c = 0.0
    orphans = []
    root_ids = {by_code[c]["id"] for c, _l, _k in ROOTS if c in by_code}
    for r in rows:
        if r["parent_id"] is not None or r["id"] in root_ids:
            continue
        g, c = _roll_up(r, own)
        if abs(g) < 0.001 and abs(c) < 0.01:
            continue
        orphan_g += g
        orphan_c += c
        flat = []
        _flatten(r, 1, max_level, flat, hide_zero)
        orphans.extend(flat)
    if orphans:
        sections.append({"code": "—", "title": "حسابات أخرى (جسور وتسويات)",
                         "kind": "asset", "gold": round(orphan_g, 3),
                         "cash": round(orphan_c, 2), "rows": orphans})

    ag, ac = totals.get("asset", (0, 0))
    ag += orphan_g
    ac += orphan_c
    lg, lc = totals.get("liability", (0, 0))
    eg, ec = totals.get("equity", (0, 0))
    rg, rc = totals.get("revenue", (0, 0))
    xg, xc = totals.get("expense", (0, 0))

    # الإيرادات والمصروفات طبيعتهما دائنة/مدينة، فصافي النشاط:
    #   النتيجة = (−الإيرادات) − (المصروفات)  بإشارة المدين
    net_g = round(-rg - xg, 3)
    net_c = round(-rc - xc, 2)

    # طرف الالتزامات وحقوق الملكية بإشارة موجبة للعرض
    right_g = round(-(lg + eg) + net_g, 3)
    right_c = round(-(lc + ec) + net_c, 2)

    diff_g = round(ag - right_g, 3)
    diff_c = round(ac - right_c, 2)

    return {
        "sections": sections,
        "assets": (round(ag, 3), round(ac, 2)),
        "liabilities": (round(-lg, 3), round(-lc, 2)),
        "equity": (round(-eg, 3), round(-ec, 2)),
        "revenue": (round(-rg, 3), round(-rc, 2)),
        "expense": (round(xg, 3), round(xc, 2)),
        "net_result": (round(-net_g, 3), round(-net_c, 2)),
        "right_side": (right_g, right_c),
        "diff_gold": diff_g, "diff_cash": diff_c,
        "balanced_gold": abs(diff_g) < 0.011,
        "balanced_cash": abs(diff_c) < 0.011,
        "max_level": max_level,
    }


def max_depth(conn):
    """أعمق مستوى في شجرة الحسابات — لضبط حدود الاختيار."""
    rows, by_id = _account_tree(conn)
    depth = 1
    for r in rows:
        d, cur = 1, r
        seen = 0
        while cur["parent_id"] is not None and seen < 12:
            cur = by_id.get(cur["parent_id"])
            if cur is None:
                break
            d += 1
            seen += 1
        depth = max(depth, d)
    return depth
