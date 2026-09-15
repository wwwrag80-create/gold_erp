# -*- coding: utf-8 -*-
"""قفل الفترات المالية — ضابط محاسبي أساسي في أنظمة ERP.

**المشكلة التي يعالجها**: بعد إقفال سنة وتسليم ميزانيتها ومعها الإقرار
الضريبي، يستطيع أي مستخدم — بحسن نية — أن يحفظ فاتورة أو سنداً بتاريخ
قديم داخل تلك السنة. القيد يُقبل، والأرصدة تتغيّر، فتصبح الميزانية
المسلَّمة مخالفةً للنظام ولا أحد يعلم. هذه ليست حالة نادرة: خطأ واحد
في حقل التاريخ يكفي.

**العلاج**: تاريخ قفل واحد. أي قيد تاريخه ≤ تاريخ القفل يُرفض برسالة
واضحة. القفل يُرفع ويُنزل من شاشة الإعدادات بصلاحية المحاسب، وكل
تغيير فيه يُسجَّل في سجل التدقيق — فالقفل نفسه قابل للمراجعة.
"""
import datetime as _dt

LOCK_KEY = "fiscal_lock_date"


# ══════════════════════════════════════════════════════════════════
#  جدول الإعدادات العام (مفتاح/قيمة) — يستعمله القفل وغيره
# ══════════════════════════════════════════════════════════════════

def ensure_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_settings("
        " key TEXT PRIMARY KEY,"
        " value TEXT NOT NULL DEFAULT '',"
        " updated_by TEXT,"
        " updated_at TEXT DEFAULT (datetime('now','localtime')))")


def get_setting(conn, key, default=""):
    try:
        r = conn.execute("SELECT value FROM app_settings WHERE key=?",
                         (key,)).fetchone()
    except Exception:
        return default
    return r["value"] if r else default


def set_setting(conn, key, value, username=None):
    ensure_table(conn)
    conn.execute(
        "INSERT INTO app_settings(key,value,updated_by,updated_at)"
        " VALUES(?,?,?,datetime('now','localtime'))"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
        " updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (key, str(value), username))
    return value


# ══════════════════════════════════════════════════════════════════
#  القفل
# ══════════════════════════════════════════════════════════════════

def lock_date(conn):
    """تاريخ القفل الحالي (نص ISO) أو "" إن لم يكن هناك قفل."""
    return (get_setting(conn, LOCK_KEY, "") or "").strip()


def _valid_date(value):
    try:
        _dt.date.fromisoformat(str(value).strip()[:10])
        return str(value).strip()[:10]
    except Exception:
        raise ValueError("تاريخ القفل غير صالح — الصيغة YYYY-MM-DD")


def set_lock(conn, date_str, username=None):
    """يقفل كل ما هو ≤ `date_str`. القيمة الفارغة تُلغي القفل."""
    from services.audit import log_action
    if not str(date_str or "").strip():
        set_setting(conn, LOCK_KEY, "", username)
        log_action(conn, username, "update", "app_settings", None,
                   "fiscal_lock=cleared")
        return ""
    d = _valid_date(date_str)
    set_setting(conn, LOCK_KEY, d, username)
    log_action(conn, username, "update", "app_settings", None,
               f"fiscal_lock={d}")
    return d


def is_open(conn, entry_date):
    """هل الفترة التي يقع فيها `entry_date` مفتوحة للترحيل؟"""
    lock = lock_date(conn)
    if not lock:
        return True
    d = str(entry_date or "").strip()[:10]
    if not d:
        return True
    return d > lock


def assert_open(conn, entry_date):
    """يرفع ValueError إن كان التاريخ داخل فترة مقفلة."""
    lock = lock_date(conn)
    if not lock:
        return True
    d = str(entry_date or "").strip()[:10]
    if d and d <= lock:
        raise ValueError(
            f"الفترة حتى {lock} مقفلة محاسبياً — لا يُقبل قيد بتاريخ {d}.\n"
            "استعمل تاريخاً بعد القفل، أو ارفع القفل من شاشة الإعدادات "
            "إن كان التعديل مقصوداً.")
    return True


def status(conn):
    """ملخّص القفل لعرضه في الواجهة."""
    lock = lock_date(conn)
    n = 0
    if lock:
        try:
            n = conn.execute(
                "SELECT COUNT(*) c FROM journal_entries"
                " WHERE is_deleted=0 AND entry_date<=?", (lock,)).fetchone()["c"]
        except Exception:
            n = 0
    return {"locked": bool(lock), "date": lock, "entries_locked": n}
