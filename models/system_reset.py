# -*- coding: utf-8 -*-
"""تهيئة النظام من الصفر (Danger Zone).

يمسح **كل** البيانات المالية والتشغيلية محلياً وسحابياً ويعيد النظام
كأنه مثبَّت لأول مرة، مع الإبقاء على حساب المدير وحده.

إجراء لا رجعة فيه — لذلك يتطلب تأكيداً مغلَّظاً وكلمة المرور، ويأخذ
نسخة احتياطية أخيرة قبل التنفيذ احتياطاً.
"""
import shutil
from pathlib import Path

# الجداول التي تُفرَّغ بالكامل (بيانات مالية وتشغيلية)
DATA_TABLES = [
    "journal_lines", "journal_entries",
    "invoice_items", "invoices",
    "voucher_lines", "vouchers",
    "work_orders", "wo_adjust",
    "melting_ops", "melting_lines",
    "fixing_ops", "purchases",
    "shrinkage_ops",
    "payroll_ledger", "employees",
    "mfg_targets", "mfg_salaries",
    "entities", "accounts",
    "sync_queue", "audit_log",
    "stock_moves", "scrap_moves",
]

# جداول لا تُمسّ (المستخدمون وإعدادات النظام)
KEEP_TABLES = {"users", "settings", "schema_migrations", "schema_baseline"}


