# -*- coding: utf-8 -*-
"""شجرة الحسابات ومراكز التكلفة — دوال استعلام مشتركة."""


def acc_id(conn, code: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
    if not row:
        raise ValueError(f"حساب غير موجود في الشجرة: {code}")
    return row["id"]


def account_name(conn, account_id: int) -> str:
    row = conn.execute("SELECT code,name FROM accounts WHERE id=?", (account_id,)).fetchone()
    return f"{row['code']} — {row['name']}" if row else str(account_id)


def list_postable(conn):
    """الحسابات المتاحة لحقول الإدخال في كل الشاشات: تقرأ مباشرة من
    شجرة الحسابات — فرعية تقبل الحركة (is_transactional) ونشطة غير
    مجمَّدة (is_active). أي حساب يُضاف في الشجرة يظهر هنا فوراً."""
    return conn.execute(
        "SELECT id, code, name, balance_type FROM accounts"
        " WHERE is_postable=1 AND is_active=1 ORDER BY code").fetchall()


def list_tree(conn):
    return conn.execute(
        "SELECT id, code, name, type, parent_id, is_postable FROM accounts ORDER BY code").fetchall()


def subtree_ids(conn, root_id):
    """معرّفات الحساب وكل فروعه وأحفاده — باستعلام **واحد**.

    كان كل موضع يمشي الشجرة باستعلام لكل عقدة. الحساب التجميعي
    للعملاء وحده قد يضمّ مئات الفروع، فتُنفَّذ مئات الاستعلامات في كل
    تحديث للوحة التحكم — وهذا ما يجعل النظام يبطؤ مع نموّ عدد
    العملاء لا مع حجم العمل. استعلام CTE تكراري واحد يكفي.

    `LIMIT 5000` و`depth` حارسان: لو وُجدت حلقة في الشجرة (حساب أبوه
    أحد أحفاده) لدار الاستعلام بلا نهاية وتجمّد النظام.
    """
    rows = conn.execute(
        "WITH RECURSIVE sub(id, depth) AS ("
        "  SELECT id, 0 FROM accounts WHERE id=?"
        "  UNION"
        "  SELECT a.id, s.depth+1 FROM accounts a"
        "   JOIN sub s ON a.parent_id=s.id WHERE s.depth < 20"
        ") SELECT id FROM sub LIMIT 5000", (root_id,)).fetchall()
    return [r["id"] for r in rows]


def subtree_ids_by_code(conn, code):
    """كسابقتها لكن بكود الحساب. تعيد [] إن لم يوجد."""
    row = conn.execute("SELECT id FROM accounts WHERE code=?",
                       (code,)).fetchone()
    return subtree_ids(conn, row["id"]) if row else []


