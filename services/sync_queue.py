# -*- coding: utf-8 -*-
"""طابور المزامنة الصامت (Silent Sync Queue).

**النزاهة المحاسبية**: كل عملية تُوضع في الطابور كـ**حزمة واحدة**
(`bundle`) تضم الفاتورة وقيدها المحاسبي وحركة أرقام التشغيل معاً. فإما
تُرفع الحزمة كاملة إلى السحابة أو لا تُرفع إطلاقاً — فلا تختلف
الميزانية المحلية عن السحابية أبداً.

**صفر تأخير**: الإدراج في الطابور يتم داخل نفس معاملة العملية المحلية
(صف واحد صغير)، والرفع يتولاه خيط خلفي معزول تماماً عن الواجهة.
"""
import json
import uuid

from services import tenant

# الحد الأقصى لمحاولات الرفع قبل وسم العملية «فاشلة» لمراجعتها
MAX_ATTEMPTS = 8
BATCH_SIZE = 50

# مدة الاحتفاظ بالحزم المرفوعة قبل تنظيفها
SENT_KEEP_DAYS = 7


def enqueue(conn, entity, payload, op_uuid=None):
    """يضيف حزمة عملية للطابور داخل معاملة العملية نفسها.

    `entity`: نوع الحزمة (invoice · voucher · work_order · journal …)
    `payload`: قاموس يضم **كل** سجلات العملية المترابطة.
    """
    op_uuid = op_uuid or str(uuid.uuid4())
    conn.execute(
        "INSERT OR IGNORE INTO sync_queue(tenant_id,op_uuid,entity,payload)"
        " VALUES(?,?,?,?)",
        (tenant.tenant_id(), op_uuid, entity,
         json.dumps(payload, ensure_ascii=False, default=str)))
    return op_uuid


def bundle_invoice(conn, invoice_id):
    """حزمة فاتورة كاملة: الفاتورة + بنودها + قيدها + أسطر القيد +
    حالات أرقام التشغيل — لترفع ككتلة واحدة لا تتجزأ."""
    inv = conn.execute("SELECT * FROM invoices WHERE id=?",
                       (invoice_id,)).fetchone()
    if not inv:
        return None
    items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id=?",
                         (invoice_id,)).fetchall()
    entry = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                         (inv["entry_id"],)).fetchone()
    lines = conn.execute("SELECT * FROM journal_lines WHERE entry_id=?",
                         (inv["entry_id"],)).fetchall() if entry else []
    wos = []
    for it in items:
        w = conn.execute(
            "SELECT id, work_order_no, status, registered_weight, item_type"
            " FROM work_orders WHERE id=?", (it["work_order_id"],)).fetchone()
        if w:
            wos.append(dict(w))
    return {"invoice": dict(inv), "items": [dict(i) for i in items],
            "entry": dict(entry) if entry else None,
            "lines": [dict(l) for l in lines],
            "work_orders": wos}


def bundle_voucher(conn, voucher_id):
    """حزمة سند: السند + أسطره + قيده + أسطر القيد."""
    v = conn.execute("SELECT * FROM vouchers WHERE id=?",
                     (voucher_id,)).fetchone()
    if not v:
        return None
    vl = conn.execute("SELECT * FROM voucher_lines WHERE voucher_id=?",
                      (voucher_id,)).fetchall()
    entry = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                         (v["entry_id"],)).fetchone()
    lines = conn.execute("SELECT * FROM journal_lines WHERE entry_id=?",
                         (v["entry_id"],)).fetchall() if entry else []
    return {"voucher": dict(v), "voucher_lines": [dict(x) for x in vl],
            "entry": dict(entry) if entry else None,
            "lines": [dict(l) for l in lines]}


def bundle_entry(conn, entry_id):
    """حزمة قيد يومية مستقل (توريد · صب · رواتب · تسوية …)."""
    entry = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                         (entry_id,)).fetchone()
    if not entry:
        return None
    lines = conn.execute("SELECT * FROM journal_lines WHERE entry_id=?",
                         (entry_id,)).fetchall()
    return {"entry": dict(entry), "lines": [dict(l) for l in lines]}


# ══════════════════════════════════════════════════════════════════
# قراءة الطابور وتحديث حالاته
# ══════════════════════════════════════════════════════════════════

def pending_batch(conn, limit=BATCH_SIZE):
    return conn.execute(
        "SELECT * FROM sync_queue WHERE status='pending'"
        " AND attempts < ? ORDER BY id LIMIT ?",
        (MAX_ATTEMPTS, limit)).fetchall()


def mark_sent(conn, ids):
    if not ids:
        return
    qs = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE sync_queue SET status='sent',"
        f" sent_at=datetime('now','localtime') WHERE id IN ({qs})", ids)


def mark_failed(conn, ids, error=""):
    if not ids:
        return
    qs = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE sync_queue SET attempts=attempts+1, last_error=?,"
        f" status=CASE WHEN attempts+1 >= ? THEN 'failed' ELSE 'pending' END"
        f" WHERE id IN ({qs})", [str(error)[:400], MAX_ATTEMPTS] + list(ids))


def stats(conn):
    """إحصاءات الطابور لعرضها في الواجهة بلا إزعاج المستخدم.

    `GROUP BY status` يُحسب من فهرس (status, id) وحده، بينما الصيغة
    السابقة (SUM(status='pending') …) كانت تُجبر SQLite على مسح كل
    صفوف الطابور — ومعها حقل `payload` الضخم — في كل دورة مزامنة،
    أي كل بضع ثوانٍ. هذا هو أكبر مصدر لبطء لا يفسّره حجم العمل.
    """
    out = {"pending": 0, "sent": 0, "failed": 0, "total": 0}
    for r in conn.execute(
            "SELECT status, COUNT(*) n FROM sync_queue GROUP BY status"):
        if r["status"] in out:
            out[r["status"]] = r["n"]
    out["total"] = out["pending"] + out["sent"] + out["failed"]
    return out


def purge_sent(conn, keep_days=SENT_KEEP_DAYS):
    """يحذف الحزم المرفوعة القديمة.

    كل قيد وفاتورة وسند يترك في الطابور صفاً يحمل نسخة JSON كاملة من
    العملية. هذه الصفوف لم تكن تُحذف أبداً، فينمو الطابور حتى يصير
    أكبر جداول القاعدة — يُبطئ كل دورة مزامنة، ويُضخّم كل نسخة
    احتياطية (وهي تُرفع للسحابة كل ساعة). بعد الرفع الناجح تفقد الحزمة
    قيمتها، فالاحتفاظ بأسبوع منها كافٍ للمراجعة.
    """
    try:
        return conn.execute(
            "DELETE FROM sync_queue WHERE status='sent'"
            " AND sent_at IS NOT NULL"
            " AND sent_at < datetime('now','localtime',?)",
            (f"-{int(keep_days)} days",)).rowcount or 0
    except Exception:
        return 0


def retry_failed(conn):
    """إعادة العمليات الفاشلة للطابور بعد معالجة سبب الفشل."""
    n = conn.execute(
        "UPDATE sync_queue SET status='pending', attempts=0, last_error=''"
        " WHERE status='failed'").rowcount
    return n or 0
