# -*- coding: utf-8 -*-
"""بقايا طابور المزامنة — للتنظيف وحده.

**المزامنة السحابية أُلغيت (4.29)**: كل مصنعٍ يحفظ بياناته على جهازه
وحده، ولا يُرفع منها شيء إلى السحابة ولا يُستقبل منها شيء. فلا
تُضاف إلى هذا الطابور حزمةٌ بعد اليوم، وجدوله `sync_queue` يبقى في
المخطّط لتوافق القواعد القديمة فقط.

ما بقي هنا: إحصاءٌ يُثبت أن الطابور فارغ، وتنظيفُ ما تراكم فيه من
إصدارات سابقة — فتلك الصفوف نُسخٌ JSON كاملة من العمليات تُضخّم
القاعدة وكل نسخة احتياطية منها بلا فائدة.
"""

# مدة الاحتفاظ بالحزم المرفوعة قبل تنظيفها (للقواعد القديمة)
SENT_KEEP_DAYS = 7


def stats(conn):
    """عدد الصفوف في الطابور بحسب حالتها — صفرٌ في كل نسخة حديثة."""
    out = {"pending": 0, "sent": 0, "failed": 0, "total": 0}
    try:
        for r in conn.execute(
                "SELECT status, COUNT(*) n FROM sync_queue GROUP BY status"):
            if r["status"] in out:
                out[r["status"]] = r["n"]
    except Exception:
        return out
    out["total"] = out["pending"] + out["sent"] + out["failed"]
    return out


def purge_sent(conn, keep_days=SENT_KEEP_DAYS):
    """يحذف الحزم المرفوعة القديمة (من إصدارات ما قبل الإلغاء)."""
    try:
        return conn.execute(
            "DELETE FROM sync_queue WHERE status='sent'"
            " AND sent_at IS NOT NULL"
            " AND sent_at < datetime('now','localtime',?)",
            (f"-{int(keep_days)} days",)).rowcount or 0
    except Exception:
        return 0


def purge_all(conn):
    """يفرّغ الطابور كله — لا شيء فيه سيُرفع بعد الإلغاء."""
    try:
        return conn.execute("DELETE FROM sync_queue").rowcount or 0
    except Exception:
        return 0
