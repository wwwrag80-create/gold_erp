# -*- coding: utf-8 -*-
"""أعمار الديون (Aging) — أهم تقرير رقابي على أرصدة الجهات.

**ما يجيب عنه**: رصيد العميل رقمٌ واحد لا يقول شيئاً عن خطورته. مئة
ألف عمرها أسبوع شيء، ومئة ألف عمرها سنة شيء آخر تماماً. هذا التقرير
يوزّع الرصيد على فئات عمرية فيُظهر أيّ الديون تأخّرت وكم.

**الطريقة — الأقدم فالأقدم (FIFO)**: تُقرأ حركة الحساب بترتيبها
الزمني؛ كل مدين يفتح «دفعة» بتاريخها، وكل دائن يُسدّد أقدم الدفعات
المفتوحة أولاً. ما يبقى مفتوحاً في النهاية يُوزَّع على الفئات بحسب
عمره من تاريخ التقرير. وهذا هو المتّبع محاسبياً لأن العميل يسدّد
أقدم ما عليه ما لم يخصّص دفعته صراحةً.

**البعدان معاً**: الذهب والنقد يُعمَّران كلٌّ على حدة — فقد يكون
الوزن مسدَّداً والأجور متأخرة أو العكس.

**الرصيد الدائن** (الذي للعميل علينا) لا عمر له: يُعرض في عمود مستقل
لأنه ليس ديناً متأخراً بل أمانة عنده.
"""
import datetime as _dt

# حدود الفئات بالأيام — القياس المتعارف عليه
BUCKETS = ((0, 30), (31, 60), (61, 90), (91, None))
# تسميةٌ تُقرأ كما يقولها المحاسب: «أقل من ثلاثين» لا «٠–٣٠».
# الحدود الفاصلة لم تتغيّر — اللفظ وحده. مصدرٌ واحد للشاشة والورقة
# فلا يختلف ما يراه المستخدم عمّا يُسلَّم للعميل.
BUCKET_LABELS = ("أقل من 30", "أقل من 60", "أقل من 90", "أكثر من 90")

EPS_GOLD = 0.001
EPS_CASH = 0.01


def _days(a, b):
    """عدد الأيام بين تاريخين نصيّين (a أقدم)."""
    try:
        d1 = _dt.date.fromisoformat(str(a)[:10])
        d2 = _dt.date.fromisoformat(str(b)[:10])
        return (d2 - d1).days
    except Exception:
        return 0


def _age(lots, as_of, eps):
    """يوزّع الدفعات المفتوحة على الفئات العمرية."""
    out = [0.0, 0.0, 0.0, 0.0]
    for date, amount in lots:
        if amount <= eps:
            continue
        n = _days(date, as_of)
        for i, (lo, hi) in enumerate(BUCKETS):
            if n >= lo and (hi is None or n <= hi):
                out[i] += amount
                break
    return [round(x, 3) for x in out]


def _fifo(rows, dim, eps):
    """يطبّق «الأقدم فالأقدم» على بعدٍ واحد ويعيد الدفعات المفتوحة.

    `rows` مرتّبة زمنياً. يعيد (الدفعات المفتوحة، الرصيد الدائن).
    """
    lots = []               # [[التاريخ, المتبقي مديناً], …]
    credit = 0.0            # دائن زائد عن كل المدين (له علينا)
    for r in rows:
        debit = float(r[f"{dim}_debit"] or 0)
        cred = float(r[f"{dim}_credit"] or 0)
        if debit > eps:
            # الدائن الزائد السابق يُستهلك أولاً قبل فتح دفعة جديدة
            if credit > eps:
                used = min(credit, debit)
                credit -= used
                debit -= used
            if debit > eps:
                lots.append([r["entry_date"], debit])
        if cred > eps:
            left = cred
            for lot in lots:
                if left <= eps:
                    break
                used = min(lot[1], left)
                lot[1] -= used
                left -= used
            lots = [l for l in lots if l[1] > eps]
            if left > eps:
                credit += left
    return lots, round(credit, 3)


