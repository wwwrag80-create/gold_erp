# -*- coding: utf-8 -*-
"""فحص سلامة دليل الحسابات — ما يسأل عنه المراجع قبل أن يعتمد الأرقام.

يُعيد قائمة ملاحظات (الخطورة، البند، التفصيل، الأكواد):

* **خطأ**: يُفسد القوائم — قيدٌ غير متوازن، حركةٌ على حساب تجميعي
  مغلق، حساب نوعه يخالف جذره، حسابٌ نظامي مفقود.
* **تنبيه**: يستوقف المراجع — رصيدٌ على خلاف طبيعة الحساب (صندوق دائن،
  مجمّع إهلاك مدين…)، حسابٌ وسيط لم يُصفَّر، حسابٌ مجمَّد برصيد، حساب
  يُصنَّف في «أخرى» بالقوائم.
* **ملاحظة**: تنظيمية — أسماء مكرّرة تحت الأب نفسه، مجموعةٌ فارغة.

قراءةٌ محضة لا تعدّل شيئاً.
"""
from models import statements as st

ERROR, WARN, INFO = "خطأ", "تنبيه", "ملاحظة"

# حساباتٌ تعتمد عليها القيود الآلية والقوائم — غيابها يكسر الترحيل
REQUIRED = ("1400", "1500", "1100", "1200", "1600", "1680", "1700", "1790",
            "1900", "1980", "2100", "2280", "2300", "2400", "2600", "3110",
            "3120", "3200", "3900", "4110", "4120", "4910", "4920", "5150",
            "5860", "5870", "5880", "5950", "6100")
# حساباتٌ وسيطة/تسوية يجب أن تُصفَّر قبل الاعتماد
CLEARING = {"3900": "الأرصدة الافتتاحية للتسوية",
            "2900": "تسويات مباشرة على أرصدة الجهات",
            "6100": "مركز التسكير (ذهب ↔ نقد)"}
EPS = 0.005


def _bal(conn, dim="cash"):
    return st._balances(conn, "9999-12-31", dim)


