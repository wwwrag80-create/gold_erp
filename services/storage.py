# -*- coding: utf-8 -*-
"""هيكلية الحفظ والنسخ الاحتياطي (TreeSoft).

**فصل التطبيق عن البيانات**: لا يُحفظ شيء داخل مجلد التثبيت ولا على
سطح المكتب. البيانات في مسار ثابت خارج التطبيق، فحذف الملف التنفيذي
أو تحديثه لا يمسّها إطلاقاً — والنسخة الجديدة تتعرّف عليها تلقائياً.

**ترتيب اختيار مجلد البيانات**:
    1. `D:/TreeSoft_System/Data`  — إن وُجد القرص D
    2. `%APPDATA%/TreeSoft`       — بديل على ويندوز
    3. `~/.treesoft`              — أنظمة أخرى

**النسخ الاحتياطي**: خيط خلفي ينسخ كل 30 دقيقة إلى
`D:/TreeSoft_Backups` (أو C كخطة بديلة)، والمجلد **مخفي** عبر
`ctypes`، ويُحتفظ بنسخ آخر 3 أيام فقط.

**الاسترداد التلقائي**: عند الإقلاع، إن كانت قاعدة البيانات مفقودة
تُسحب أحدث نسخة متوفرة وتُستعاد بسلاسة.
"""
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

APP_FOLDER = "TreeSoft"
BACKUP_FOLDER = "TreeSoft_Backups"
SYSTEM_FOLDER = "TreeSoft_System"

BACKUP_EVERY_SEC = 30 * 60        # كل 30 دقيقة
KEEP_DAYS = 3                     # نسخ آخر 3 أيام
DB_NAME = "gold_erp.db"


# ══════════════════════════════════════════════════════════════════
# 1) فصل التطبيق عن البيانات
# ══════════════════════════════════════════════════════════════════

def _drive_exists(letter):
    """هل القرص موجود وقابل للكتابة؟"""
    if os.name != "nt":
        return False
    root = Path(f"{letter}:/")
    try:
        if not root.exists():
            return False
        probe = root / f".{APP_FOLDER}_probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def data_dir():
    """مجلد البيانات الثابت — خارج مجلد التطبيق دائماً."""
    if _drive_exists("D"):
        d = Path("D:/") / SYSTEM_FOLDER / "Data"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
        d = base / APP_FOLDER
    else:
        d = Path.home() / ".treesoft"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_dir():
    """مجلد النسخ الاحتياطي — القرص D أولاً، وإلا C.

    مجلد فرعي لكل مصنع فلا تختلط نسخه بنسخ غيره.
    """
    sub = ""
    try:
        from services.tenant_db import active_tenant
        t = active_tenant()
        if t:
            sub = "".join(c for c in str(t) if c.isalnum() or c in "-_")[:64]
    except Exception:
        pass
    if _drive_exists("D"):
        d = Path("D:/") / BACKUP_FOLDER
    elif os.name == "nt":
        d = Path("C:/") / BACKUP_FOLDER
    else:
        d = Path.home() / f".{BACKUP_FOLDER.lower()}"
    d.mkdir(parents=True, exist_ok=True)
    hide_directory(d)
    if sub:
        d = d / sub
        d.mkdir(parents=True, exist_ok=True)
    return d


def db_path():
    """مسار قاعدة البيانات **النشطة** — مسار المصنع الحالي.

    كان يُرجع مساراً خاصاً به لا يعرف عزل المصانع، فيعمل النسخ
    الاحتياطي على ملف غير موجود ولا يُنسخ شيء إطلاقاً — خطأ صامت
    خطير: المستخدم يظن بياناته محفوظة وهي ليست كذلك.
    """
    try:
        import config
        return Path(str(config.DB_PATH))
    except Exception:
        return data_dir() / DB_NAME


# ══════════════════════════════════════════════════════════════════
# 2) إخفاء المجلد (ويندوز)
# ══════════════════════════════════════════════════════════════════

FILE_ATTRIBUTE_HIDDEN = 0x02


def hide_directory(path):
    """يُخفي المجلد عن المستخدم — ترتيباً واحترافية."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        ok = ctypes.windll.kernel32.SetFileAttributesW(
            str(path), FILE_ATTRIBUTE_HIDDEN)
        return bool(ok)
    except Exception:
        return False


def unhide_directory(path):
    """يُظهر المجلد عند الحاجة لمراجعته يدوياً."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetFileAttributesW(
            str(path), 0x80))          # FILE_ATTRIBUTE_NORMAL
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# 3) النسخ الاحتياطي
# ══════════════════════════════════════════════════════════════════

def safe_copy_db(source, dest):
    """ينسخ قاعدة البيانات بواجهة SQLite لا بنسخ الملف.

    **لماذا**: `shutil.copy2` يقرأ الملف كتلةً واحدة فيتنازع مع
    الواجهة على القفل، ويُنتج نسخة تالفة إن جرت كتابة أثناءه. واجهة
    `Connection.backup` تنسخ على دفعات صغيرة وتُفلت القفل بينها —
    فلا تتجمّد الواجهة ولا تتلف النسخة.
    """
    import sqlite3
    src_con = sqlite3.connect(f"file:{source}?mode=ro", uri=True,
                              timeout=5)
    try:
        dst_con = sqlite3.connect(str(dest))
        try:
            # 64 صفحة لكل دفعة، مع تنفّس 2 مللي ثانية بينها
            src_con.backup(dst_con, pages=64, sleep=0.002)
        finally:
            dst_con.close()
    finally:
        src_con.close()
    return dest


