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