def audit(conn):
    out = []
    rows, by_id, _roots = st._tree(conn)
    by_code = {r["code"]: r for r in rows}
    kids = {}
    for r in rows:
        if r["parent_id"]:
            kids.setdefault(r["parent_id"], []).append(r)

    # ── 1) القيود غير المتوازنة (أخطر ما يُرى)
    bad = conn.execute(
        "SELECT e.id, e.doc_no, e.entry_date,"
        " ROUND(SUM(l.cash_debit-l.cash_credit),2) c,"
        " ROUND(SUM(l.gold_debit-l.gold_credit),3) g"
        " FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id"
        " WHERE e.is_deleted=0 GROUP BY e.id"
        " HAVING ABS(c) >= 0.01 OR ABS(g) >= 0.001 LIMIT 50").fetchall()
    if bad:
        out.append((ERROR, "قيود غير متوازنة (مدين ≠ دائن)",
                    "، ".join(f"{b['doc_no'] or b['id']} ({b['entry_date']})"
                              for b in bad[:10]), []))

    # ── 2) الحسابات النظامية
    miss = [c for c in REQUIRED if c not in by_code]
    if miss:
        out.append((ERROR, "حسابات نظامية مفقودة من الشجرة",
                    "القيود الآلية تُرحَّل عليها — أعد تشغيل البرنامج"
                    " لتُضاف", miss))

    # ── 3) نوع الحساب يخالف نوع جذره
    wrong = [r["code"] for r in rows
             if r["type"] != st._root_of(r, by_id)["type"]]
    if wrong:
        out.append((ERROR, "حسابات نوعها يخالف نوع جذرها",
                    "حسابٌ تحت الأصول بنوع مصروف مثلاً يُقرأ في غير قائمته",
                    wrong))

    # ── 4) حركة على حسابات تجميعية
    moved = {r["account_id"] for r in conn.execute(
        "SELECT DISTINCT l.account_id FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0")}
    from database.seed import KEEP_POSTABLE_GROUPS
    from models.coa import group_own_balance
    grp_moved = []
    for r in rows:
        if r["id"] in kids and r["id"] in moved \
                and r["code"] not in KEEP_POSTABLE_GROUPS:
            c, g = group_own_balance(conn, r["id"])
            if abs(c) >= 0.005 or abs(g) >= 0.0005:
                grp_moved.append(r["code"])
    if grp_moved:
        out.append((WARN, "حسابات تجميعية عليها رصيدٌ مباشر",
                    "رصيد المجموعة يختلط بفروعها — من «دليل الحسابات»:"
                    " زر الفأرة الأيمن على المجموعة ← «نقل رصيدها إلى"
                    " فرع»", grp_moved))
    closed = [r["code"] for r in rows if not r["is_postable"]
              and r["id"] in moved and r["id"] not in kids]
    if closed:
        out.append((ERROR, "حسابات مغلقة للترحيل وعليها حركة",
                    "", closed))

    # ── 5) الطبيعة: الحسابات المقابلة
    from database.seed import CONTRA_NATURE
    nat = [c for c, n in CONTRA_NATURE.items()
           if c in by_code and by_code[c].get("nature") not in (None, n)]
    if nat:
        out.append((WARN, "طبيعة حسابات مقابلة غير صحيحة", "", nat))

    # ── 6) أرصدةٌ على خلاف طبيعتها
    cash = _bal(conn, "cash")
    gold = _bal(conn, "gold")
    abnormal = []
    for r in rows:
        if r["id"] in kids:
            continue
        b = cash.get(r["id"], 0.0)
        g = gold.get(r["id"], 0.0)
        kind = st._classify(r, by_id)
        if kind == "cash" and b < -EPS:
            abnormal.append(f"{r['code']} {r['name']}: رصيد نقدي دائن"
                            f" {-b:,.2f}")
        elif kind == "inventory" and g < -0.0005:
            abnormal.append(f"{r['code']} {r['name']}: وزن سالب {g:,.3f}")
        elif kind in ("ppe_dep", "ecl") and b > EPS:
            abnormal.append(f"{r['code']} {r['name']}: رصيد مدين {b:,.2f}"
                            " لحساب مقابل")
        elif kind in ("zakat", "eosb", "accrued", "loans_st", "loans_lt") \
                and b > EPS:
            abnormal.append(f"{r['code']} {r['name']}: رصيد مدين {b:,.2f}"
                            " لالتزام")
    if abnormal:
        out.append((WARN, "أرصدة على خلاف طبيعة الحساب",
                    " · ".join(abnormal[:12])
                    + (f" … و{len(abnormal) - 12} غيرها"
                       if len(abnormal) > 12 else ""), []))

    # ── 7) حسابات وسيطة لم تُصفَّر
    for code, name in CLEARING.items():
        r = by_code.get(code)
        if not r:
            continue
        ids = [r["id"]] + [k["id"] for k in kids.get(r["id"], [])]
        b = sum(cash.get(i, 0.0) for i in ids)
        g = sum(gold.get(i, 0.0) for i in ids)
        if abs(b) >= 0.01 or abs(g) >= 0.001:
            out.append((WARN, f"حساب وسيط برصيد: {code} {name}",
                        f"نقد {b:,.2f} · ذهب {g:,.3f} — يُصفَّر بقيد تسوية"
                        " قبل اعتماد القوائم", [code]))

    # ── 8) حسابات مجمَّدة برصيد
    frozen = [r["code"] for r in rows if not r.get("is_active", 1)
              and (abs(cash.get(r["id"], 0.0)) >= 0.01
                   or abs(gold.get(r["id"], 0.0)) >= 0.001)]
    if frozen:
        out.append((WARN, "حسابات مجمَّدة وعليها رصيد",
                    "تظهر في القوائم ولا تظهر في قوائم الإدخال", frozen))

    # ── 9) ما يقع في بنود «أخرى» من القوائم
    other = []
    for r in rows:
        if r["id"] in kids or r["type"] not in ("asset", "liability",
                                                "equity"):
            continue
        if abs(cash.get(r["id"], 0.0)) < 0.01:
            continue
        if st._classify(r, by_id) is None:
            other.append(r["code"])
    if other:
        out.append((INFO, "حسابات تُعرض في بند «أخرى» بالمركز المالي",
                    "ضعها تحت مجموعتها الصحيحة ليظهر بندها باسمه", other))

    # ── 10) تنظيم
    seen, dup = {}, []
    for r in rows:
        key = (r["parent_id"], r["name"].strip())
        if key in seen:
            dup.append(r["code"])
        seen[key] = r["code"]
    if dup:
        out.append((INFO, "أسماء مكرّرة تحت الأب نفسه", "", dup))
    empty = [r["code"] for r in rows if not r["is_postable"]
             and r["id"] not in kids and r["id"] not in moved
             and r["code"] not in ("1360",)]
    if empty:
        out.append((INFO, "مجموعات بلا فروع", "لا ضرر — للتنظيم فقط", empty))
    return out


def summary(conn):
    items = audit(conn)
    errors = sum(1 for s, *_ in items if s == ERROR)
    warns = sum(1 for s, *_ in items if s == WARN)
    return {"items": items, "errors": errors, "warnings": warns,
            "ok": errors == 0}