def make_backup(reason="auto", src=None):
    """نسخة كاملة من قاعدة البيانات + الإعدادات."""
    source = Path(src) if src else db_path()
    if not source.exists():
        return None
    dest_dir = backup_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{DB_NAME}_{stamp}_{reason}.bak"
    try:
        safe_copy_db(source, dest)
    except Exception:
        shutil.copy2(source, dest)          # بديل عند أي تعذّر
    # الإعدادات المرافقة
    for name in ("tenant.json", "auth_cache.json", "admin_token.json",
                 "nav_layout.json"):
        f = data_dir() / name
        if f.exists():
            try:
                shutil.copy2(f, dest_dir / f"{name}_{stamp}.bak")
            except Exception:
                pass
    purge_old()
    return str(dest)


def purge_old(keep_days=KEEP_DAYS):
    """يحذف النسخ الأقدم من المدة المحددة — توفيراً للمساحة."""
    cutoff = time.time() - keep_days * 86400
    removed = 0
    try:
        for f in backup_dir().glob("*.bak"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                pass
    except Exception:
        pass
    return removed


def list_backups():
    out = []
    try:
        for f in sorted(backup_dir().glob(f"{DB_NAME}_*.bak"),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            st = f.stat()
            out.append({
                "path": str(f), "name": f.name,
                "size_kb": round(st.st_size / 1024, 1),
                "when": datetime.fromtimestamp(st.st_mtime)
                .strftime("%Y-%m-%d %H:%M")})
    except Exception:
        pass
    return out


class BackupWorker(threading.Thread):
    """خيط خلفي ينسخ تلقائياً بلا تدخل المستخدم ولا تعطيل الواجهة."""

    def __init__(self, interval=BACKUP_EVERY_SEC):
        super().__init__(daemon=True, name="TreeSoftBackup")
        self.interval = interval
        self._stop = threading.Event()
        self.last = {"when": "", "ok": False, "path": "", "error": ""}

    def stop(self):
        self._stop.set()

    def run(self):
        # أول نسخة بعد دقيقة من الإقلاع
        if self._stop.wait(timeout=60):
            return
        while True:
            try:
                p = make_backup("auto")
                self.last = {"when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                             "ok": bool(p), "path": p or "", "error": ""}
            except Exception as e:
                self.last = {"when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                             "ok": False, "path": "", "error": str(e)[:150]}
            if self._stop.wait(timeout=self.interval):
                return


_worker = None


def start_backup_worker(interval=BACKUP_EVERY_SEC):
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = BackupWorker(interval)
        _worker.start()
    return _worker


def status():
    return dict(_worker.last) if _worker else {
        "when": "", "ok": False, "path": "", "error": "لم يبدأ بعد"}


# ══════════════════════════════════════════════════════════════════
# 4) الاسترداد التلقائي
# ══════════════════════════════════════════════════════════════════

def auto_recover(target=None):
    """يستعيد أحدث نسخة إن كانت قاعدة البيانات مفقودة.

    يُستدعى **قبل** تهيئة قاعدة البيانات في `main.py`، فيلتقط حالة
    حذف الملف بالخطأ أو تلف القرص ويعيد آخر نسخة سليمة تلقائياً.
    """
    dst = Path(target) if target else db_path()
    if dst.exists() and dst.stat().st_size > 0:
        return {"recovered": False, "reason": "قاعدة البيانات موجودة"}
    backups = list_backups()
    if not backups:
        return {"recovered": False, "reason": "لا توجد نسخة احتياطية"}
    latest = backups[0]
    try:
        # تحقق من سلامة النسخة قبل اعتمادها
        import sqlite3
        con = sqlite3.connect(latest["path"])
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM sqlite_master"
                " WHERE type='table'").fetchone()[0]
            if n < 5:
                return {"recovered": False, "reason": "النسخة غير صالحة"}
        finally:
            con.close()
        dst.parent.mkdir(parents=True, exist_ok=True)
        for ext in ("-wal", "-shm"):
            Path(str(dst) + ext).unlink(missing_ok=True)
        shutil.copy2(latest["path"], dst)
        return {"recovered": True, "from": latest["name"],
                "when": latest["when"]}
    except Exception as e:
        return {"recovered": False, "reason": str(e)[:150]}


def restore(backup_path, target=None):
    """استرجاع يدوي لنسخة محددة (يحفظ الحالية جانباً أولاً)."""
    dst = Path(target) if target else db_path()
    src = Path(backup_path)
    if not src.exists():
        raise FileNotFoundError("النسخة غير موجودة")
    # يجب إغلاق اتصال هذا الخيط قبل استبدال الملف، وإلا بقي يقرأ من
    # الملف القديم (أو من WAL محذوف) فتظهر بيانات مختلطة بعد الاسترجاع.
    try:
        from database.database import close_thread_connection
        close_thread_connection()
    except Exception:
        pass
    if dst.exists():
        keep = dst.with_name(
            f"before_restore_{datetime.now():%Y%m%d_%H%M%S}.db")
        shutil.copy2(dst, keep)
    for ext in ("-wal", "-shm"):
        Path(str(dst) + ext).unlink(missing_ok=True)
    shutil.copy2(src, dst)
    return True


def info():
    """معلومات المسارات — لعرضها في شاشة الصيانة."""
    return {
        "data_dir": str(data_dir()),
        "backup_dir": str(backup_dir()),
        "db_path": str(db_path()),
        "db_exists": db_path().exists(),
        "db_size_kb": (round(db_path().stat().st_size / 1024, 1)
                       if db_path().exists() else 0),
        "backups": len(list_backups()),
        "keep_days": KEEP_DAYS,
        "interval_min": BACKUP_EVERY_SEC // 60,
        "frozen": bool(getattr(sys, "frozen", False)),
    }
