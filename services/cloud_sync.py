# -*- coding: utf-8 -*-
"""عامل المزامنة الخلفي (Background Sync Worker) + محوّل Supabase.

**مبدأ التصميم**: الواجهة لا تنتظر السحابة إطلاقاً. يعمل هذا العامل في
خيط مستقل (daemon) يلتقط حزم الطابور ويرفعها دفعةً واحدة كلما توفر
الإنترنت. وعند الانقطاع لا تظهر أي رسالة خطأ للمستخدم — تتراكم الحزم
محلياً وتُرفع كتلةً عند عودة الاتصال.
"""
import json
import threading
import time as _time
import urllib.error
import urllib.request

from database.database import db
from services import sync_queue, tenant


# ══════════════════════════════════════════════════════════════════
# محوّل السحابة — Supabase (PostgREST)
# ══════════════════════════════════════════════════════════════════

class CloudSetupError(Exception):
    """خطأ تهيئة سحابية برسالة عربية مفهومة بدل رمز HTTP خام."""


def _explain(e, what=""):
    """يترجم أخطاء HTTP إلى سبب واضح وخطوة عملية."""
    code = getattr(e, "code", None)
    if code == 404:
        return CloudSetupError(
            f"الجداول السحابية غير موجودة{(' (' + what + ')') if what else ''}."
            " شغّل المهاجر مرة واحدة:\n"
            "    python tools/cloud_migrate.py --dsn \"postgresql://…\"")
    if code in (401, 403):
        return CloudSetupError(
            "المفتاح غير مصرَّح له. تحقّق من صحة المفتاح، ومن تنفيذ"
            " سياسات RLS في ملف المخطط.")
    if code == 400:
        return CloudSetupError(
            "طلب غير صالح — تحقّق من مطابقة أعمدة الجداول للمخطط.")
    return e


class SupabaseAdapter:
    """يرفع الحزم إلى Supabase عبر واجهة REST.

    يُرفع كل شيء إلى دالة قاعدة بيانات واحدة `ingest_bundle` تُنفَّذ
    داخل **معاملة واحدة على الخادم**، فترفع الفاتورة وقيدها وحركة
    الأطقم معاً أو لا شيء — وهو ما يضمن تطابق الميزانية المحلية
    والسحابية.
    """

    def __init__(self, url, key, timeout=20):
        self.url = self.normalize_url(url)
        self.key = key or ""
        self.timeout = timeout

    def available(self):
        return bool(self.url and self.key)

    @staticmethod
    def normalize_url(url):
        """يضبط رابط المشروع: بلا شرطة أخيرة وبمخطط https."""
        u = (url or "").strip().rstrip("/")
        if u and not u.startswith(("http://", "https://")):
            u = "https://" + u
        return u

    def _post(self, path, body):
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=json.dumps(body, ensure_ascii=False,
                            default=str).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Prefer": "return=minimal",
                # هوية المصنع تُقرأ في سياسات RLS على الخادم
                "x-tenant-id": tenant.effective_tenant_id(),
            }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            raise _explain(e, path.split("/")[-1]) from e

    def push_batch(self, rows):
        """يرفع دفعة حزم. يرفع استثناءً عند أي فشل فتبقى في الطابور."""
        payload = [{
            "p_tenant_id": r["tenant_id"],
            "p_op_uuid": r["op_uuid"],
            "p_entity": r["entity"],
            "p_payload": json.loads(r["payload"]),
        } for r in rows]
        # دالة مخزّنة على Supabase تُنفَّذ داخل معاملة واحدة
        self._post("/rest/v1/rpc/ingest_bundle", {"batch": payload})
        return True

    def list_factories(self):
        """قائمة المصانع المسجّلة — تُستخدم في لوحة المدير الأعلى."""
        req = urllib.request.Request(
            f"{self.url}/rest/v1/factories?select=*&order=created_at.desc",
            headers={"apikey": self.key,
                     "Authorization": f"Bearer {self.key}",
                     "x-tenant-id": tenant.effective_tenant_id()})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def create_user(self, tenant_id, username, password_hash,
                    full_name="", role="owner"):
        """ينشئ حساب صاحب مصنع في السحابة (كلمة المرور مُجزّأة)."""
        self._post("/rest/v1/factory_users",
                   {"tenant_id": tenant_id, "username": username,
                    "password_hash": password_hash,
                    "full_name": full_name, "role": role,
                    "is_active": True})
        return True

    def list_users(self, tenant_id=None):
        q = "?select=*&order=created_at.desc"
        if tenant_id:
            q += f"&tenant_id=eq.{tenant_id}"
        req = urllib.request.Request(
            f"{self.url}/rest/v1/factory_users{q}",
            headers={"apikey": self.key,
                     "Authorization": f"Bearer {self.key}",
                     "x-tenant-id": tenant.effective_tenant_id()})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise _explain(e, "factory_users") from e

    def diagnose(self):
        """فحص تشخيصي يحدّد بدقة ما ينقص قبل الاستخدام."""
        out = {"url": self.url, "reachable": False, "tables": {},
               "rpc": False, "message": ""}
        if not self.available():
            out["message"] = "أدخل رابط السحابة ومفتاحها أولاً"
            return out
        hdr = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
               "x-tenant-id": tenant.effective_tenant_id()}
        for t in ("factories", "sync_bundles", "factory_users",
                  "app_versions"):
            try:
                req = urllib.request.Request(
                    f"{self.url}/rest/v1/{t}?select=*&limit=1", headers=hdr)
                urllib.request.urlopen(req, timeout=self.timeout).read()
                out["tables"][t] = "موجود"
                out["reachable"] = True
            except urllib.error.HTTPError as e:
                out["reachable"] = True
                out["tables"][t] = ("غير موجود" if e.code == 404
                                    else f"محمي/خطأ {e.code}")
            except Exception as e:
                out["tables"][t] = f"تعذّر: {type(e).__name__}"
        try:
            self._post("/rest/v1/rpc/ingest_bundle", {"batch": []})
            out["rpc"] = True
        except Exception:
            out["rpc"] = False
        missing = [k for k, v in out["tables"].items() if v == "غير موجود"]
        if missing:
            out["message"] = ("جداول ناقصة: " + " · ".join(missing)
                              + "\nشغّل: python tools/cloud_migrate.py")
        elif not out["reachable"]:
            out["message"] = "تعذّر الوصول للخادم — تحقّق من الرابط والإنترنت"
        else:
            out["message"] = "السحابة جاهزة"
        return out

    def create_factory(self, tenant_id, name, license_key=""):
        self._post("/rest/v1/factories",
                   {"tenant_id": tenant_id, "name": name,
                    "license_key": license_key, "is_active": True})
        return True


