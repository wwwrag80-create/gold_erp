# -*- coding: utf-8 -*-
"""هيكلية الحفظ والنسخ الاحتياطي (TreeSoft).

**فصل التطبيق عن البيانات**: لا يُحفظ شيء داخل مجلد التثبيت ولا على
سطح المكتب. البيانات في مسار ثابت خارج التطبيق، فحذف الملف التنفيذي
أو تحديثه لا يمسّها إطلاقاً — والنسخة الجديدة تتعرّف عليها تلقائياً.

**ترتيب اختيار مجلد البيانات**:
    1. `D:/TreeSoft_System/Data`  — إن وُجد القرص D
    2. `%APPDATA%/TreeSoft`       — بديل على ويندوز
    3. `~/.treesoft`              — أنظمة أخرى

**النسخ الاحتياطي — النظام الوحيد (4.29)**: كل مصنع يحفظ بياناته على
جهازه ولا يُرفع منها شيء. خيط خلفي ينسخ كل 30 دقيقة (وعند الإغلاق،
وعند الطلب) إلى `D:/TreeSoft_Backups/<المصنع>` (أو C كخطة بديلة)،
والمجلد **مخفي** عبر `ctypes`، ويُحتفظ **بآخر 20 نسخة**.

* **النسخة المطابقة لا تُحفظ مرتين**: إن لم يتغيّر شيء منذ آخر نسخة
  تُحذف الجديدة — فالعشرون عشرون حالةً مختلفة لا عشرون نسخةً من
  ليلةٍ لم يعمل فيها أحد، ولا تدهس نسخةُ الليل الفارغة نسخَ النهار.
* **كل استرجاع قابلٌ للتراجع**: قبل استبدال البيانات تُؤخذ نسخة
  «قبل الاسترجاع» تظهر في القائمة نفسها.

**الاسترداد التلقائي**: عند الإقلاع، إن كانت قاعدة البيانات مفقودة
تُسحب أحدث نسخة متوفرة وتُستعاد بسلاسة.
"""
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

APP_FOLDER = "TreeSoft"
BACKUP_FOLDER = "TreeSoft_Backups"
SYSTEM_FOLDER = "TreeSoft_System"

BACKUP_EVERY_SEC = 30 * 60        # كل 30 دقيقة
KEEP_LAST = 20                    # آخر 20 نسخة (حالات مختلفة)
KEEP_DAYS = KEEP_LAST             # توافقٌ مع من يقرأ الاسم القديم

# أسباب النسخ كما تُعرض للمستخدم
REASONS = {
    "auto": "تلقائية", "manual": "يدوية", "exit": "عند الإغلاق",
    "before_restore": "قبل الاسترجاع", "before_reset": "قبل التهيئة",
    "before_update": "قبل التحديث", "login": "عند الدخول",
}
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


def _digest(path):
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_backup(reason="auto", src=None, force=False, purge=True):
    """نسخة كاملة من قاعدة البيانات + الإعدادات.

    النسخة التي لا تختلف عن أحدث نسخةٍ سابقة تُحذف ويُعاد مسار
    السابقة — إلا إن طُلبت صراحةً (`force`) أو كانت قبل استرجاع
    أو تهيئة (تُحفظ دائماً لأنها ما يُرجَع إليه عند التراجع).
    """
    source = Path(src) if src else db_path()
    if not source.exists():
        return None
    dest_dir = backup_dir()
    prev = list_backups()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{DB_NAME}_{stamp}_{reason}.bak"
    n = 1
    while dest.exists():                       # نسختان في الثانية نفسها
        n += 1
        dest = dest_dir / f"{DB_NAME}_{stamp}-{n}_{reason}.bak"
    try:
        safe_copy_db(source, dest)
    except Exception:
        shutil.copy2(source, dest)          # بديل عند أي تعذّر
    keep_always = force or reason.startswith("before_") or reason == "manual"
    if prev and not keep_always:
        try:
            if _digest(dest) == _digest(prev[0]["path"]):
                dest.unlink(missing_ok=True)
                return prev[0]["path"]
        except Exception:
            pass
    # الإعدادات المرافقة
    for name in ("tenant.json", "nav_layout.json"):
        f = data_dir() / name
        if f.exists():
            try:
                shutil.copy2(f, dest_dir / f"{name}_{stamp}.bak")
            except Exception:
                pass
    if purge:
        purge_old()
    return str(dest)


def _stamp_of(name):
    """الختم الزمني من اسم النسخة: gold_erp.db_<ختم>_<سبب>.bak"""
    core = name[len(DB_NAME) + 1:-4] if name.endswith(".bak") else name
    parts = core.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else core


