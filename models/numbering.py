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
    OR  طلب عميل من دليل الموديلات (بلا أثر محاسبي)

**القاعدة المتينة**: العدّاد يبدأ عند أول استعمال من **أعلى رقمٍ قائم**
بحرفه — فقاعدةٌ قديمة تكمل من حيث انتهت ولا يتكرّر رقم، والمصنع الجديد
يبدأ من 1. والحجز داخل معاملة الترحيل نفسها: إن أُلغيت لم يُستهلك الرقم.

**5.7.0 — الرقم المحذوف لا يضيع**: حذفُ مستندٍ نهائياً (بيع · مرتجع · قبض ·
صرف · قيد يومية · تسكير — `models.doc_delete`) أو دمجُ فاتورةٍ في أخرى
يُحرِّر رقمه (`release`) ويُعاد تسمية المحذوف (`retire_name`) فلا يبقى
الرقم مشغولاً به. وأول مستندٍ جديد من نوعه يأخذ **أصغر رقمٍ محرَّر** قبل أن
يتقدّم العدّاد — فلا تبقى في الدفتر فجوة.
"""
import re as _re

# أين تُحفظ أرقام المستندات — للبحث عن أعلى رقمٍ قائم بحرفه ولمنع التكرار
_SOURCES = (("invoices", "invoice_no"), ("vouchers", "voucher_no"),
            ("purchases", "purchase_no"), ("fixing_ops", "op_no"),
            ("melting_ops", "op_no"), ("tax_sales", "doc_no"),
            ("stocktakes", "stocktake_no"), ("shrinkage_ops", "op_no"),
            ("tax_debit_notes", "note_no"), ("direct_adjustments", "adj_no"),
            ("model_orders", "order_no"), ("journal_entries", "doc_no"),
            ("supply_docs", "supply_no"), ("set_purchases", "doc_no"))


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS doc_sequences("
        " prefix TEXT PRIMARY KEY, last INTEGER NOT NULL DEFAULT 0)")
    # الأرقام المحرَّرة بالحذف أو الدمج — تُعطى لأول مستندٍ جديد من نوعها
    conn.execute(
        "CREATE TABLE IF NOT EXISTS doc_number_pool("
        " prefix TEXT NOT NULL, n INTEGER NOT NULL, doc_no TEXT NOT NULL,"
        " released_by TEXT, released_at TEXT DEFAULT"
        " (datetime('now','localtime')), PRIMARY KEY(prefix, n))")


_NO_RE = _re.compile(r"^([A-Z]{1,4})-(\d{1,9})$")
RETIRED = "·محذوف·"     # علامة المستند المحذوف في رقمه — فيتحرّر الرقم


def split_no(no):
    """(الحرف، الرقم) لرقم مستندٍ مثل S-00005 — أو None."""
    m = _NO_RE.match(str(no or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


def retire_name(no, rec_id):
    """الاسم الذي يحمله المستند المحذوف بدل رقمه: يبقى أثره في سجل
    التتبع مقروءاً، ولا يشغل الرقم عن المستند الجديد."""
    return f"{no}{RETIRED}{int(rec_id)}"


def release(conn, no, username=None):
    """يُحرِّر رقم مستندٍ حُذف أو دُمج — فيأخذه أول مستندٍ جديد من نوعه.
    يعيد True إن كان الرقم من أرقام الدفاتر (حرف-رقم)."""
    p = split_no(no)
    if not p:
        return False
    ensure_schema(conn)
    conn.execute("INSERT OR IGNORE INTO doc_number_pool(prefix,n,doc_no,"
                 "released_by) VALUES(?,?,?,?)",
                 (p[0], p[1], str(no).strip(), username))
    return True


def pooled(conn, prefix=None):
    """الأرقام المحرَّرة التي تنتظر مستنداً جديداً (للعرض والفحص)."""
    ensure_schema(conn)
    if prefix:
        return [r["doc_no"] for r in conn.execute(
            "SELECT doc_no FROM doc_number_pool WHERE prefix=? ORDER BY n",
            (prefix,))]
    return [r["doc_no"] for r in conn.execute(
        "SELECT doc_no FROM doc_number_pool ORDER BY prefix, n")]


def _take_pooled(conn, prefix, srcs):
    """أصغر رقمٍ محرَّر لهذا الحرف ما زال فارغاً — يُسحب من المخزن."""
    for r in conn.execute("SELECT n, doc_no FROM doc_number_pool"
                          " WHERE prefix=? ORDER BY n", (prefix,)).fetchall():
        conn.execute("DELETE FROM doc_number_pool WHERE prefix=? AND n=?",
                     (prefix, r["n"]))
        if not _used(conn, r["doc_no"], srcs):
            return r["doc_no"]
    return None


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
    """الرقم التالي لهذا الحرف — يُحجز في المعاملة الجارية.

    الرقم المحرَّر بحذفٍ أو دمج أولاً (أصغرها)، ثم العدّاد."""
    ensure_schema(conn)
    srcs = _sources(conn)
    reuse = _take_pooled(conn, prefix, srcs)
    if reuse:
        return reuse
    row = conn.execute("SELECT last FROM doc_sequences WHERE prefix=?",
                       (prefix,)).fetchone()
    if row is None:
        last = max_existing(conn, prefix)
        conn.execute("INSERT INTO doc_sequences(prefix,last) VALUES(?,?)",
                     (prefix, last))
    else:
        last = int(row["last"] or 0)
    while True:
        last += 1
        no = f"{prefix}-{last:0{width}d}"
        if not _used(conn, no, srcs):
            break
    conn.execute("UPDATE doc_sequences SET last=? WHERE prefix=?",
                 (last, prefix))
    return no
