# -*- coding: utf-8 -*-
"""ما هو «الرصيد الافتتاحي»؟ — قاعدةٌ واحدة تقرؤها كل الشاشات.

**الخلل الذي عولج**: ثلاث شاشاتٍ كانت تجيب عن هذا السؤال بثلاث
إجابات:
  • لوحة العملاء: بمصدر القيد وحده (بطاقة الجهة، قيد الافتتاح…) —
    فالقيد اليومي الذي أدخل به المصنع رصيد عميله مقابل «الأرصدة
    الافتتاحية» كان يقع في «حركات أخرى» لا في «رصيد سابق».
  • تحليل الحركة وملف الجهة: **كلُّ** قيدٍ يدويّ افتتاحيٌّ — ولو كان
    تسويةً على المصروفات جرت أمس.
  • تحليل المبيعات: ما في بيانه «رصيد افتتاحي» فقط.
فيقرأ المستخدم للعميل نفسه ثلاثة أرصدةٍ افتتاحية.

**القاعدة الآن** — القيد افتتاحيٌّ إذا:
  1. نشأ من مصدرٍ افتتاحي: بطاقة الجهة، شاشة أرصدة أول المدة، قيد
     الافتتاح، فتح السنة؛ أو
  2. **كان طرفُه المقابل حسابَ الأرصدة الافتتاحية** (3900 وما تحته،
     أو أي حساب حقوق ملكيةٍ في اسمه «افتتاح») — وهذا ما يجعل القيد
     اليومي الذي يُدخل رصيد العميل رصيداً سابقاً، كما هو محاسبياً:
     مبيعاتٌ سبقت النظام بقيت عنده؛ أو
  3. في بيانه «رصيد افتتاحي» (قيودٌ قديمة قبل هذه القاعدة).

قراءةٌ محضة.
"""

OPENING_SOURCES = ("entities", "opening", "opening_entry", "year_open")
OPENING_CODE = "3900"            # الأرصدة الافتتاحية للتسوية
OPENING_TEXT = "رصيد افتتاحي"


def opening_account_ids(conn):
    """حسابات «الأرصدة الافتتاحية»: 3900 وشجرته، وحسابات حقوق الملكية
    التي يقول اسمها إنها افتتاحية (يُنشئها المستخدم أحياناً باسمه)."""
    ids = set()
    try:
        r = conn.execute("SELECT id FROM accounts WHERE code=?",
                         (OPENING_CODE,)).fetchone()
        if r:
            from models.accounts import subtree_ids
            ids.update(subtree_ids(conn, r["id"]) or [r["id"]])
    except Exception:
        pass
    try:
        for r in conn.execute(
                "SELECT id FROM accounts WHERE type='equity'"
                " AND name LIKE '%افتتاح%'"):
            ids.add(r["id"])
    except Exception:
        pass
    return sorted(ids)


def sql(conn, alias="e"):
    """شرط SQL «القيد افتتاحي» على قيدٍ اسمه `alias`، ومعاملاته."""
    acc = opening_account_ids(conn)
    parts = [f"{alias}.source_table IN ({','.join('?' * len(OPENING_SOURCES))})",
             f"{alias}.description LIKE ?"]
    params = list(OPENING_SOURCES) + [f"%{OPENING_TEXT}%"]
    if acc:
        parts.append(
            f"EXISTS(SELECT 1 FROM journal_lines ol WHERE ol.entry_id={alias}.id"
            f" AND ol.account_id IN ({','.join('?' * len(acc))}))")
        params += acc
    return "(" + " OR ".join(parts) + ")", params


def entry_ids(conn, ids):
    """أيُّ القيود المعطاة افتتاحي — لمن يقرأ كشفاً سطراً سطراً."""
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return set()
    cond, params = sql(conn, "e")
    out = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in conn.execute(
                f"SELECT e.id FROM journal_entries e WHERE e.id IN"
                f" ({','.join('?' * len(chunk))}) AND e.is_deleted=0"
                f" AND {cond}",
                chunk + params):
            out.add(r["id"])
    return out
