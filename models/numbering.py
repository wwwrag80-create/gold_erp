# -*- coding: utf-8 -*-
"""ترقيم المستندات — لكل نوعٍ حرفُه وتسلسلُه الخاص يبدأ من 1.

كان الرقم مشتقّاً من معرّف السجل في جدوله: فالمبيعات والمرتجعات
والتحويلات تتقاسم جدولاً واحداً فتتداخل أرقامها (S-00001 ثم R-00002
ثم S-00003)، وسندات القبض والصرف رقمٌ واحد (V-…)، وأرقام القيود
اليومية وسندات التوريد من معرّف القيد العام فتقفز مع كل عمليةٍ في
النظام. والمعتاد محاسبياً — والمطلوب للتدقيق — أن يكون لكل دفترٍ
تسلسلٌ متصلٌ بلا فجوات: فاتورة البيع 1 ثم 2 ثم 3…

    S   فاتورة بيع            R   مرتجع بيع
    T   تحويل داخلي            TR  عكس تحويل داخلي
    RV  سند قبض               PV  سند صرف
    P   مشتريات               JV  قيد يومية
    F   تسكير                 PRD سند توريد من التصنيع
    MD/MR/MC صرف للصب / قبض مصفى / إقفال صب
    TS/TSR/TSD فاتورة ضريبية / إشعار دائن / إشعار مدين
    ST  جرد · SH  تسوية فاقد · TDN إشعار مدين ضريبي · ADJ تسوية مباشرة

**القاعدة المتينة**: العدّاد يبدأ عند أول استعمال من **أعلى رقمٍ قائم**
بحرفه — فقاعدةٌ قديمة تكمل من حيث انتهت ولا يتكرّر رقم، والمصنع الجديد
يبدأ من 1. والحجز داخل معاملة الترحيل نفسها: إن أُلغيت لم يُستهلك الرقم.
"""

# أين تُحفظ أرقام المستندات — للبحث عن أعلى رقمٍ قائم بحرفه ولمنع التكرار
_SOURCES = (("invoices", "invoice_no"), ("vouchers", "voucher_no"),
            ("purchases", "purchase_no"), ("fixing_ops", "op_no"),
            ("melting_ops", "op_no"), ("tax_sales", "doc_no"),
            ("stocktakes", "stocktake_no"), ("shrinkage_ops", "op_no"),
            ("tax_debit_notes", "note_no"), ("direct_adjustments", "adj_no"),
            ("journal_entries", "doc_no"))


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS doc_sequences("
        " prefix TEXT PRIMARY KEY, last INTEGER NOT NULL DEFAULT 0)")


def migrate(conn):
    """جدول العدّادات وفهرسٌ على رقم القيد — فالتحقق من عدم تكرار الرقم
    يبحث في دفتر القيود كله عند كل مستند، وبلا فهرسٍ يمسحه سطراً سطراً."""
    ensure_schema(conn)
    if {r["name"] for r in conn.execute("PRAGMA table_info(journal_entries)")
        } >= {"doc_no"}:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_entries_doc_no"
                     " ON journal_entries(doc_no)")


def _sources(conn):
    out = []
    for t, c in _SOURCES:
        try:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
        except Exception:
            cols = set()
        if c in cols:
            out.append((t, c))
    return out


def _suffix(no, prefix):
    tail = str(no)[len(prefix) + 1:]
    return int(tail) if tail.isdigit() else 0


def max_existing(conn, prefix):
    """أعلى رقمٍ قائم بهذا الحرف في كل جداول المستندات."""
    m = 0
    for t, c in _sources(conn):
        for r in conn.execute(f"SELECT {c} v FROM {t} WHERE {c} LIKE ?",
                              (f"{prefix}-%",)):
            m = max(m, _suffix(r["v"], prefix))
    return m


def _used(conn, no, srcs):
    for t, c in srcs:
        if conn.execute(f"SELECT 1 FROM {t} WHERE {c}=? LIMIT 1",
                        (no,)).fetchone():
            return True
    return False


def next_no(conn, prefix, width=5):
    """الرقم التالي لهذا الحرف — يُحجز في المعاملة الجارية."""
    ensure_schema(conn)
    row = conn.execute("SELECT last FROM doc_sequences WHERE prefix=?",
                       (prefix,)).fetchone()
    if row is None:
        last = max_existing(conn, prefix)
        conn.execute("INSERT INTO doc_sequences(prefix,last) VALUES(?,?)",
                     (prefix, last))
    else:
        last = int(row["last"] or 0)
    srcs = _sources(conn)
    while True:
        last += 1
        no = f"{prefix}-{last:0{width}d}"
        if not _used(conn, no, srcs):
            break
    conn.execute("UPDATE doc_sequences SET last=? WHERE prefix=?",
                 (last, prefix))
    return no