def _existing(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


def wipe_local(conn, keep_admin=True):
    """يفرّغ كل الجداول المالية ويعيد بناء شجرة الحسابات."""
    from database.seed import ensure_system_tags
    from models.entities import (ensure_employee_accrual_accounts,
                                 ensure_internal_counterparties)

    cleared = []
    # لا نستخدم PRAGMA foreign_keys داخل معاملة (يُتجاهل صامتاً)،
    # بل نحذف بترتيب التبعية: الأبناء قبل الآباء.
    try:
        for t in DATA_TABLES:
            if t in KEEP_TABLES or not _existing(conn, t):
                continue
            try:
                conn.execute(f"DELETE FROM {t}")
                cleared.append(t)
            except Exception as e:
                # جدول له مرجع لم يُحذف بعد — نعيد المحاولة لاحقاً
                cleared.append(f"!{t}")
        # مرور ثانٍ لما فشل بسبب ترتيب التبعية
        for t in [x[1:] for x in cleared if x.startswith("!")]:
            try:
                conn.execute(f"DELETE FROM {t}")
                cleared.append(t)
            except Exception:
                pass
        cleared = [c for c in cleared if not c.startswith("!")]
        # تصفير العدّادات
        if _existing(conn, "sqlite_sequence"):
            conn.execute("DELETE FROM sqlite_sequence")
        # المستخدمون: الإبقاء على المدير وحده
        if keep_admin and _existing(conn, "users"):
            conn.execute("DELETE FROM users WHERE username<>'admin'")
    finally:
        pass

    # إعادة بناء شجرة الحسابات بنفس الاتصال — لا نفتح معاملة جديدة
    # داخل معاملة قائمة (تُسبّب قفل قاعدة البيانات).
    from database.seed import ACCOUNTS
    for code, name, atype, parent, postable, btype in ACCOUNTS:
        pid = None
        if parent:
            row = conn.execute("SELECT id FROM accounts WHERE code=?",
                               (parent,)).fetchone()
            pid = row["id"] if row else None
        nature = ("credit" if atype in ("liability", "equity", "revenue")
                  else "debit")
        conn.execute(
            "INSERT OR IGNORE INTO accounts(code,name,type,parent_id,"
            "is_postable,nature,balance_type) VALUES(?,?,?,?,?,?,?)",
            (code, name, atype, pid, postable, nature, btype))
    # مرور ثانٍ لربط الآباء الذين أُنشئوا بعد أبنائهم
    for code, _n, _t, parent, _p, _b in ACCOUNTS:
        if not parent:
            continue
        row = conn.execute("SELECT id FROM accounts WHERE code=?",
                           (parent,)).fetchone()
        if row:
            conn.execute("UPDATE accounts SET parent_id=? WHERE code=?"
                         " AND parent_id IS NULL", (row["id"], code))
    ensure_internal_counterparties(conn)
    ensure_employee_accrual_accounts(conn)
    ensure_system_tags(conn)
    return cleared


def wipe_cloud():
    """يمسح بيانات هذا المصنع من السحابة عبر دالة الخادم."""
    from services import cloud_auth, tenant
    tid = tenant.effective_tenant_id()
    try:
        cloud_auth._rpc("admin_wipe_tenant",
                        {"p_token": cloud_auth._need_token(),
                         "p_tenant": tid})
        return {"ok": True, "tenant": tid}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def wipe_backups():
    """يحذف كل النسخ الاحتياطية المحلية."""
    from services import licensing, storage
    removed = 0
    targets = []
    try:
        targets.append(Path(storage.backup_dir()))
    except Exception:
        pass
    try:
        targets.append(Path(licensing.BACKUP_DIR))
    except Exception:
        pass
    for d in targets:
        try:
            if d.exists():
                for f in d.glob("*"):
                    try:
                        if f.is_file():
                            f.unlink()
                            removed += 1
                        elif f.is_dir():
                            shutil.rmtree(f, ignore_errors=True)
                            removed += 1
                    except Exception:
                        pass
        except Exception:
            pass
    return removed


def wipe_all_tenants(keep_tenant=None):
    """يحذف قواعد بيانات **كل** المصانع على هذا الجهاز.

    المسح كان يطال قاعدة المصنع النشط وحده، فتبقى قواعد المصانع
    الأخرى كما هي — فيرى المستخدم أسماء قديمة عند الدخول بحساب آخر
    ويظن أن المسح فشل. الآن يُمسح الجهاز كاملاً.
    """
    import config
    from services import tenant_db
    removed = []
    for t in tenant_db.list_tenant_dbs(config.BASE_DIR):
        if keep_tenant and t["tenant_id"] == keep_tenant:
            continue
        try:
            p = Path(t["path"])
            for ext in ("", "-wal", "-shm"):
                Path(str(p) + ext).unlink(missing_ok=True)
            # المجلد نفسه إن صار فارغاً
            try:
                p.parent.rmdir()
            except Exception:
                pass
            removed.append(t["tenant_id"])
        except Exception:
            pass
    # وقاعدة البيانات القديمة المشتركة إن بقيت
    try:
        legacy = Path(config.BASE_DIR) / "data" / "gold_erp.db"
        for ext in ("", "-wal", "-shm"):
            Path(str(legacy) + ext).unlink(missing_ok=True)
    except Exception:
        pass
    return removed


def full_reset(conn, wipe_cloud_too=True, wipe_backups_too=True,
               wipe_other_tenants=True):
    """التهيئة الكاملة: محلي + كل المصانع + سحابي + النسخ."""
    result = {"local": [], "cloud": None, "backups": 0, "last_backup": None,
              "tenants": []}

    # نسخة أخيرة قبل المسح — احتياطاً لا أكثر
    try:
        from services import storage
        result["last_backup"] = storage.make_backup("before_reset")
    except Exception:
        pass

    result["local"] = wipe_local(conn)
    if wipe_other_tenants:
        # قواعد المصانع الأخرى على الجهاز — نُبقي المصنع النشط لأنه
        # فُرِّغ للتوّ وأُعيد بناء شجرته
        try:
            from services import tenant_db
            result["tenants"] = wipe_all_tenants(
                keep_tenant=tenant_db.active_tenant())
        except Exception:
            pass
    if wipe_cloud_too:
        result["cloud"] = wipe_cloud()
    if wipe_backups_too:
        result["backups"] = wipe_backups()
    return result
