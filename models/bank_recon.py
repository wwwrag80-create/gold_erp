# -*- coding: utf-8 -*-
"""مطابقة كشف البنك — بين ما في الدفتر وما في كشف المصرف.

**الفجوة التي تسدّها**: في النظام حسابُ بنكٍ (١٥٠٠) تُقيَّد عليه
السندات، ولم يكن فيه ما يقابل رصيده بكشف المصرف. فكان المحاسب يطابق
بورقةٍ وقلم خارج النظام — والورقة لا تُدقَّق ولا تُؤرشَف ولا يعرف
خَلَفه ما فعله.

**المعادلة** التي تُبنى عليها الشاشة، وهي معادلة المطابقة المعروفة:

    رصيد الدفتر
      − حركاتٌ في الدفتر لم تظهر في الكشف بعد (شيكاتٌ لم تُصرَف)
      + حركاتٌ في الدفتر لم تظهر في الكشف بعد (إيداعاتٌ لم تُقيَّد)
      = الرصيد المتوقَّع في الكشف

فإن خالف الرصيد المعلن في الكشف فالفرق خطأٌ يُبحث عنه: قيدٌ ناقص، أو
مبلغٌ مقلوب، أو رسمٌ مصرفيٌّ لم يُقيَّد.

**ما يُخزَّن**: علامة المطابقة وحدها — أي سطرٍ في الدفتر رآه المحاسب
في الكشف، ومتى، ومَن. لا تُنشَأ قيود ولا تُعدَّل أرقام: المطابقة
**قراءةٌ وشهادة**، وما ينقص الدفتر يُقيَّد في القيود اليومية كأي قيد،
فيبقى لكل رقمٍ مستنده.
"""

# جذر النقدية وشبه النقدية في شجرة الحسابات. المطابقة تخصّ ما تحته
# وحده: الصندوق والبنك وما يُضاف من فروع. ولا يصحّ أخذ كل حسابٍ
# `balance_type='cash'` — فالسيارات وأجهزة الكمبيوتر كذلك، ولا يُطابَق
# كشفُ مصرفٍ بسيارة.
CASH_ROOT = "1010"


def bank_accounts(conn):
    """حسابات النقدية والبنوك القابلة للترحيل — فروع ١٠١٠ مهما عمقت."""
    rows = list(conn.execute(
        "WITH RECURSIVE tree(id) AS ("
        "   SELECT id FROM accounts WHERE code=?"
        "   UNION ALL"
        "   SELECT a.id FROM accounts a JOIN tree t ON a.parent_id=t.id)"
        " SELECT a.id, a.code, a.name FROM accounts a JOIN tree t ON t.id=a.id"
        " WHERE a.is_active=1 AND a.is_postable=1"
        " ORDER BY a.code", (CASH_ROOT,)))
    if rows:
        return [dict(r) for r in rows]
    # شجرةٌ غير قياسية (قاعدةٌ نُقلت أو عُدّلت يدوياً): يُكتفى بالنقدي
    return [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM accounts"
        " WHERE is_active=1 AND is_postable=1 AND type='asset'"
        "   AND balance_type='cash'"
        " ORDER BY code")]


def opening_balance(conn, account_id, date_from):
    """رصيد الحساب قبل بداية الفترة — أساس كشف المطابقة."""
    r = conn.execute(
        "SELECT COALESCE(SUM(l.cash_debit - l.cash_credit),0) b"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE l.account_id=? AND e.is_deleted=0 AND e.entry_date<?",
        (account_id, date_from)).fetchone()
    return float(r["b"] or 0)


