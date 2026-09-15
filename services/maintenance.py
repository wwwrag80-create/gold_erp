# -*- coding: utf-8 -*-
"""صيانة قاعدة البيانات — ما يجعل النظام يبقى سريعاً مع مرور السنين.

قاعدة SQLite لا تتدهور فجأة، بل تتدهور ببطء إن تُركت بلا صيانة:

1. **بلا إحصاءات** لا يعرف مخطِّط الاستعلام أي فهرس أنفع، فيختار
   أحياناً مسح الجدول كاملاً بدل الفهرس. الفرق لا يُلاحظ على ألف
   قيد، ويصير ثوانيَ على مئة ألف. `PRAGMA optimize` يعالج هذا
   ويكلّف أجزاءً من الثانية.
2. **ملف WAL** يتضخّم بين نقاط التفتيش؛ وإن تضخّم بطؤت القراءة
   وكبرت كل نسخة احتياطية.
3. **الصفحات المحرَّرة** (بعد تنظيف طابور المزامنة مثلاً) تبقى في
   الملف فلا يصغر حجمه — يُعاد استعمالها، لكن النسخ الاحتياطية
   تظل تنقل حجماً لا داعي له حتى يُضغط الملف.

الصيانة هنا **آمنة أثناء العمل**: `optimize` و`checkpoint` لا يقفلان
النظام. `compact` (VACUUM) وحده ثقيل، فهو إجراء يدوي صريح.
"""
import datetime as _dt
import threading

from database.database import db, get_connection

LAST_KEY = "last_maintenance"
EVERY_HOURS = 24


# ══════════════════════════════════════════════════════════════════
#  صيانة خفيفة — آمنة أثناء العمل
# ══════════════════════════════════════════════════════════════════

def optimize(conn=None):
    """يحدّث إحصاءات المخطِّط. رخيص، ويُنصح به عند كل إغلاق."""
    own = conn is None
    c = get_connection() if own else conn
    try:
        c.execute("PRAGMA optimize")
        return True
    except Exception:
        return False
    finally:
        if own:
            c.close()


def checkpoint(truncate=True):
    """يدمج ملف WAL في القاعدة ويقلّصه.

    يعيد (صفحات WAL قبل الدمج، صفحات مدموجة) أو None عند التعذّر.
    `PASSIVE` لا ينتظر أحداً؛ نستعمل TRUNCATE لأنه يُصفّر الملف بعد
    الدمج فلا يظل بحجمه الأكبر.
    """
    c = get_connection()
    try:
        mode = "TRUNCATE" if truncate else "PASSIVE"
        r = c.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        return tuple(r) if r else None
    except Exception:
        return None
    finally:
        c.close()


def analyze():
    """يبني إحصاءات كاملة — أثقل من optimize، يُستدعى نادراً."""
    c = get_connection()
    try:
        c.execute("ANALYZE")
        return True
    except Exception:
        return False
    finally:
        c.close()


def light_maintenance():
    """الدورة الخفيفة: تنظيف الطابور + تفتيش WAL + تحديث الإحصاءات."""
    out = {"purged": 0, "wal": None, "optimized": False}
    try:
        from services import sync_queue
        with db() as conn:
            out["purged"] = sync_queue.purge_sent(conn)
    except Exception:
        pass
    out["wal"] = checkpoint(truncate=True)
    out["optimized"] = optimize()
    try:
        from models import fiscal
        with db() as conn:
            fiscal.set_setting(
                conn, LAST_KEY,
                _dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "system")
    except Exception:
        pass
    return out


def last_run():
    try:
        from models import fiscal
        with db(readonly=True) as conn:
            return fiscal.get_setting(conn, LAST_KEY, "")
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════
#  ضغط الملف — إجراء يدوي صريح
# ══════════════════════════════════════════════════════════════════

def compact():
    """VACUUM: يعيد بناء الملف بلا صفحات محرَّرة.

    يقفل القاعدة طوال التنفيذ ويحتاج مساحة قرص بحجم القاعدة مؤقتاً،
    فلا يُشغَّل تلقائياً — يستدعيه المستخدم من شاشة الصيانة وقت
    الفراغ. يعيد (الحجم قبل، الحجم بعد) بالميجابايت.
    """
    import config
    before = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    checkpoint(truncate=True)
    c = get_connection()
    try:
        c.execute("VACUUM")
    finally:
        c.close()
    after = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    return round(before / 1048576, 1), round(after / 1048576, 1)


def db_stats():
    """أحجام الجداول الكبرى — لتشخيص «لماذا كبرت القاعدة؟»."""
    out = {"tables": [], "db_mb": 0.0, "wal_mb": 0.0}
    try:
        import config
        from pathlib import Path
        p = Path(str(config.DB_PATH))
        if p.exists():
            out["db_mb"] = round(p.stat().st_size / 1048576, 1)
        w = Path(str(p) + "-wal")
        if w.exists():
            out["wal_mb"] = round(w.stat().st_size / 1048576, 1)
    except Exception:
        pass
    try:
        with db(readonly=True) as conn:
            names = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%'")]
            rows = []
            for n in names:
                try:
                    c = conn.execute(f"SELECT COUNT(*) c FROM {n}").fetchone()["c"]
                except Exception:
                    c = 0
                rows.append({"table": n, "rows": c})
            out["tables"] = sorted(rows, key=lambda r: -r["rows"])[:12]
    except Exception:
        pass
    return out


# ══════════════════════════════════════════════════════════════════
#  عامل خلفي يومي
# ══════════════════════════════════════════════════════════════════

class MaintenanceWorker(threading.Thread):
    def __init__(self, interval=EVERY_HOURS * 3600):
        super().__init__(daemon=True, name="JadeiteMaintenance")
        self.interval = interval
        self._stop = threading.Event()
        self.last = {}

    def stop(self):
        self._stop.set()

    def run(self):
        # أول دورة بعد خمس دقائق من الإقلاع — لا نزاحم بدء العمل
        if self._stop.wait(timeout=300):
            return
        while True:
            try:
                self.last = light_maintenance()
            except Exception as e:
                try:
                    from services.health import log_error
                    log_error("MaintenanceWorker", e)
                except Exception:
                    pass
            finally:
                # الخيط الخلفي يملك اتصاله الخاص: نغلقه بعد كل دورة
                # فلا يبقى مفتوحاً طوال اليوم يمنع تقليص WAL.
                try:
                    from database.database import close_thread_connection
                    close_thread_connection()
                except Exception:
                    pass
            if self._stop.wait(timeout=self.interval):
                return


_worker = None


def start_worker(interval=EVERY_HOURS * 3600):
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = MaintenanceWorker(interval)
        _worker.start()
    return _worker


def status():
    return {"last": last_run(), "result": dict(_worker.last) if _worker else {}}
