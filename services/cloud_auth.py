# -*- coding: utf-8 -*-
"""التحقق من الهوية وإدارة الحسابات — مصدر واحد نظيف.

**المعمارية**:
* كل العمليات الإدارية تمر بدوال على الخادم (`cloud/admin_rpc.sql`)
  تتحقق من الرمز الإداري بنفسها — فلا يحمل الملف التنفيذي أي مفتاح
  خطير، ولا يستطيع العملاء إنشاء حسابات أو حذفها.
* الدخول يُتحقق سحابياً ثم يُحفظ محلياً، فيعمل المصنع بلا إنترنت
  بعد أول دخول ناجح.
* أول مدير يُنشأ عبر `bootstrap_admin` بلا رمز (ترفض العمل إن وُجد
  مدير مسبقاً).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import config
from services import tenant
from services.auth import hash_password, verify_password

ROLE_SUPER = "super_admin"
ROLE_FACTORY = "factory"

CACHE = config.BASE_DIR / "data" / "auth_cache.json"
ADMIN_TOKEN_FILE = config.BASE_DIR / "data" / "admin_token.json"

OFFLINE_GRACE_DAYS = 30

# إصدار دوال الخادم المتوقَّع — إن اختلف فالترقية لم تُنفَّذ
RPC_EXPECTED = "2.1.0"


# ══════════════════════════════════════════════════════════════════
# الذاكرة المحلية
# ══════════════════════════════════════════════════════════════════

def _cache_read():
    try:
        if CACHE.exists():
            return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"users": {}}


def _cache_write(data):
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    except Exception:
        pass


def _cache_put(username, row):
    data = _cache_read()
    data.setdefault("users", {})[username.lower()] = {
        "tenant_id": row.get("tenant_id", ""),
        "password_hash": row.get("password_hash", ""),
        "role": row.get("role") or ROLE_FACTORY,
        "full_name": row.get("full_name") or username,
        "is_active": bool(row.get("is_active", True)),
        "cached_at": time.time(),
    }
    _cache_write(data)


def _cache_get(username):
    return _cache_read().get("users", {}).get(username.lower())


def clear_cache():
    for f in (CACHE, ADMIN_TOKEN_FILE):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# الرمز الإداري
# ══════════════════════════════════════════════════════════════════

def save_admin_token(tok):
    try:
        ADMIN_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        ADMIN_TOKEN_FILE.write_text(json.dumps({"token": tok}),
                                    encoding="utf-8")
    except Exception:
        pass


def clear_admin_token():
    """يمسح الرمز الإداري المحفوظ — عند رفض الخادم له."""
    try:
        ADMIN_TOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def admin_token():
    try:
        if ADMIN_TOKEN_FILE.exists():
            return json.loads(
                ADMIN_TOKEN_FILE.read_text(encoding="utf-8")).get("token", "")
    except Exception:
        pass
    return ""


# ══════════════════════════════════════════════════════════════════
# استدعاء دوال الخادم
# ══════════════════════════════════════════════════════════════════

def _rpc(fn, payload, timeout=25):
    """ينادي دالة على الخادم بالمفتاح العام ويُرجع نتيجتها."""
    import app_config
    cfg = tenant.cloud_config()
    url = app_config.supabase_url() or cfg["url"]
    key = app_config.supabase_key() or cfg["key"]
    if not (url and key):
        raise ValueError(
            "إعدادات السحابة غير مكتملة.\n"
            "افتح ملف .env وتأكد من وجود SUPABASE_URL و"
            "SUPABASE_PUBLISHABLE_KEY")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/rpc/{fn}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        if e.code == 404:
            raise ValueError(
                "دوال الإدارة غير موجودة على الخادم.\n\n"
                "افتح Supabase ← SQL Editor ونفّذ الملف:\n"
                "    admin_rpc.sql") from e
        msg = ""
        try:
            msg = json.loads(detail).get("message", "")
        except Exception:
            msg = detail[:250]
        raise ValueError(msg or f"خطأ من الخادم ({e.code})") from e


def fetch_user(username, timeout=15):
    """يجلب سجل المستخدم عبر دالة الخادم."""
    rows = _rpc("auth_login", {"p_username": username}, timeout=timeout)
    if not rows:
        return None
    return rows[0] if isinstance(rows, list) else rows


# ══════════════════════════════════════════════════════════════════
# تسجيل الدخول
# ══════════════════════════════════════════════════════════════════

def _default_admin_allowed(username):
    """`admin` الافتراضي مسموح ما لم يُنشأ حساب سحابي بعد."""
    if (username or "").strip().lower() != "admin":
        return True
    return not _cache_read().get("users", {})


def _session(username, row, online, notice=""):
    role = row.get("role") or ROLE_FACTORY
    tid = row.get("tenant_id") or ""
    if tid:
        tenant.update(tenant_id=tid,
                      role=(ROLE_SUPER if role == ROLE_SUPER else "factory"))
    return {"username": username,
            "full_name": row.get("full_name") or username,
            "role": role, "role_local": "accountant", "tenant_id": tid,
            "is_super": role == ROLE_SUPER,
            "online": online, "notice": notice}


def login(username, password):
    """الدخول بثلاث مراحل: محلي ← سحابي ← ذاكرة محلية."""
    username = (username or "").strip()
    if not username or not password:
        raise ValueError("أدخل اسم المستخدم وكلمة المرور")

    # (1) الحساب المحلي — مدير عام في أي نسخة، ويُعطَّل تلقائياً بعد
    #     إنشاء أول حساب سحابي فلا يصل للعملاء.
    try:
        from services import auth as local_auth
        lu = local_auth.verify_login(username, password)
        if lu and _default_admin_allowed(username):
            tenant.update(role="super_admin")
            return {"username": lu["username"],
                    "full_name": lu.get("full_name") or lu["username"],
                    "role": ROLE_SUPER,
                    "role_local": lu.get("role", "accountant"),
                    "tenant_id": tenant.tenant_id(),
                    "is_super": True, "online": False, "notice": ""}
    except Exception:
        pass

    # (2) الحساب السحابي
    online, row, net_err = True, None, ""
    try:
        row = fetch_user(username)
    except ValueError:
        raise                      # رسالة الخادم الواضحة تُعرض كما هي
    except Exception as e:
        online, net_err = False, type(e).__name__

    if online:
        if not row or not verify_password(password,
                                          row.get("password_hash", "")):
            raise ValueError("اسم المستخدم أو كلمة المرور غير صحيحة")
        if not bool(row.get("is_active", True)):
            raise ValueError("الحساب موقوف — يرجى مراجعة الإدارة")
        _cache_put(username, row)
        if row.get("admin_token"):
            save_admin_token(row["admin_token"])
        return _session(username, row, online=True)

    # (3) بلا اتصال: الذاكرة المحلية
    cached = _cache_get(username)
    if not cached:
        raise ValueError(
            "اسم المستخدم أو كلمة المرور غير صحيحة.\n\n"
            "إن كان هذا أول دخول لك على هذا الجهاز فاتصل بالإنترنت.")
    if not verify_password(password, cached.get("password_hash", "")):
        raise ValueError("اسم المستخدم أو كلمة المرور غير صحيحة")
    if not cached.get("is_active", True):
        raise ValueError("الحساب موقوف — يرجى مراجعة الإدارة")
    age = (time.time() - cached.get("cached_at", 0)) / 86400
    if age > OFFLINE_GRACE_DAYS:
        raise ValueError(
            f"مضى {int(age)} يوماً بلا اتصال — اتصل بالإنترنت للمتابعة")
    return _session(username, cached, online=False,
                    notice=f"عمل دون اتصال ({net_err})")


# ══════════════════════════════════════════════════════════════════
# إدارة الحسابات (عبر دوال الخادم)
# ══════════════════════════════════════════════════════════════════

def _new_tenant_id():
    import uuid
    return f"F-{uuid.uuid4().hex[:12].upper()}"


def _need_token():
    tok = admin_token()
    if not tok:
        raise ValueError(
            "أنشئ حساب المدير العام أولاً.\n\n"
            "ضع علامة على «حساب مدير عام»، واكتب اسم مستخدم وكلمة "
            "مرور، ثم اضغط «إنشاء الحساب».")
    return tok


def _admin_call(fn, payload, timeout=20):
    """ينادي دالة إدارية، ويمسح الرمز الميت عند رفضه.

    فلا يبقى النظام عالقاً برمز لا وجود له بعد حذف الحسابات.
    """
    try:
        return _rpc(fn, payload, timeout=timeout)
    except ValueError as e:
        if "رمز إداري" in str(e):
            clear_admin_token()
            raise ValueError(
                "الرمز الإداري لم يعد صالحاً (حُذفت الحسابات من "
                "السحابة).\n\nأنشئ حساب المدير العام من جديد: ضع "
                "علامة «حساب مدير عام» واكتب اسماً وكلمة مرور.") from e
        raise


def server_version():
    """إصدار دوال الخادم — يكشف عدم تنفيذ ملف SQL المحدَّث."""
    try:
        v = _rpc("rpc_version", {}, timeout=12)
        return v if isinstance(v, str) else ""
    except Exception:
        return ""


def _require_current_rpc():
    """يمنع العمليات إن كانت دوال الخادم قديمة، ويشرح الحل."""
    v = server_version()
    if v and v != RPC_EXPECTED:
        raise ValueError(
            f"دوال الخادم قديمة (إصدار {v}، المطلوب {RPC_EXPECTED}).\n\n"
            f"افتح Supabase ← SQL Editor ← New query\n"
            f"والصق ملف admin_rpc.sql كاملاً ثم اضغط RUN.\n\n"
            f"تأكد أن الملف كامل من أول سطر إلى آخره.")
    if not v:
        raise ValueError(
            "دوال الإدارة غير موجودة على الخادم.\n\n"
            "افتح Supabase ← SQL Editor ← New query\n"
            "والصق ملف admin_rpc.sql كاملاً ثم اضغط RUN.")


def create_admin(username, password, full_name="المدير العام"):
    """ينشئ حساب مدير عام.

    أول مدير يُنشأ عبر `bootstrap_admin` **بلا رمز** — وهي دالة على
    الخادم ترفض العمل إن وُجد مدير مسبقاً. والمدراء التالون يُنشأون
    بالرمز الإداري كأي حساب.
    """
    username = (username or "").strip()
    if not username:
        raise ValueError("أدخل اسم المستخدم")
    if len(password or "") < 4:
        raise ValueError("كلمة المرور قصيرة — 4 أحرف على الأقل")
    _require_current_rpc()
    tid = _new_tenant_id()

    # الرمز المحفوظ محلياً قد يكون **ميتاً**: لو حُذفت حسابات المصانع
    # من السحابة يبقى الملف عندنا فيُرسَل رمز لا وجود له ويفشل بـ
    # «رمز إداري غير صالح» — والنظام يعجز عن إنشاء أول مدير من جديد.
    # لذلك نجرّب بالرمز، وعند رفضه نسقط تلقائياً إلى التأسيس.
    if admin_token():
        try:
            return create_user(username, password, role=ROLE_SUPER,
                               full_name=full_name,
                               factory_name="الإدارة العامة")
        except ValueError as e:
            if "رمز إداري" not in str(e):
                raise
            clear_admin_token()

    tok = _rpc("bootstrap_admin", {"p_username": username,
                                   "p_hash": hash_password(password),
                                   "p_tenant": tid})
    if isinstance(tok, str) and tok:
        save_admin_token(tok)
    return {"username": username, "tenant_id": tid, "role": ROLE_SUPER}


def create_user(username, password, role=ROLE_FACTORY, tenant_id=None,
                full_name="", factory_name=""):
    """ينشئ حساب مصنع. الخادم ينشئ سجل المصنع والمستخدم معاً."""
    username = (username or "").strip()
    if not username:
        raise ValueError("أدخل اسم المستخدم")
    if len(password or "") < 4:
        raise ValueError("كلمة المرور قصيرة — 4 أحرف على الأقل")
    _require_current_rpc()
    tid = tenant_id or _new_tenant_id()
    _admin_call("admin_create_user", {
        "p_token": _need_token(), "p_username": username,
        "p_hash": hash_password(password), "p_role": role,
        "p_tenant": tid, "p_name": factory_name or full_name or username})
    return {"username": username, "tenant_id": tid, "role": role}


def list_users(timeout=15):
    return _admin_call("admin_list_users", {"p_token": _need_token()},
                timeout=timeout) or []


def set_user_active(username, active):
    _admin_call("admin_set_active", {"p_token": _need_token(),
                              "p_username": username,
                              "p_active": bool(active)})
    return True


def delete_user(username):
    _admin_call("admin_delete_user", {"p_token": _need_token(),
                               "p_username": username})
    try:
        data = _cache_read()
        data.get("users", {}).pop(username.lower(), None)
        _cache_write(data)
    except Exception:
        pass
    return True


def user_exists(username, timeout=10):
    try:
        return fetch_user(username, timeout=timeout) is not None
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# التشخيص
# ══════════════════════════════════════════════════════════════════

def diagnose():
    """فحص شامل: الإعدادات · الاتصال · الدوال · الرمز الإداري."""
    import app_config
    out = {"url": "", "pub": False, "reachable": False, "rpc": False,
           "has_token": bool(admin_token()), "rpc_version": "",
           "expected": RPC_EXPECTED, "message": ""}
    try:
        out["url"] = app_config.supabase_url()
        out["pub"] = bool(app_config.supabase_key())
    except Exception:
        pass
    if not (out["url"] and out["pub"]):
        out["message"] = "إعدادات السحابة ناقصة في ملف .env"
        return out
    try:
        _rpc("auth_login", {"p_username": "__probe__"}, timeout=12)
        out["reachable"] = out["rpc"] = True
        out["rpc_version"] = server_version()
        if out["rpc_version"] != RPC_EXPECTED:
            out["message"] = (
                f"دوال الخادم قديمة ({out['rpc_version'] or 'غير معروف'}) — "
                f"المطلوب {RPC_EXPECTED}.\n"
                f"نفّذ ملف admin_rpc.sql كاملاً في Supabase.")
        else:
            out["message"] = ("جاهز — أنشئ حساب المدير العام"
                              if not out["has_token"] else "جاهز تماماً")
    except ValueError as e:
        out["reachable"] = True
        out["message"] = str(e).splitlines()[0]
    except Exception as e:
        out["message"] = f"تعذّر الاتصال: {type(e).__name__}"
    return out


def is_owner_copy():
    """للتوافق مع كود قديم — لم تعد تُستخدم في أي قرار."""
    return True
