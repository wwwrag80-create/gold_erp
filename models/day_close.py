# -*- coding: utf-8 -*-
"""الإغلاق اليومي — صفحة واحدة تُقفل بها اليوم.

**الحاجة**: آخر الدوام يُسأل سؤالان: ماذا جرى اليوم؟ وبماذا نُقفل؟
الإجابة اليوم تتطلب فتح خمس شاشات وجمع أرقامها يدوياً. وهذه الورقة
تجيبهما في صفحة: حركة اليوم مصنَّفة بنوعها، وأرصدة الخزائن والصناديق
بنهايته، ومن أدخل ماذا.

**ليست قيداً**: لا تُنشئ شيئاً ولا تُقفل حساباً — قراءة محضة. الإقفال
المحاسبي الحقيقي سنويٌّ وله شاشته. تسميتها «إغلاق يومي» بالمعنى
التشغيلي: مراجعة اليوم قبل إقفال الدرج.
"""
from services.accounting_engine import account_balance

# الأرصدة التي تُقفل عليها الورقة — المادية وذمم الجهات
KEY_ACCOUNTS = [
    ("1100", "خزينة التصنيع", "gold"),
    ("1200", "الذهب المشغول", "gold"),
    ("1310", "صندوق الكسر", "gold"),
    ("1350", "الصب والتصفية", "gold"),
    ("1400", "الصندوق النقدي", "cash"),
    ("1600", "ذمم العملاء", "both"),
    ("2000", "ذمم الموردين", "both"),
]


def _subtree_balance(conn, code, date_to):
    """رصيد الحساب **وفروعه** حتى نهاية اليوم.

    الحساب التجميعي (ذمم العملاء) رصيده مجموع فروعه لا حركته
    المباشرة — وقراءته وحده تعطي صفراً فيبدو أن لا ذمم على أحد.
    """
    from models.accounts import subtree_ids_by_code
    ids = subtree_ids_by_code(conn, code)
    if not ids:
        return None
    if len(ids) == 1:
        return account_balance(conn, ids[0], date_to=date_to)
    qs = ",".join("?" * len(ids))
    p = list(ids)
    q = ("SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
         " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
         " FROM journal_lines l"
         " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
         f" WHERE l.account_id IN ({qs})")
    if date_to:
        q += " AND e.entry_date<=?"
        p.append(date_to)
    r = conn.execute(q, p).fetchone()
    return round(r["g"] or 0, 3), round(r["c"] or 0, 2)


def summary(conn, date):
    """ملخّص يوم كامل: الحركة بأنواعها · الأرصدة الختامية · المستخدمون.

    `date` نص ISO. يعيد قاموساً جاهزاً للعرض والطباعة.
    """
    from models import journal
    date = str(date or "")[:10]
    docs = journal.day_book(conn, date, date)

    # ── الحركة مصنَّفة بنوع العملية ──
    kinds = {}
    for d in docs:
        k = kinds.setdefault(d["op"] or "غير محدد",
                             {"op": d["op"] or "غير محدد", "count": 0,
                              "gold": 0.0, "cash": 0.0})
        k["count"] += 1
        k["gold"] += float(d["gold"] or 0)
        k["cash"] += float(d["cash"] or 0)
    for k in kinds.values():
        k["gold"] = round(k["gold"], 3)
        k["cash"] = round(k["cash"], 2)
    kinds = sorted(kinds.values(), key=lambda x: -x["count"])

    # ── من أدخل ماذا — مسؤولية واضحة عن حركة اليوم ──
    users = {}
    for d in docs:
        u = users.setdefault(d["who"] or "—", {"user": d["who"] or "—",
                                               "count": 0})
        u["count"] += 1
    users = sorted(users.values(), key=lambda x: -x["count"])

    # ── الأرصدة الختامية ──
    balances = []
    for code, name, dim in KEY_ACCOUNTS:
        b = _subtree_balance(conn, code, date)
        if b is None:
            continue
        g, c = b
        balances.append({"code": code, "name": name, "dim": dim,
                         "gold": g, "cash": c})

    # ── حركة النقد داخلاً وخارجاً (الصندوق وحده) ──
    cash_in = cash_out = 0.0
    row = conn.execute(
        "SELECT COALESCE(SUM(l.cash_debit),0) i,"
        " COALESCE(SUM(l.cash_credit),0) o"
        " FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
        " JOIN accounts a ON a.id=l.account_id"
        " WHERE a.code='1400' AND e.entry_date=?", (date,)).fetchone()
    if row:
        cash_in, cash_out = round(row["i"] or 0, 2), round(row["o"] or 0, 2)

    return {
        "date": date,
        "docs": docs,
        "count": len(docs),
        "kinds": kinds,
        "users": users,
        "balances": balances,
        "gold_total": round(sum(float(d["gold"] or 0) for d in docs), 3),
        "cash_total": round(sum(float(d["cash"] or 0) for d in docs), 2),
        "cash_in": cash_in,
        "cash_out": cash_out,
        "cash_net": round(cash_in - cash_out, 2),
    }