# ══════════════════════════════════════════════════════════════════
# العامل الخلفي
# ══════════════════════════════════════════════════════════════════

class SyncWorker(threading.Thread):
    """خيط خلفي معزول عن الواجهة تماماً.

    * لا يمسّ الواجهة ولا يعرض رسائل — يسجّل حالته داخلياً فقط.
    * يستخدم اتصال قاعدة بيانات خاصاً به فلا يزاحم الشاشات.
    * عند انقطاع الإنترنت ينام ويعاود المحاولة تلقائياً (backoff).
    """

    def __init__(self, on_status=None):
        super().__init__(daemon=True, name="JadeiteSyncWorker")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.on_status = on_status
        self.last_status = {"state": "متوقف", "pending": 0, "sent": 0,
                            "failed": 0, "total": 0, "error": ""}

    # ── التحكم ──
    def stop(self):
        self._stop.set()
        self._wake.set()

    def nudge(self):
        """إيقاظ فوري بعد حفظ عملية جديدة (بلا انتظار الدورة)."""
        self._wake.set()

    # ── الحلقة ──
    def run(self):
        backoff = 1
        while not self._stop.is_set():
            cfg = tenant.cloud_config()
            interval = max(5, cfg.get("interval", 30))
            try:
                if cfg["enabled"]:
                    moved = self._cycle(cfg)
                    backoff = 1
                    if moved:
                        continue          # تابع فوراً ما دامت هناك حزم
                else:
                    self._set("معطّل")
            except Exception as e:
                # انقطاع الإنترنت أو خطأ خادم: صامت تماماً تجاه المستخدم
                self._set("بانتظار الاتصال", error=str(e)[:120])
                backoff = min(backoff * 2, 12)
            self._wake.wait(timeout=interval * backoff)
            self._wake.clear()

    def _cycle(self, cfg):
        adapter = SupabaseAdapter(cfg["url"], cfg["key"])
        if not adapter.available():
            self._set("غير مهيّأ")
            return False
        # قراءة الطابور لا تحتاج قفل كتابة. الصيغة السابقة كانت تفتح
        # BEGIN IMMEDIATE كل بضع ثوانٍ فتُوقف حفظ أي فاتورة ريثما
        # ينتهي الاستعلام — وهو سبب «التعليق» اللحظي عند الحفظ.
        with db(readonly=True) as conn:
            rows = sync_queue.pending_batch(conn)
            st = sync_queue.stats(conn)
        if not rows:
            self._set("متزامن", **st)
            self._maybe_purge()
            return False
        ids = [r["id"] for r in rows]
        try:
            adapter.push_batch(rows)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            with db() as conn:
                sync_queue.mark_failed(conn, ids, e)
            raise
        with db() as conn:
            sync_queue.mark_sent(conn, ids)
            st = sync_queue.stats(conn)
        self._set("يرفع…", **st)
        return True

    def _maybe_purge(self):
        """تنظيف الحزم المرفوعة — مرة كل ست ساعات على الأكثر."""
        now = _time.time()
        if now - getattr(self, "_last_purge", 0) < 6 * 3600:
            return
        self._last_purge = now
        try:
            with db() as conn:
                sync_queue.purge_sent(conn)
        except Exception:
            pass          # التنظيف رفاهية، لا يعطّل المزامنة

    def _set(self, state, error="", **counts):
        """يحدّث حالة العامل. يقبل أي مفاتيح إحصائية من `stats()`
        (pending · sent · failed · total) بلا كسر عند إضافة مفاتيح
        جديدة مستقبلاً."""
        self.last_status.update({"state": state, "error": error})
        for k, v in counts.items():
            if v is not None:
                self.last_status[k] = v
        if self.on_status:
            try:
                self.on_status(dict(self.last_status))
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
# مثيل واحد للتطبيق
# ══════════════════════════════════════════════════════════════════

_worker = None


def start_worker(on_status=None):
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = SyncWorker(on_status)
        _worker.start()
    return _worker


def worker():
    return _worker


def nudge():
    if _worker is not None:
        _worker.nudge()


def status():
    return dict(_worker.last_status) if _worker else {
        "state": "متوقف", "pending": 0, "sent": 0, "failed": 0, "error": ""}