def movements(conn, account_id, date_from, date_to):
    """حركات الحساب في الفترة، ومع كل حركةٍ حالةُ مطابقتها.

    يُقرأ من سطور القيود لا من جدول السندات: فكل ما يمسّ البنك يظهر
    هنا مهما كان مصدره — سندٌ أو فاتورةٌ أو قيدٌ يدوي.
    """
    rows = []
    for r in conn.execute(
            "SELECT l.id line_id, e.id entry_id, e.entry_date d,"
            "       e.doc_no, e.description, e.source_table, e.source_id,"
            "       l.cash_debit dr, l.cash_credit cr, l.line_desc,"
            "       m.matched_at, m.matched_by, m.statement_ref"
            "  FROM journal_lines l"
            "  JOIN journal_entries e ON e.id=l.entry_id"
            "  LEFT JOIN bank_recon_marks m ON m.line_id=l.id"
            " WHERE l.account_id=? AND e.is_deleted=0"
            "   AND e.entry_date>=? AND e.entry_date<=?"
            "   AND (l.cash_debit<>0 OR l.cash_credit<>0)"
            " ORDER BY e.entry_date, e.id, l.id",
            (account_id, date_from, date_to)):
        rows.append({
            "line_id": r["line_id"], "entry_id": r["entry_id"],
            "date": r["d"], "doc_no": r["doc_no"] or f"#{r['entry_id']}",
            "desc": (r["line_desc"] or r["description"] or "").strip(),
            "src": r["source_table"], "sid": r["source_id"],
            "debit": float(r["dr"] or 0), "credit": float(r["cr"] or 0),
            "matched": bool(r["matched_at"]),
            "matched_at": r["matched_at"], "matched_by": r["matched_by"],
            "ref": r["statement_ref"] or "",
        })
    return rows


def set_matched(conn, line_ids, matched, username, ref=""):
    """يضع علامة المطابقة أو يرفعها عن سطورٍ بعينها.

    علامةٌ لا قيد: لا تُغيَّر أرقام الدفتر بالمطابقة أبداً. وما ينقص
    الدفتر (رسمٌ مصرفي، فائدة) يُقيَّد قيداً يومياً له مستنده.
    """
    ids = [int(x) for x in line_ids]
    if not ids:
        return 0
    if matched:
        conn.executemany(
            "INSERT INTO bank_recon_marks(line_id, matched_at, matched_by,"
            "                             statement_ref)"
            " VALUES(?, datetime('now','localtime'), ?, ?)"
            " ON CONFLICT(line_id) DO UPDATE SET"
            "   matched_at=excluded.matched_at,"
            "   matched_by=excluded.matched_by,"
            "   statement_ref=excluded.statement_ref",
            [(i, username, ref) for i in ids])
    else:
        conn.executemany("DELETE FROM bank_recon_marks WHERE line_id=?",
                         [(i,) for i in ids])
    return len(ids)


def summary(conn, account_id, date_from, date_to, statement_balance=None):
    """كشف المطابقة: من رصيد الدفتر إلى رصيد البنك، والفرق بينهما."""
    rows = movements(conn, account_id, date_from, date_to)
    opening = opening_balance(conn, account_id, date_from)
    book = opening + sum(r["debit"] - r["credit"] for r in rows)

    # غير المطابَق = ما في الدفتر ولم يظهر في الكشف بعد
    un_in = sum(r["debit"] for r in rows if not r["matched"])
    un_out = sum(r["credit"] for r in rows if not r["matched"])
    expected = book - un_in + un_out

    out = {
        "opening": opening,
        "book": book,
        "rows": len(rows),
        "matched_rows": sum(1 for r in rows if r["matched"]),
        "unmatched_rows": sum(1 for r in rows if not r["matched"]),
        "unmatched_in": un_in,          # إيداعات لم تظهر في الكشف
        "unmatched_out": un_out,        # شيكات لم تُصرَف
        "expected": expected,
        "statement": None,
        "difference": None,
    }
    if statement_balance is not None:
        out["statement"] = float(statement_balance)
        # التقريب لفلسين: فرقٌ دون الفلس ليس فرقاً، وإظهاره يُقلق بلا داعٍ
        out["difference"] = round(float(statement_balance) - expected, 2)
    return out
