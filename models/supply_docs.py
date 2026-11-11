# -*- coding: utf-8 -*-
"""اسمٌ ورقمٌ خاص لفواتير الوارد (5.3.2) — «فاتورة وارد IN-00012».

كفاتورة البيع (S-…) والمرتجع (R-…): لكل دفعة توريدٍ رقمٌ يُعرف به في
الطباعة وحركة الطقم والقوائم. يُحفظ في جدولٍ مستقل مربوطٍ بقيد الدفعة —
فلا يُمسّ «المرجع» الذي يكتبه المستخدم (عمود المستند) ولا بيان القيود
القديمة (بصمتها في سلسلة السلامة).
"""
PREFIX = "IN"
NAME = "فاتورة وارد"


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS supply_docs("
        " entry_id INTEGER PRIMARY KEY REFERENCES journal_entries(id),"
        " supply_no TEXT NOT NULL UNIQUE)")


def new_no(conn):
    """الرقم التالي — يُحجز في معاملة الترحيل نفسها."""
    from models import numbering
    ensure_schema(conn)
    return numbering.next_no(conn, PREFIX)


def bind(conn, entry_id, supply_no):
    ensure_schema(conn)
    conn.execute("INSERT OR REPLACE INTO supply_docs(entry_id, supply_no)"
                 " VALUES(?,?)", (int(entry_id), supply_no))


def number_of(conn, entry_id):
    if not entry_id:
        return None
    try:
        r = conn.execute("SELECT supply_no FROM supply_docs WHERE entry_id=?",
                         (int(entry_id),)).fetchone()
    except Exception:
        return None
    return r[0] if r else None


def backfill(conn):
    """الدفعات القائمة قبل الميزة تأخذ أرقامها بترتيب تواريخها — مرةً
    واحدة. لا يُغيَّر بيان قيدٍ قديم."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT e.id FROM journal_entries e"
        " WHERE e.is_deleted=0 AND e.source_table='work_orders'"
        " AND NOT EXISTS (SELECT 1 FROM supply_docs s WHERE s.entry_id=e.id)"
        " AND (EXISTS (SELECT 1 FROM wo_batch_lines b WHERE b.entry_id=e.id)"
        "      OR EXISTS (SELECT 1 FROM work_orders w WHERE w.entry_id=e.id))"
        " ORDER BY e.entry_date, e.id").fetchall()
    for r in rows:
        bind(conn, r[0], new_no(conn))
    return len(rows)


def batch_info(conn, entry_id):
    """{"no", "ref", "date", "count", "label"} لدفعة التوريد — أو None."""
    if not entry_id:
        return None
    e = conn.execute("SELECT id, entry_date, doc_no FROM journal_entries"
                     " WHERE id=?", (int(entry_id),)).fetchone()
    if not e:
        return None
    try:
        n = conn.execute("SELECT COUNT(*) FROM wo_batch_lines WHERE entry_id=?",
                         (int(entry_id),)).fetchone()[0]
    except Exception:
        n = 0
    if not n:
        n = conn.execute("SELECT COUNT(*) FROM work_orders WHERE entry_id=?",
                         (int(entry_id),)).fetchone()[0]
    no = number_of(conn, entry_id)
    ref = (e["doc_no"] or "").strip()
    if ref and ref == no:
        ref = ""
    parts = [f"{NAME} {no}" if no else f"دفعة القيد #{e['id']}"]
    parts.append(f"دفعة {e['entry_date']} ({n} طقم)")
    if ref:
        parts.append(f"مرجع {ref}")
    return {"no": no, "ref": ref, "date": e["entry_date"], "count": n,
            "label": " · ".join(parts)}
