# -*- coding: utf-8 -*-
"""محرك التعديل الشامل (Universal Edit).

أي عملية في النظام تُعدَّل بنفس الآلية المحاسبية الآمنة، داخل **معاملة
واحدة** لا تتجزأ:

  1. عكس أثر المستند القديم بالكامل — القيود اليومية وحركات المخازن
     وصناديق الكسر وحالات الأطقم — عبر نفس محرك العكس المركزي المستخدم
     في الحذف (`services.audit.reverse_entry`)، فلا يوجد منطق عكس
     مزدوج يمكن أن يتعارض.
  2. تحويل المستند القديم إلى «ملغى» مع بقاء أثره صفراً، حفاظاً على
     سلامة التتابع الرقمي وإمكانية التتبع الرقابي.
  3. ترحيل المستند الجديد بقيده المحاسبي الجديد.
  4. تسجيل التعديل في سجل التتبع (Audit Trail) رابطاً القديم بالجديد.

النتيجة: دفتر الأستاذ العام والأستاذ المساعد يتحدثان فوراً ويبقى
الميزانان (الوزني والنقدي) متوازنين، لأن القيد الجديد يمر من نفس
`post_entry` الذي يرفض أي قيد غير متوازن.
"""
from services.audit import log_action, reverse_entry

# المستندات القابلة للتعديل ومسمياتها والشاشة التي تُفتح لتعديلها
EDITABLE = {
    "invoices": ("فاتورة مبيعات/مرتجع", "sales"),
    "vouchers": ("سند قبض/صرف", "vouchers"),
    "work_orders": ("توريد/إنتاج", "wo_supply"),
    "wo_adjust": ("تسوية وزن طقم", "wo_adjust"),
    "melting_ops": ("عملية صهر", "melting"),
    "fixing_ops": ("عملية تسكير", "fixing"),
    "shrinkage_ops": ("تسوية فاقد", "shrinkage"),
    "purchases": ("فاتورة مشتريات", "purchases"),
    "manual": ("قيد يومية يدوي", "journal"),
    "mfg_salaries": ("رواتب عمال التصنيع", "mfg_costs"),
    "payroll": ("رواتب الموظفين", "payroll"),
}


def entry_of(conn, source_table, source_id):
    """رقم القيد المرتبط بمستند معيّن (غير المحذوف)."""
    row = conn.execute(
        "SELECT id FROM journal_entries WHERE source_table=? AND source_id=?"
        " AND is_deleted=0 ORDER BY id DESC LIMIT 1",
        (source_table, source_id)).fetchone()
    return row["id"] if row else None


def void_for_edit(conn, entry_id, username, note=""):
    """يعكس أثر المستند القديم ويلغيه تمهيداً لترحيل نسخته المعدَّلة.

    يُستدعى **داخل** نفس معاملة الحفظ الجديدة، فإن فشل الترحيل الجديد
    لأي سبب (قيد غير متوازن، رصيد غير كافٍ...) تُلغى المعاملة كلها
    ويعود المستند القديم كما كان دون أي أثر جانبي."""
    e = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                     (entry_id,)).fetchone()
    if not e:
        raise ValueError("القيد الأصلي غير موجود")
    if e["is_deleted"]:
        raise ValueError("القيد الأصلي محذوف — لا يمكن تعديله")
    reverse_entry(conn, entry_id, username)
    log_action(conn, username, "edit_void", e["source_table"], e["source_id"],
              f"إلغاء تمهيداً للتعديل — قيد {entry_id} {note}")
    return {"old_entry_id": entry_id, "source_table": e["source_table"],
            "source_id": e["source_id"]}


def log_edit(conn, username, source_table, old_id, new_id, new_entry_id):
    """يسجّل اكتمال التعديل في سجل التتبع رابطاً القديم بالجديد."""
    log_action(conn, username, "edit", source_table, new_id,
              f"تعديل: حلّ محل السجل رقم {old_id} — القيد الجديد "
              f"{new_entry_id}")


def repost(conn, entry_id, username, create_fn, *args, **kwargs):
    """الغلاف العام: عكس القديم ثم ترحيل الجديد بدالة الإنشاء الأصلية.

    مثال:
        repost(conn, eid, user, vouchers.create_voucher, "receipt", ...)
    """
    info = void_for_edit(conn, entry_id, username)
    res = create_fn(conn, *args, **kwargs)
    new_id = res.get("id") if isinstance(res, dict) else None
    new_entry = res.get("entry_id") if isinstance(res, dict) else None

    # ══ توريث مفتاح الترتيب وتاريخ القيد ══
    # القيد الجديد يرث مفتاح سلفه، فيبقى في موضعه الزمني نفسه في
    # كل الكشوف بدل النزول لآخر يومه لأن معرّفه أكبر.
    if new_entry and info.get("old_entry_id"):
        try:
            old = conn.execute(
                "SELECT COALESCE(sort_key, id) k FROM journal_entries"
                " WHERE id=?", (info["old_entry_id"],)).fetchone()
            if old:
                conn.execute(
                    "UPDATE journal_entries SET sort_key=? WHERE id=?",
                    (old["k"], new_entry))
        except Exception:
            pass
    log_edit(conn, username, info["source_table"], info["source_id"],
             new_id, new_entry)
    if isinstance(res, dict):
        res["replaced_id"] = info["source_id"]
        res["replaced_entry_id"] = info["old_entry_id"]
    return res


def load_document(conn, source_table, source_id):
    """يجلب بيانات المستند لتعبئة شاشته عند التعديل."""
    table = {"manual": "journal_entries"}.get(source_table, source_table)
    if source_table == "manual":
        e = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                         (source_id,)).fetchone()
        if not e:
            return None
        lines = conn.execute(
            "SELECT l.*, a.code acode, a.name aname FROM journal_lines l"
            " JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?"
            " ORDER BY l.id", (source_id,)).fetchall()
        return {"entry": e, "lines": lines}
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?",
                       (source_id,)).fetchone()
    return dict(row) if row else None
