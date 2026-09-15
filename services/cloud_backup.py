# -*- coding: utf-8 -*-
"""النسخ الاحتياطي السحابي والاسترجاع.

**المشكلة التي يحلّها**: النسخ المحلية تضيع بضياع الجهاز. هذه الوحدة
ترفع نسخة كاملة من قاعدة بيانات المصنع إلى تخزين سحابي مرتبط بهويته،
فيستطيع استرجاع محاسبته كاملةً على أي جهاز جديد — حتى لو حُذف البرنامج
أو تعطّل القرص.

كل مصنع يرى نسخه وحده (المسار يبدأ بهوية المصنع + سياسات التخزين).
"""
import gzip
import json
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import config
from services import tenant

BUCKET = "factory-backups"
# كل 10 دقائق: الرفع كل 30 ثانية كان ينسخ القاعدة ويضغطها
# ويرفعها 120 مرة في الساعة — يُثقل القرص والشبكة ويُجمّد الواجهة.
# ومع الرفع عند كل إغلاق، لا تُفقد بيانات تُذكر.
UPLOAD_EVERY_SEC = 600
KEEP_CLOUD = 20                  # عدد النسخ المحفوظة سحابياً


def _cfg():
    cfg = tenant.cloud_config()
    if not (cfg["url"] and cfg["key"]):
        raise RuntimeError("إعدادات السحابة غير مكتملة")
    return cfg["url"].rstrip("/"), cfg["key"]


def _headers(key, content_type=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "x-tenant-id": tenant.effective_tenant_id()}
    if content_type:
        h["Content-Type"] = content_type
    return h


# ══════════════════════════════════════════════════════════════════
# الرفع
# ══════════════════════════════════════════════════════════════════

def _snapshot():
    """نسخة مضغوطة متسقة من قاعدة البيانات + بيان بمحتواها."""
    src = Path(str(config.DB_PATH))
    if not src.exists():
        raise FileNotFoundError("لا توجد قاعدة بيانات لنسخها")
    tmp = Path(tempfile.mkdtemp(prefix="jadeite_bk_"))
    raw = tmp / "gold_erp.db"
    # نسخ بواجهة SQLite: لا يقفل القاعدة على الواجهة
    try:
        from services.storage import safe_copy_db
        safe_copy_db(src, raw)
    except Exception:
        shutil.copy2(src, raw)
    gz = tmp / "backup.db.gz"
    with open(raw, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo)
    raw.unlink(missing_ok=True)
    return gz, tmp