def _reason_of(name):
    core = name[len(DB_NAME) + 1:-4] if name.endswith(".bak") else name
    parts = core.split("_", 2)
    return parts[2] if len(parts) > 2 else "auto"


def purge_old(keep=KEEP_LAST):
    """يُبقي آخر `keep` نسخة ويحذف ما قبلها مع ملفاتها المرافقة."""
    removed = 0
    try:
        rows = list_backups()
        for r in rows[keep:]:
            try:
                Path(r["path"]).unlink(missing_ok=True)
                removed += 1
                st = _stamp_of(r["name"]).split("-")[0]
                for comp in backup_dir().glob(f"*.json_{st}.bak"):
                    comp.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass
    return removed


def list_backups():
    """النسخ الأحدث أولاً — مع سببها وتاريخها وحجمها."""
    out = []
    try:
        for f in sorted(backup_dir().glob(f"{DB_NAME}_*.bak"),
                        key=lambda p: (p.stat().st_mtime, p.name),
                        reverse=True):
            st = f.stat()
            reason = _reason_of(f.name)
            out.append({
                "path": str(f), "name": f.name, "reason": reason,
                "reason_label": REASONS.get(reason, reason),
                "size_kb": round(st.st_size / 1024, 1),
                "when": datetime.fromtimestamp(st.st_mtime)
                .strftime("%Y-%m-%d %H:%M")})
    except Exception:
        pass
    return out


def verify_backup(path):
    """هل النسخة سليمة وقابلة للاسترجاع؟ يعيد (سليمة، سبب)."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            ok = con.execute("PRAGMA quick_check").fetchone()[0]
            if str(ok).lower() != "ok":
                return False, f"الملف تالف: {ok}"
            n = con.execute("SELECT COUNT(*) FROM sqlite_master"
                            " WHERE type='table'").fetchone()[0]
            if n < 5:
                return False, "النسخة لا تحوي جداول النظام"
            try:
                e = con.execute("SELECT COUNT(*) FROM journal_entries"
                                " WHERE is_deleted=0").fetchone()[0]
            except Exception:
                e = 0
            return True, f"{e:,} قيد"
        finally:
            con.close()
    except Exception as ex:
        return False, str(ex)[:150]


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
    """يسترجع نسخة محددة — ويحفظ الحالية أولاً نسخةً «قبل الاسترجاع».

    الاستبدال عبر واجهة `sqlite3.backup` **داخل** ملف القاعدة القائم لا
    بنسخ الملف فوقه: الاتصالات المفتوحة تقرأ المحتوى الجديد مباشرة،
    ولا يبقى ملف WAL قديمٌ يخلط بيانات النسختين.
    """
    import sqlite3
    dst = Path(target) if target else db_path()
    src = Path(backup_path)
    if not src.exists():
        raise FileNotFoundError("النسخة غير موجودة")
    ok, why = verify_backup(src)
    if not ok:
        raise ValueError(f"لا تُسترجع هذه النسخة — {why}")
    before = None
    if dst.exists():
        # بلا تدوير الآن: لو كانت المسترجَعة أقدمَ العشرين لحذفها
        # التدوير قبل قراءتها. يُدوَّر بعد اكتمال الاسترجاع.
        before = make_backup("before_restore", src=dst, force=True,
                             purge=False)
    try:
        from database.database import close_thread_connection
        close_thread_connection()
    except Exception:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    s_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d_con = sqlite3.connect(str(dst), timeout=30)
    try:
        s_con.backup(d_con, pages=256, sleep=0.002)
        d_con.commit()
    finally:
        d_con.close()
        s_con.close()
    purge_old()
    return {"restored": src.name, "before": before}


def info():
    """معلومات المسارات — لعرضها في شاشة الصيانة."""
    try:
        import config
        base = str(config.BASE_DIR)
    except Exception:
        base = ""
    return {
        # مجلد العمل الفعلي: هو ما يحدّد مكان القاعدة، وقد يختلف عن
        # `data_dir` أدناه. إظهاره يجيب سؤال «أين بياناتي؟» بلا تخمين.
        "base_dir": base,
        "data_dir": str(data_dir()),
        "backup_dir": str(backup_dir()),
        "db_path": str(db_path()),
        "db_exists": db_path().exists(),
        "db_size_kb": (round(db_path().stat().st_size / 1024, 1)
                       if db_path().exists() else 0),
        "backups": len(list_backups()),
        "keep_last": KEEP_LAST,
        "keep_days": KEEP_DAYS,
        "interval_min": BACKUP_EVERY_SEC // 60,
        "frozen": bool(getattr(sys, "frozen", False)),
    }