def _entity_rows(conn, entity_type=None, as_of=None):
    """حركة كل الجهات دفعةً واحدة — استعلام واحد لا استعلام لكل جهة.

    الاستعلام لكل جهة كان يعني مئات الاستعلامات على مصنع بمئة عميل،
    فيتجمّد التقرير قبل أن يظهر.
    """
    q = ("SELECT e.id eid, e.name, e.phone, e.entity_type,"
         " a.code, l.gold_debit, l.gold_credit, l.cash_debit,"
         " l.cash_credit, en.entry_date"
         " FROM entities e"
         " JOIN accounts a ON a.id=e.account_id"
         " JOIN journal_lines l ON l.account_id=e.account_id"
         " JOIN journal_entries en ON en.id=l.entry_id AND en.is_deleted=0"
         " WHERE e.is_deleted=0 AND e.is_internal=0")
    p = []
    if entity_type:
        q += " AND e.entity_type=?"
        p.append(entity_type)
    if as_of:
        q += " AND en.entry_date<=?"
        p.append(as_of)
    q += " ORDER BY e.id, en.entry_date, en.id, l.id"
    return conn.execute(q, p).fetchall()


def report(conn, entity_type="customer", as_of=None):
    """صفوف التقرير: لكل جهة رصيدها موزَّعاً على الفئات العمرية."""
    as_of = str(as_of or _dt.date.today().isoformat())[:10]
    rows = _entity_rows(conn, entity_type, as_of)
    by_entity = {}
    for r in rows:
        by_entity.setdefault(
            r["eid"], {"name": r["name"], "phone": r["phone"] or "",
                       "code": r["code"], "rows": []})["rows"].append(r)

    out = []
    for eid, info in by_entity.items():
        g_lots, g_credit = _fifo(info["rows"], "gold", EPS_GOLD)
        c_lots, c_credit = _fifo(info["rows"], "cash", EPS_CASH)
        g_buckets = _age(g_lots, as_of, EPS_GOLD)
        c_buckets = _age(c_lots, as_of, EPS_CASH)
        g_total = round(sum(g_buckets), 3)
        c_total = round(sum(c_buckets), 2)
        if (abs(g_total) < EPS_GOLD and abs(c_total) < EPS_CASH
                and abs(g_credit) < EPS_GOLD and abs(c_credit) < EPS_CASH):
            continue          # حساب متزن — لا شأن له بتقرير الأعمار
        oldest = min((l[0] for l in (g_lots + c_lots)), default="")
        out.append({
            "entity_id": eid, "name": info["name"], "phone": info["phone"],
            "code": info["code"],
            "gold": g_total, "gold_buckets": g_buckets,
            "gold_credit": round(-g_credit, 3) if g_credit else 0.0,
            "cash": round(c_total, 2), "cash_buckets":
                [round(x, 2) for x in c_buckets],
            "cash_credit": round(-c_credit, 2) if c_credit else 0.0,
            "oldest": oldest,
            "days": _days(oldest, as_of) if oldest else 0,
        })
    # الأخطر أولاً: الأقدم ديناً في رأس القائمة
    return sorted(out, key=lambda r: (-r["days"], -abs(r["cash"])))


def totals(rows):
    """إجماليات التقرير — لصف الإجمالي ولبطاقات الملخّص."""
    t = {"count": len(rows), "gold": 0.0, "cash": 0.0,
         "gold_buckets": [0.0] * 4, "cash_buckets": [0.0] * 4,
         "gold_credit": 0.0, "cash_credit": 0.0}
    for r in rows:
        t["gold"] += r["gold"]
        t["cash"] += r["cash"]
        t["gold_credit"] += r["gold_credit"]
        t["cash_credit"] += r["cash_credit"]
        for i in range(4):
            t["gold_buckets"][i] += r["gold_buckets"][i]
            t["cash_buckets"][i] += r["cash_buckets"][i]
    t["gold"] = round(t["gold"], 3)
    t["cash"] = round(t["cash"], 2)
    t["gold_credit"] = round(t["gold_credit"], 3)
    t["cash_credit"] = round(t["cash_credit"], 2)
    t["gold_buckets"] = [round(x, 3) for x in t["gold_buckets"]]
    t["cash_buckets"] = [round(x, 2) for x in t["cash_buckets"]]
    # نسبة كل فئة من الإجمالي النقدي — تُقرأ الخطورة في لمحة
    base = t["cash"] or 0.0
    t["cash_pct"] = [round(x / base * 100, 1) if base else 0.0
                     for x in t["cash_buckets"]]
    return t


def overdue(conn, days=90, entity_type="customer", as_of=None):
    """الجهات التي تجاوز أقدم دينها الحدّ — للتنبيه في لوحة التحكم."""
    return [r for r in report(conn, entity_type, as_of) if r["days"] >= days]
