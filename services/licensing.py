# -*- coding: utf-8 -*-
"""خدمات إدارة المنتج: الإيقاف عن بُعد · النسخ الاحتياطي · التحديثات.

ثلاث خدمات تُحوّل النظام إلى منتج SaaS قابل للإدارة عن بُعد:

* **الترخيص والإيقاف** — التحقق من حالة المصنع سحابياً ومنع الدخول
  فور إيقافه، مع تخزين آخر حالة معروفة محلياً للعمل بلا إنترنت.
* **النسخ الاحتياطي المحلي** — حماية القيود من تلف الجهاز قبل المزامنة.
* **التحديثات** — إشعار بوجود إصدار أحدث عند الإقلاع.
"""
import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import config
from services import tenant

# ══════════════════════════════════════════════════════════════════
# 1) الترخيص والإيقاف عن بُعد
# ══════════════════════════════════════════════════════════════════

LICENSE_CACHE = config.BASE_DIR / "data" / "license_state.json"

# مهلة السماح بلا إنترنت قبل رفض الدخول (بالأيام)
GRACE_DAYS = 14


def _cache_read():
    try:
        if LICENSE_CACHE.exists():
            return json.loads(LICENSE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _cache_write(data):
    try:
        LICENSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LICENSE_CACHE.write_text(json.dumps(data, ensure_ascii=False),
                                 encoding="utf-8")
    except Exception:
        pass


def fetch_status(timeout=10):
    """يجلب حالة المصنع من السحابة: نشط أم موقوف."""
    cfg = tenant.cloud_config()
    tid = tenant.tenant_id()
    if not (cfg["url"] and cfg["key"]):
        return None
    url = (f"{cfg['url'].rstrip('/')}/rest/v1/factories"
           f"?tenant_id=eq.{tid}&select=is_active,name,license_key")
    req = urllib.request.Request(
        url, headers={"apikey": cfg["key"],
                      "Authorization": f"Bearer {cfg['key']}",
                      "x-tenant-id": tid})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rows = json.loads(r.read().decode("utf-8"))
    if not rows:
        # مصنع لم يُسجَّل بعد: يعمل محلياً بلا قيد. الإيقاف قرار صريح
        # من الإدارة (is_active = false) لا نتيجة غياب التسجيل.
        return {"found": False, "active": True,
                "reason": "يعمل محلياً — لم يُسجَّل في السحابة بعد"}
    row = rows[0]
    return {"found": True, "active": bool(row.get("is_active")),
            "name": row.get("name", ""), "reason": ""}


def check_access():
    """يقرّر السماح بالدخول.

    يُحدَّث من السحابة عند توفرها، ويعتمد آخر حالة معروفة عند الانقطاع
    ضمن مهلة سماح — فلا يتعطّل المصنع بسبب انقطاع إنترنت عارض، ولا
    يستمر موقوفٌ بالعمل إلى الأبد.
    """
    cached = _cache_read()
    try:
        st = fetch_status()
        if st is None:                       # السحابة غير مهيّأة أصلاً
            return {"allowed": True, "online": False,
                    "reason": "العمل محلي — السحابة غير مفعّلة"}
        cached = {"active": st["active"], "checked_at": time.time(),
                  "reason": st.get("reason", ""),
                  "registered": bool(st.get("found"))}
        _cache_write(cached)
        # المنع حصراً لمصنع **مسجَّل** وموقوف صراحةً
        if st.get("found") and not st["active"]:
            return {"allowed": False, "online": True,
                    "reason": st.get("reason")
                    or "الحساب موقوف — يرجى مراجعة الإدارة"}
        return {"allowed": True, "online": True, "reason": ""}
    except Exception:
        pass                                  # انقطاع: نعتمد الذاكرة

    if not cached:
        return {"allowed": True, "online": False,
                "reason": "تعذّر التحقق — سيُعاد لاحقاً"}
    if not cached.get("active", True):
        return {"allowed": False, "online": False,
                "reason": "الحساب موقوف — يرجى مراجعة الإدارة"}
    age_days = (time.time() - cached.get("checked_at", 0)) / 86400
    if cached.get("registered") and age_days > GRACE_DAYS:
        return {"allowed": False, "online": False,
                "reason": f"تعذّر التحقق من الترخيص منذ {int(age_days)} يوماً"
                          f" — اتصل بالإنترنت أو راجع الإدارة"}
    return {"allowed": True, "online": False,
            "reason": f"عمل دون اتصال (تحقق قبل {int(age_days)} يوم)"}


def set_factory_active(tenant_id, active, service_key=None):
    """يوقف مصنعاً أو يفعّله — للمدير الأعلى.

    يتطلب مفتاح خدمة (service_role) لأنه يعدّل سجلاً خارج نطاق
    سياسات RLS الخاصة بالمصنع.
    """
    cfg = tenant.cloud_config()
    key = service_key or cfg["key"]
    url = (f"{cfg['url'].rstrip('/')}/rest/v1/factories"
           f"?tenant_id=eq.{tenant_id}")
    req = urllib.request.Request(
        url, data=json.dumps({"is_active": bool(active)}).encode("utf-8"),
        method="PATCH",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status in (200, 204)


# ══════════════════════════════════════════════════════════════════
# 2) النسخ الاحتياطي المحلي الآمن
# ══════════════════════════════════════════════════════════════════

BACKUP_DIR = config.BASE_DIR / "backups" / "auto"
KEEP_COPIES = 60                 # عدد النسخ المحفوظة قبل التدوير
BACKUP_EVERY_SEC = 900           # كل 15 دقيقة


def make_backup(reason="auto"):
    """نسخة كاملة من قاعدة البيانات + العمليات غير المرفوعة.

    تُحفظ في مجلد مستقل داخل الجهاز فتنجو القيود من تلف مفاجئ قبل
    المزامنة. النسخ تُدوَّر تلقائياً فلا تمتلئ القرص.
    """
    from database.database import db
    from services import sync_queue

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"gold_erp_{stamp}_{reason}.db"

    # نسخة متسقة: نأخذها بعد إغلاق أي معاملة مفتوحة
    src = Path(str(config.DB_PATH))
    if not src.exists():
        return None
    try:
        from services.storage import safe_copy_db
        safe_copy_db(src, dest)
    except Exception:
        shutil.copy2(src, dest)

    # ملف مرافق يوثّق ما لم يُرفع بعد
    try:
        with db() as conn:
            pend = sync_queue.pending_batch(conn, limit=10_000)
            stats = sync_queue.stats(conn)
        meta = {
            "created_at": stamp, "reason": reason,
            "tenant_id": tenant.tenant_id(),
            "factory": tenant.factory_name(),
            "queue": stats,
            "unsynced": [{"entity": r["entity"], "op_uuid": r["op_uuid"],
                          "payload": json.loads(r["payload"])}
                         for r in pend],
        }
        dest.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass

    _rotate()
    return str(dest)


def _rotate():
    try:
        files = sorted(BACKUP_DIR.glob("gold_erp_*.db"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP_COPIES:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
    except Exception:
        pass


def list_backups():
    if not BACKUP_DIR.exists():
        return []
    out = []
    for p in sorted(BACKUP_DIR.glob("gold_erp_*.db"),
                    key=lambda x: x.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({"path": str(p), "name": p.name,
                    "size_kb": round(st.st_size / 1024, 1),
                    "when": datetime.fromtimestamp(
                        st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out


class BackupWorker(threading.Thread):
    """خيط خلفي يأخذ نسخة دورية بلا أي تأثير على الواجهة."""

    def __init__(self, interval=BACKUP_EVERY_SEC):
        super().__init__(daemon=True, name="JadeiteBackupWorker")
        self.interval = interval
        self._stop = threading.Event()
        self.last = None

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.wait(timeout=self.interval):
            try:
                self.last = make_backup("auto")
            except Exception:
                pass


_backup_worker = None


def start_backup_worker(interval=BACKUP_EVERY_SEC):
    global _backup_worker
    if _backup_worker is None or not _backup_worker.is_alive():
        _backup_worker = BackupWorker(interval)
        _backup_worker.start()
    return _backup_worker


# ══════════════════════════════════════════════════════════════════
# 3) التحديثات التلقائية
# ══════════════════════════════════════════════════════════════════

APP_VERSION = getattr(config, "APP_VERSION", "1.0.0")


def _ver_tuple(v):
    parts = []
    for p in str(v).strip().split("."):
        try:
            parts.append(int("".join(c for c in p if c.isdigit()) or 0))
        except Exception:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])
