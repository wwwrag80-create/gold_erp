# -*- coding: utf-8 -*-
"""سجل التتبع والحذف المنطقي المركزي (لا DELETE فعلي في النظام)."""
from database.database import db


def log_action(conn, username, action, table_name=None, record_id=None, details=""):
    conn.execute(
        "INSERT INTO audit_log(username,action,table_name,record_id,details)"
        " VALUES(?,?,?,?,?)",
        (username, action, table_name, record_id, details))


def _mark(conn, table, rec_id, username):
    conn.execute(f"UPDATE {table} SET is_deleted=1 WHERE id=?", (rec_id,))
    log_action(conn, username, "soft_delete", table, rec_id, "")


def _advance_outstanding(conn, employee_id):
    r = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='advance' THEN amount ELSE 0 END),0)"
        " - COALESCE(SUM(CASE WHEN kind='payment' THEN advance_deducted"
        " ELSE 0 END),0) v"
        " FROM payroll_ledger WHERE employee_id=? AND is_deleted=0",
        (employee_id,)).fetchone()
    return round(r["v"], 2)


def reverse_entry(conn, entry_id: int, username: str) -> str:
    """
    حذف منطقي لقيد ومستنده المصدر مع عكس الآثار الجانبية:
    - فاتورة بيع: تعود الأطقم للمخزون. مرتجع: تعود الأطقم مباعة.
    - سند/صهر: تُلغى حركات صناديق الكسر الفعلية المرتبطة.
    - إنتاج: يُحذف الطقم (يُمنع إن كان مباعاً).
    - رواتب: تُلغى حركات الاستحقاق/السلفة/الصرف المرتبطة بالقيد بضوابط سلامة.
    يعيد وصفاً عربياً لما حدث.
    """
    if True:
        e = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                         (entry_id,)).fetchone()
        if not e:
            raise ValueError("القيد غير موجود")
        if e["is_deleted"]:
            raise ValueError("القيد محذوف مسبقاً")
        # حذف قيد داخل فترة مقفلة يغيّر ميزانيةً سبق اعتمادها تماماً
        # كإضافة قيد جديد فيها — فيخضع للقفل نفسه.
        from models import fiscal
        fiscal.assert_open(conn, e["entry_date"])
        src, sid = e["source_table"], e["source_id"]

        if src == "work_orders":
            # القيد قد يكون فردياً (source_id) أو مجمّعاً لدفعة (entry_id
            # مشترك على أكثر من طقم) — نجمع الطرفين لضمان التوافق الرجعي.
            wos = conn.execute(
                "SELECT * FROM work_orders WHERE entry_id=?", (entry_id,)).fetchall()
            if not wos and sid:
                wo = conn.execute("SELECT * FROM work_orders WHERE id=?",
                                  (sid,)).fetchone()
                wos = [wo] if wo else []
            sold = [w for w in wos if w["status"] == "sold"]
            if sold:
                names = "، ".join(w["work_order_no"] for w in sold)
                raise ValueError(
                    "لا يمكن حذف قيد الإنتاج — الأطقم التالية تم بيعها أو "
                    f"تحويلها: {names} — احذف الفاتورة المرتبطة أولاً")
            for w in wos:
                _mark(conn, "work_orders", w["id"], username)
            # دفعةٌ ورَدت إلى صندوق الكسر: حذفها يُخرج وزنها من عياره،
            # وإلا بقي الصندوق زائداً بعيارٍ بلا مستندٍ يفسّره.
            conn.execute("UPDATE scrap_moves SET is_deleted=1"
                         " WHERE ref_table='work_orders' AND ref_id=?",
                         (entry_id,))
        elif src == "invoices":
            from models.inventory import adjust_bulk_wo
            inv = conn.execute("SELECT * FROM invoices WHERE id=?", (sid,)).fetchone()
            if inv:
                new_status = "in_stock" if inv["kind"] == "sale" else "sold"
                for it in conn.execute(
                        "SELECT it.*, w.is_bulk FROM invoice_items it"
                        " JOIN work_orders w ON w.id=it.work_order_id"
                        " WHERE invoice_id=?", (sid,)):
                    if it["is_bulk"]:
                        delta = -it["registered_weight"] if inv["kind"] == "sale_return" \
                            else it["registered_weight"]
                        adjust_bulk_wo(conn, delta, username)
                    else:
                        conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                                     (new_status, it["work_order_id"]))
                # فاتورةٌ بيعت من صندوق الكسر: حذفها يُعيد وزنها لعياره،
                # وإلا بقي الصندوق ناقصاً بعيارٍ بلا مستندٍ يفسّره.
                conn.execute("UPDATE scrap_moves SET is_deleted=1"
                             " WHERE ref_table='invoices' AND ref_id=?",
                             (sid,))
                _mark(conn, "invoices", sid, username)
        elif src == "tax_debit_notes":
            _mark(conn, "tax_debit_notes", sid, username)
        elif src == "vouchers":
            conn.execute("UPDATE scrap_moves SET is_deleted=1"
                         " WHERE ref_table='vouchers' AND ref_id=?", (sid,))
            _mark(conn, "vouchers", sid, username)
        elif src == "melting_ops":
            conn.execute("UPDATE scrap_moves SET is_deleted=1"
                         " WHERE ref_table='melting_ops' AND ref_id=?", (sid,))
            _mark(conn, "melting_ops", sid, username)
        elif src == "fixing_ops":
            _mark(conn, "fixing_ops", sid, username)
        elif src == "shrinkage_ops":
            _mark(conn, "shrinkage_ops", sid, username)
        elif src == "stocktakes":
            st = conn.execute("SELECT * FROM stocktakes WHERE id=?", (sid,)).fetchone()
            if st and st["mode"] == "itemized":
                for ln in conn.execute(
                        "SELECT * FROM stocktake_lines WHERE stocktake_id=?"
                        " AND status='missing'", (sid,)):
                    if ln["work_order_id"]:
                        conn.execute(
                            "UPDATE work_orders SET is_deleted=0 WHERE id=?",
                            (ln["work_order_id"],))
            if st:
                _mark(conn, "stocktakes", sid, username)
        elif src == "purchases":
            p = conn.execute("SELECT * FROM purchases WHERE id=?", (sid,)).fetchone()
            if p and p["asset_id"]:
                _mark(conn, "fixed_assets", p["asset_id"], username)
            if p:
                _mark(conn, "purchases", sid, username)
        elif src == "payroll_ledger":
            rows = conn.execute(
                "SELECT * FROM payroll_ledger WHERE entry_id=? AND is_deleted=0",
                (entry_id,)).fetchall()
            for r in rows:
                if r["kind"] == "accrual":
                    paid = conn.execute(
                        "SELECT 1 FROM payroll_ledger WHERE employee_id=?"
                        " AND period=? AND kind='payment' AND is_deleted=0",
                        (r["employee_id"], r["period"])).fetchone()
                    if paid:
                        raise ValueError(
                            "لا يمكن حذف قيد استحقاق فترة تم صرف رواتبها — "
                            "احذف قيد الصرف أولاً")
                elif r["kind"] == "advance":
                    if _advance_outstanding(conn, r["employee_id"]) \
                            - r["amount"] < -0.005:
                        raise ValueError(
                            "لا يمكن حذف سلفة سبق خصمها ضمن صرف رواتب — "
                            "احذف قيد الصرف أولاً")
            conn.execute("UPDATE payroll_ledger SET is_deleted=1"
                         " WHERE entry_id=?", (entry_id,))

        conn.execute(
            "UPDATE journal_entries SET is_deleted=1, deleted_by=?,"
            " deleted_at=datetime('now','localtime') WHERE id=?",
            (username, entry_id))
        log_action(conn, username, "soft_delete", "journal_entries", entry_id,
                   f"source={src}/{sid}")
        return f"تم الحذف المنطقي للقيد رقم {entry_id} وعكس آثاره"


def soft_delete_entry(entry_id: int, username: str) -> str:
    """حذف منطقي بمعاملة مستقلة (يُستدعى من الشاشات مباشرة)."""
    with db() as conn:
        src = conn.execute(
            "SELECT source_table, source_id FROM journal_entries"
            " WHERE id=?", (entry_id,)).fetchone()
        msg = reverse_entry(conn, entry_id, username)
    # ══ صفحة الفاتورة المحذوفة تُعلن إلغاءها ══
    # **بعد إغلاق المعاملة**: الإعلان رفعٌ عبر الإنترنت، وإجراؤه داخل
    # المعاملة يحبس قفل الكتابة. ومن بيده الورقة سيصوّر رمزها يوماً،
    # فصفحةٌ باقية بمضمونها القديم تُوهمه أن فاتورةً ملغاة ما زالت
    # سارية — وهو أخطر من صفحةٍ مفقودة.
    try:
        if src and src["source_table"] == "invoices" and src["source_id"]:
            import config
            from services import invoice_share
            invoice_share.mark_cancelled(src["source_id"],
                                         config.COMPANY_NAME)
    except Exception:
        pass          # إعلان الإلغاء لا يُبطل حذفاً تمّ
    return msg
