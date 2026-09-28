# -*- coding: utf-8 -*-
"""الترخيص — ما بقي من السحابة: المدير يوقف البرنامج عن أي مصنع.

**منذ 4.29 لا تُرفع بيانات مصنعٍ ولا تُستقبل.** كل مصنع يعمل على جهازه
وحده، ويحفظ نسخه عليه (`services/storage.py`). والذي يمرّ عبر الشبكة
شيئان فقط، وكلاهما عن **الحساب** لا عن البيانات:

1. عند الدخول: التحقق من اسم المستخدم وكلمة المرور وحالة الحساب.
2. أثناء العمل: سؤالٌ دوري صغير «هل الحساب ما زال نشطاً؟» — فإن أوقفه
   المدير توقّف البرنامج عند العميل خلال دقائق، لا عند الدخول القادم
   وحده (الذي قد يتأخر أياماً والجهاز لا يُطفأ).

بلا إنترنت يستمر العمل كما هو؛ وآخر حالةٍ معروفة تُحفظ على الجهاز،
فحسابٌ أُوقف لا يدخل ولو قُطع الإنترنت بعد إيقافه.
"""
import threading
import time
from pathlib import Path

import config

# كل كم يُسأل عن حالة الحساب أثناء العمل
CHECK_EVERY_SEC = 20 * 60

# مجلد النسخ القديم (قبل توحيد النسخ في storage) — يُمسح عند التهيئة
BACKUP_DIR = Path(str(config.BASE_DIR)) / "backups" / "auto"

APP_VERSION = getattr(config, "APP_VERSION", "1.0.0")


# ══════════════════════════════════════════════════════════════════
#  حالة الحساب
# ══════════════════════════════════════════════════════════════════

def account_status(username, timeout=10):
    """حالة الحساب من السحابة: {online, known, active}.

    * `online=False`: تعذّر السؤال (لا إنترنت) — لا يُتخذ أي قرار.
    * `known=False`: حسابٌ محلي لا سحابي (مدير النسخة الأصلية).
    تُحدَّث الذاكرة المحلية بالحالة، فالدخول بلا اتصال يعرفها أيضاً.
    """
    from services import cloud_auth
    name = (username or "").strip()
    if not name:
        return {"online": False, "known": False, "active": True}
    try:
        row = cloud_auth.fetch_user(name, timeout=timeout)
    except Exception:
        return {"online": False, "known": False, "active": True}
    if not row:
        return {"online": True, "known": False, "active": True}
    active = bool(row.get("is_active", True))
    try:
        cloud_auth._cache_put(name, row)
    except Exception:
        pass
    return {"online": True, "known": True, "active": active}


class AccountGuard(threading.Thread):
    """خيطٌ خلفي يسأل عن حالة الحساب كل `interval` ثانية.

    عند الإيقاف يُنادى `on_suspended()` مرةً واحدة — والواجهة تتولّى
    العرض والإغلاق على خيطها هي. لا يُرسل شيئاً عن بيانات المصنع.
    """

    def __init__(self, username, on_suspended, interval=CHECK_EVERY_SEC,
                 first_delay=90):
        super().__init__(daemon=True, name="AccountGuard")
        self.username = username
        self.on_suspended = on_suspended
        self.interval = interval
        self.first_delay = first_delay
        self._stop = threading.Event()
        self.last = {"when": "", "online": False, "active": True}

    def stop(self):
        self._stop.set()

    def check_now(self):
        st = account_status(self.username)
        self.last = dict(st, when=time.strftime("%Y-%m-%d %H:%M"))
        if st["online"] and st["known"] and not st["active"]:
            self._stop.set()
            try:
                self.on_suspended()
            except Exception:
                pass
        return st

    def run(self):
        if self._stop.wait(timeout=self.first_delay):
            return
        while not self._stop.is_set():
            self.check_now()
            if self._stop.wait(timeout=self.interval):
                return


# ══════════════════════════════════════════════════════════════════
#  إيقاف مصنع كامل — للمدير
# ══════════════════════════════════════════════════════════════════

def factory_accounts(users, tenant_id):
    """حسابات المصنع الواحد من قائمة الحسابات."""
    return [u for u in (users or [])
            if (u.get("tenant_id") or "") == (tenant_id or "")
            and u.get("role") != "super_admin"]


def set_factory_active(tenant_id, active, users=None):
    """يوقف مصنعاً (كل حساباته) أو يفعّله — للمدير العام.

    الإيقاف على مستوى الحساب لأن الحساب هو ما يُسأل عنه عند الدخول
    وأثناء العمل؛ فإيقاف كل حسابات المصنع يوقف البرنامج عنده كله.
    يعيد عدد الحسابات التي تغيّرت.
    """
    from services import cloud_auth
    if not tenant_id:
        raise ValueError("حدّد المصنع")
    rows = factory_accounts(
        users if users is not None else cloud_auth.list_users(), tenant_id)
    if not rows:
        raise ValueError("لا حسابات لهذا المصنع")
    n = 0
    for u in rows:
        if bool(u.get("is_active")) != bool(active):
            cloud_auth.set_user_active(u.get("username"), bool(active))
            n += 1
    return n


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