def upload(reason="auto", timeout=180):
    """يرفع نسخة كاملة إلى التخزين السحابي تحت هوية المصنع."""
    url, key = _cfg()
    tid = tenant.effective_tenant_id()
    gz, tmp = _snapshot()
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{tid}/{stamp}_{reason}.db.gz"
        data = gz.read_bytes()
        req = urllib.request.Request(
            f"{url}/storage/v1/object/{BUCKET}/{name}",
            data=data, method="POST",
            headers={**_headers(key, "application/gzip"),
                     "x-upsert": "true"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok = r.status in (200, 201)
        return {"ok": ok, "name": name,
                "size_kb": round(len(data) / 1024, 1)}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                f"مجلد التخزين «{BUCKET}» غير موجود في السحابة.\n"
                f"أنشئه من: Supabase → Storage → New bucket") from e
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def list_cloud(tenant_id=None, timeout=30):
    """قائمة النسخ السحابية لهذا المصنع (أو لمصنع محدد للمدير)."""
    url, key = _cfg()
    tid = tenant_id or tenant.effective_tenant_id()
    body = {"prefix": f"{tid}/", "limit": 100,
            "sortBy": {"column": "created_at", "order": "desc"}}
    req = urllib.request.Request(
        f"{url}/storage/v1/object/list/{BUCKET}",
        data=json.dumps(body).encode("utf-8"), method="POST",
        headers=_headers(key, "application/json"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rows = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    out = []
    for it in rows or []:
        nm = it.get("name", "")
        meta = it.get("metadata") or {}
        out.append({"name": f"{tid}/{nm}", "file": nm,
                    "when": (it.get("created_at") or "")[:19].replace("T", " "),
                    "size_kb": round((meta.get("size") or 0) / 1024, 1)})
    return out


# ══════════════════════════════════════════════════════════════════
# الاسترجاع
# ══════════════════════════════════════════════════════════════════

def download(object_name, timeout=180):
    """ينزّل نسخة سحابية ويفكّ ضغطها."""
    url, key = _cfg()
    req = urllib.request.Request(
        f"{url}/storage/v1/object/{BUCKET}/{object_name}",
        headers=_headers(key))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        blob = r.read()
    tmp = Path(tempfile.mkdtemp(prefix="jadeite_rs_"))
    gz = tmp / "restore.db.gz"
    gz.write_bytes(blob)
    out = tmp / "restored.db"
    with gzip.open(gz, "rb") as fi, open(out, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    gz.unlink(missing_ok=True)
    return out, tmp


def restore(object_name):
    """يستبدل قاعدة البيانات الحالية بنسخة سحابية.

    يحفظ الحالية جانباً أولاً — فإن كان الاسترجاع خطأً أمكن التراجع.
    يتطلب إعادة تشغيل النظام بعده.
    """
    src, tmp = download(object_name)
    try:
        # تحقق أن الملف قاعدة بيانات سليمة قبل استبدال أي شيء
        import sqlite3
        con = sqlite3.connect(str(src))
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM sqlite_master"
                " WHERE type='table'").fetchone()[0]
            if n < 5:
                raise ValueError("الملف المُنزَّل ليس قاعدة بيانات صالحة")
        finally:
            con.close()

        dst = Path(str(config.DB_PATH))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            keep = dst.with_name(
                f"before_restore_{datetime.now():%Y%m%d_%H%M%S}.db")
            shutil.copy2(dst, keep)
        # إزالة ملفات WAL لئلا تختلط بالقاعدة الجديدة
        for ext in ("-wal", "-shm"):
            Path(str(dst) + ext).unlink(missing_ok=True)
        shutil.copy2(src, dst)
        return {"ok": True, "restored_from": object_name}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════
# العامل الخلفي
# ══════════════════════════════════════════════════════════════════

class CloudBackupWorker(threading.Thread):
    """يرفع نسخة دورية بصمت — لا يعطّل الواجهة ولا يزعج المستخدم."""

    def __init__(self, interval=UPLOAD_EVERY_SEC):
        super().__init__(daemon=True, name="JadeiteCloudBackup")
        self.interval = interval
        self._stop = threading.Event()
        self.last = {"when": "", "ok": False, "error": ""}

    def stop(self):
        self._stop.set()

    @staticmethod
    def _fingerprint():
        """بصمة سريعة لحالة القاعدة — نرفع فقط عند تغيّرها."""
        try:
            p = Path(str(config.DB_PATH))
            st = p.stat()
            return f"{st.st_size}:{int(st.st_mtime)}"
        except Exception:
            return ""

    def run(self):
        # أول رفعة بعد 20 ثانية من الإقلاع
        if self._stop.wait(timeout=20):
            return
        last_fp = ""
        while True:
            try:
                fp = self._fingerprint()
                if fp and fp == last_fp:
                    # لا تغيير منذ آخر رفعة — نوفّر الشبكة
                    if self._stop.wait(timeout=self.interval):
                        return
                    continue
                r = upload("auto")
                last_fp = fp
                self.last = {"when": time.strftime("%Y-%m-%d %H:%M"),
                             "ok": bool(r.get("ok")), "error": ""}
            except Exception as e:
                self.last = {"when": time.strftime("%Y-%m-%d %H:%M"),
                             "ok": False, "error": str(e)[:150]}
            if self._stop.wait(timeout=self.interval):
                return


_worker = None


def start_worker(interval=UPLOAD_EVERY_SEC):
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = CloudBackupWorker(interval)
        _worker.start()
    return _worker


def status():
    return dict(_worker.last) if _worker else {
        "when": "", "ok": False, "error": "لم يبدأ بعد"}


# ══════════════════════════════════════════════════════════════════
# الاسترجاع التلقائي عند أول تشغيل لنسخة جديدة
# ══════════════════════════════════════════════════════════════════

def local_is_empty():
    """هل قاعدة البيانات المحلية جديدة/فارغة من العمليات؟

    نفحص وجود حركات فعلية لا مجرد الجداول، لأن النظام يُنشئ جداوله
    وشجرة حساباته تلقائياً عند أول إقلاع.
    """
    from database.database import db
    try:
        with db() as conn:
            n = conn.execute(
                "SELECT COUNT(*) c FROM journal_entries").fetchone()["c"]
        return int(n or 0) == 0
    except Exception:
        return True


def auto_restore_if_needed(on_progress=None):
    """يسترجع بيانات المصنع تلقائياً على أي نسخة جديدة.

    **هذا ما يجعل التحديث بسيطاً**: يحذف صاحب المصنع النسخة القديمة،
    يشغّل الجديدة، فتلتقط آخر نسخة سحابية لمصنعه وتستعيد محاسبته
    كاملةً — بلا برنامج تحديث ولا خطوات يدوية.

    لا يفعل شيئاً إن كانت هناك بيانات محلية أصلاً (فلا يمسح عمل أحد).
    """
    try:
        if not local_is_empty():
            return {"done": False, "reason": "توجد بيانات محلية"}
        if on_progress:
            on_progress("البحث عن نسخة سحابية…")
        items = list_cloud()
        if not items:
            return {"done": False, "reason": "لا توجد نسخة سحابية"}
        latest = items[0]                      # الأحدث أولاً
        if on_progress:
            on_progress(f"استرجاع {latest['file']}…")
        restore(latest["name"])
        return {"done": True, "file": latest["file"],
                "when": latest.get("when", "")}
    except Exception as e:
        return {"done": False, "reason": str(e)[:150]}
