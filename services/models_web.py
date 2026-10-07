# -*- coding: utf-8 -*-
"""رابط دليل الموديلات للمدير — ثابت، مجاني، وبلا سحابة.

**الفكرة**: جهاز المصنع نفسه يعرض الدليل. البرنامج فيه أصلاً خادمٌ صغير
(`services.photo_server`) يعرض صور الفواتير على شبكة المصنع؛ وهنا يُضاف
إليه مسارٌ واحد `/m/<رمز>` يعرض **الشاشة كاملةً** للمدير على جواله:
كل موديل بصورته، وكم بالخزنة وكم عند المناديب، وكل رقم تشغيل بوزنه ومع
من هو ومتى — والبضاعة الواردة بتاريخ. البيانات تُقرأ لحظةَ الفتح من قاعدة المصنع:
طقمٌ بِيع الآن يظهر مباعاً في الصفحة الآن.

**لا سحابة ولا مساحة**: لا يُرفع شيءٌ إلى أي مكان. الصور تُصغَّر عند
الطلب (نحو 50 كيلوبايت) وتُرسل مباشرةً من الجهاز، وذاكرتها مؤقتة في
الذاكرة لا على القرص.

**الرابط الثابت المجاني** عبر Tailscale (حساب مجاني، بلا نطاقٍ ولا
رسوم): يعطي جهاز المصنع عنواناً دائماً `https://<الجهاز>.<شبكتك>.ts.net`،
والبرنامج يوجّهه إلى خادمه عند كل تشغيل — فالرابط لا يتغيّر أبداً.
وضعان:

  * **funnel** — رابطٌ يُفتح من أي متصفح (جوال المدير كما هو).
  * **serve**  — رابطٌ خاص لا يُفتح إلا على أجهزةٍ عليها Tailscale بالحساب
    نفسه (جوال المدير بعد تثبيت التطبيق عليه) — أعلى خصوصية.
  * **lan**    — شبكة المصنع وحدها، بلا إنترنت.

**يعمل والبرنامج مفتوح وحده**: إغلاق البرنامج يُغلق الخادم، فلا يردّ
الرابط بشيء حتى يُفتح البرنامج ثانيةً — وهو المطلوب.

**الحماية**: رمزٌ عشوائي طويل في الرابط لا يُخمَّن (تغييره يُبطل القديم
فوراً)، ورمز دخول (PIN) اختياري يُحفظ في جوال المدير 30 يوماً، وقفلٌ بعد
محاولاتٍ خاطئة متكررة. والخادم **قراءةٌ فقط**: لا مسار يكتب في القاعدة.
"""
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qs, quote

PREFIX = "m"
K_TOKEN = "models_web_token"
K_SECRET = "models_web_secret"
K_PIN = "models_web_pin"
K_ENABLED = "models_web_enabled"
K_MODE = "models_web_mode"
K_TS = "models_web_ts_applied"       # ما وجّهه البرنامج في Tailscale

MODES = (
    ("funnel", "ثابت عبر الإنترنت — يُفتح من أي جوال"),
    ("serve", "ثابت وخاص — على أجهزة المدير التي عليها Tailscale"),
    ("lan", "شبكة المصنع فقط — بلا إنترنت"),
)
COOKIE = "mw"
COOKIE_DAYS = 30
THUMB_W, FULL_W = 520, 1400
CACHE_CAP = 40 * 1024 * 1024         # ذاكرة الصور المصغّرة (في الذاكرة)
LOCK_AFTER, LOCK_WINDOW = 10, 15 * 60

_lock = threading.Lock()
_fails = []                          # أوقات محاولات رمز الدخول الخاطئة
_thumbs = OrderedDict()              # (المسار, التعديل, العرض) → بايتات
_thumb_bytes = [0]


# ══════════════════════════════════════════════════════════════════
#  الإعدادات
# ══════════════════════════════════════════════════════════════════

def _get(conn, key, default=""):
    from models import fiscal
    return (fiscal.get_setting(conn, key, default) or default)


def _set(conn, key, value, username=None):
    from models import fiscal
    fiscal.set_setting(conn, key, value, username)


def ensure_token(conn):
    """رمز الرابط الثابت — يُولَّد مرةً ويبقى حتى يُغيَّر صراحةً."""
    tok = _get(conn, K_TOKEN).strip()
    if not tok:
        tok = secrets.token_urlsafe(18)
        _set(conn, K_TOKEN, tok)
    if not _get(conn, K_SECRET).strip():
        _set(conn, K_SECRET, secrets.token_hex(24))
    return tok


def settings(conn):
    m = _get(conn, K_MODE, "funnel")
    return {"token": _get(conn, K_TOKEN).strip(),
            "enabled": _get(conn, K_ENABLED, "0") == "1",
            "mode": m if m in dict(MODES) else "funnel",
            "has_pin": bool(_get(conn, K_PIN).strip())}


def regenerate(conn, username=None):
    """رابطٌ جديد — والقديم يبطل فوراً (لمن تسرّب إليه الرابط)."""
    tok = secrets.token_urlsafe(18)
    _set(conn, K_TOKEN, tok, username)
    _set(conn, K_SECRET, secrets.token_hex(24), username)
    _audit(conn, username, "تغيير رابط دليل الموديلات — القديم أُبطل")
    return tok


def set_mode(conn, mode, username=None):
    if mode not in dict(MODES):
        raise ValueError("نوع الرابط غير معروف")
    _set(conn, K_MODE, mode, username)
    return mode


def set_enabled(conn, on, username=None):
    _set(conn, K_ENABLED, "1" if on else "0", username)
    _audit(conn, username, "تشغيل رابط دليل الموديلات" if on
           else "إيقاف رابط دليل الموديلات")


def _hash_pin(pin, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"),
                            salt.encode("ascii"), 120000).hex()
    return f"{salt}${h}"


def set_pin(conn, pin, username=None):
    """رمز الدخول: 4 إلى 12 خانة — وفارغٌ يلغيه."""
    pin = str(pin or "").strip()
    if pin and not (4 <= len(pin) <= 12):
        raise ValueError("رمز الدخول من 4 إلى 12 خانة")
    _set(conn, K_PIN, _hash_pin(pin) if pin else "", username)
    _audit(conn, username, "تعيين رمز دخول لرابط الموديلات" if pin
           else "إلغاء رمز دخول رابط الموديلات")


def _pin_ok(stored, pin):
    try:
        salt, _h = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(_hash_pin(pin, salt), stored)


def _audit(conn, username, text):
    try:
        from services.audit import log_action
        log_action(conn, username or "system", "update", "app_settings",
                   None, text)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
#  الرابط
# ══════════════════════════════════════════════════════════════════

def lan_url(conn):
    from services import photo_server
    addr = photo_server.current()
    if not addr:
        return ""
    return f"http://{addr[0]}:{addr[1]}/{PREFIX}/{ensure_token(conn)}"


def ts_url(dns, token):
    return f"https://{dns}/{PREFIX}/{token}" if dns and token else ""


def register():
    from services import photo_server
    photo_server.add_route(PREFIX, handle)


# ══════════════════════════════════════════════════════════════════
#  Tailscale — العنوان الثابت المجاني
# ══════════════════════════════════════════════════════════════════

_TS_PATHS = (r"C:\Program Files\Tailscale\tailscale.exe",
             r"C:\Program Files (x86)\Tailscale\tailscale.exe",
             "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
             "/usr/bin/tailscale", "/usr/local/bin/tailscale")


def ts_exe():
    p = shutil.which("tailscale")
    if p:
        return p
    for c in _TS_PATHS:
        if os.path.exists(c):
            return c
    return None


def _run_ts(args, timeout=25):
    """يشغّل أمر tailscale — (رمز الخروج, المخرجات) أو None إن لم يُثبَّت."""
    exe = ts_exe()
    if not exe:
        return None
    kw = {"capture_output": True, "timeout": timeout}
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000        # بلا نافذة أوامر سوداء
    try:
        r = subprocess.run([exe] + [str(a) for a in args], **kw)
        out = (r.stdout or b"") + b"\n" + (r.stderr or b"")
        return r.returncode, out.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        # أمر funnel الأول ينتظر الموافقة في المتصفح — مخرجاته الجزئية
        # تحمل رابط التفعيل
        out = (e.stdout or b"") + b"\n" + (e.stderr or b"")
        if isinstance(out, str):
            return -2, out
        return -2, out.decode("utf-8", "replace")
    except Exception as e:                      # noqa: BLE001
        return -1, str(e)


RUNNER = _run_ts            # يُستبدل في الاختبار


_URL_RE = re.compile(r"https://login\.tailscale\.com/\S+")


def ts_status():
    res = RUNNER(["status", "--json"], 15)
    if res is None:
        return {"installed": False, "running": False, "dns": ""}
    _code, out = res
    i = out.find("{")
    try:
        d = json.loads(out[i:out.rfind("}") + 1]) if i >= 0 else {}
    except Exception:
        d = {}
    state = d.get("BackendState") or ""
    dns = ((d.get("Self") or {}).get("DNSName") or "").rstrip(".")
    m = _URL_RE.search(out)
    return {"installed": True, "running": state == "Running",
            "state": state, "dns": dns,
            "login_url": d.get("AuthURL") or (m.group(0) if m else "")}


def ts_apply(mode, port):
    """يوجّه عنوان الجهاز الثابت إلى خادم البرنامج (أو يلغي التوجيه).

    `tailscale serve reset` قبل كل توجيه: فلا يبقى «funnel» عاماً حين
    يختار المستخدم «الخاص» أو «شبكة المصنع».
    """
    RUNNER(["serve", "reset"], 15)
    if mode not in ("funnel", "serve"):
        return {"ok": True, "message": "", "enable_url": ""}
    res = RUNNER([mode, "--bg", str(int(port))], 30)
    if res is None:
        return {"ok": False, "message": "Tailscale غير مثبّت",
                "enable_url": ""}
    code, out = res
    m = _URL_RE.search(out)
    if code == 0:
        return {"ok": True, "message": "", "enable_url": ""}
    msg = out.strip().splitlines()[-1] if out.strip() else ""
    if "flag provided but not defined" in out:
        msg = "نسخة Tailscale قديمة — حدّثها من tailscale.com"
    return {"ok": False, "message": msg[:300],
            "enable_url": m.group(0) if m else ""}


def activate(username=None):
    """يشغّل الرابط بنوعه المحفوظ ويعيد حاله ورابطه.

    يُستدعى من نافذة الرابط ومن الإقلاع (`autostart`) — في خيطٍ خلفي
    لأن أوامر Tailscale قد تستغرق ثواني.
    """
    from database.database import db
    from services import photo_server
    with db(readonly=True) as conn:
        st = settings(conn)
    if not st["token"] or not st["enabled"]:
        with db() as conn:           # كتابةٌ عند الحاجة وحدها لا كل إقلاع
            ensure_token(conn)
            if not st["enabled"]:
                set_enabled(conn, True, username)
            st = settings(conn)
    tok = st["token"]
    addr = photo_server.ensure_running()
    if not addr:
        return {"ok": False, "url": "", "lan": "", "mode": st["mode"],
                "reason": "server",
                "message": "تعذّر تشغيل الخادم على هذا الجهاز (منفذ مشغول"
                           " أو جدار حماية)"}
    register()
    lan = f"http://{addr[0]}:{addr[1]}/{PREFIX}/{tok}"
    out = {"ok": True, "url": lan, "lan": lan, "mode": st["mode"],
           "reason": "", "message": "", "enable_url": "", "login_url": ""}
    if st["mode"] == "lan":
        if _ts_was_applied():
            ts_apply("lan", addr[1])
            _remember_ts("")
        return out
    ts = ts_status()
    if not ts["installed"]:
        out.update(ok=False, reason="no_ts",
                   message="Tailscale غير مثبّت على هذا الجهاز — الرابط"
                           " يعمل الآن على شبكة المصنع وحدها")
        return out
    if not ts["running"] or not ts["dns"]:
        out.update(ok=False, reason="ts_off", login_url=ts["login_url"],
                   message="Tailscale مثبّت لكنه غير متصل — سجّل الدخول"
                           " فيه ثم أعد التفعيل")
        return out
    r = ts_apply(st["mode"], addr[1])
    if not r["ok"]:
        out.update(ok=False, reason="ts_apply", message=r["message"],
                   enable_url=r["enable_url"])
        return out
    _remember_ts(st["mode"])
    out["url"] = ts_url(ts["dns"], tok)
    return out


def peek():
    """حال الرابط الآن بلا أي تغيير — لنافذة الرابط عند فتحها."""
    from database.database import db
    from services import photo_server
    with db(readonly=True) as conn:
        st = settings(conn)
    addr = photo_server.current()
    lan = (f"http://{addr[0]}:{addr[1]}/{PREFIX}/{st['token']}"
           if addr and st["token"] else "")
    url, ts = (lan if st["enabled"] else ""), None
    if st["enabled"] and addr and st["mode"] in ("funnel", "serve"):
        ts = ts_status()
        if ts["running"] and ts["dns"] and _ts_was_applied():
            url = ts_url(ts["dns"], st["token"])
    return {"settings": st, "lan": lan, "url": url, "ts": ts,
            "running": bool(addr)}


def deactivate(username=None):
    """يوقف الرابط: الصفحة لا تُعرض، والعنوان العام يُلغى توجيهه."""
    from database.database import db
    with db() as conn:
        set_enabled(conn, False, username)
    if _ts_was_applied():
        ts_apply("lan", 0)
        _remember_ts("")
    return True


def _ts_was_applied():
    from database.database import db
    try:
        with db(readonly=True) as conn:
            return bool(_get(conn, K_TS).strip())
    except Exception:
        return False


def _remember_ts(mode):
    from database.database import db
    try:
        with db() as conn:
            _set(conn, K_TS, mode or "")
    except Exception:
        pass


def autostart():
    """عند تشغيل البرنامج: إن كان الرابط مفعّلاً يعود كما كان."""
    try:
        from database.database import db
        with db(readonly=True) as conn:
            on = _get(conn, K_ENABLED, "0") == "1"
        if on:
            return activate("system")
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════
#  الدخول
# ══════════════════════════════════════════════════════════════════

def _cookie_value(token, secret, pin_hash):
    return hmac.new(secret.encode("utf-8"),
                    f"{token}|{pin_hash}".encode("utf-8"),
                    hashlib.sha256).hexdigest()[:40]


def _cookies(headers):
    out = {}
    raw = (headers.get("Cookie") if headers is not None else "") or ""
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _locked():
    now = time.time()
    with _lock:
        _fails[:] = [t for t in _fails if now - t < LOCK_WINDOW]
        return len(_fails) >= LOCK_AFTER


def _fail():
    with _lock:
        _fails.append(time.time())


# ══════════════════════════════════════════════════════════════════
#  الطلبات
# ══════════════════════════════════════════════════════════════════

_SEC = {
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline';"
        " script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"),
}


def _resp(code, body, ctype="text/html; charset=utf-8", headers=None):
    h = dict(_SEC)
    h.update(headers or {})
    return {"code": code, "body": body, "ctype": ctype, "headers": h}


_GONE = ("<!DOCTYPE html><html dir='rtl' lang='ar'><meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<body style='font-family:system-ui,Tahoma;padding:30px;"
         "text-align:center;color:#555'><h3>الرابط غير صالح أو موقوف</h3>"
         "<p>قد يكون البرنامج مغلقاً على جهاز المصنع، أو غُيِّر الرابط.</p>"
         "</body></html>")


def handle(method, parts, query, headers, body):
    """معالج `/m/<رمز>/…` — يستدعيه `photo_server` في خيط الطلب."""
    from database.database import db
    if not parts:
        return _resp(404, _GONE)
    with db(readonly=True) as conn:
        token = _get(conn, K_TOKEN).strip()
        enabled = _get(conn, K_ENABLED, "0") == "1"
        secret = _get(conn, K_SECRET).strip()
        pin_hash = _get(conn, K_PIN).strip()
    if not (enabled and token and secret
            and hmac.compare_digest(str(parts[0]), token)):
        return _resp(404, _GONE)
    base = f"/{PREFIX}/{token}"
    rest = list(parts[1:])
    authed = (not pin_hash) or hmac.compare_digest(
        _cookies(headers).get(COOKIE, ""),
        _cookie_value(token, secret, pin_hash))

    if rest[:1] == ["login"] and method == "POST":
        if not pin_hash:
            return _resp(303, "", headers={"Location": base})
        if _locked():
            return _resp(429, login_page(base, "محاولات كثيرة — انتظر ربع"
                                               " ساعة ثم حاول ثانيةً"))
        form = parse_qs((body or b"").decode("utf-8", "replace"))
        pin = (form.get("pin") or [""])[-1].strip()
        if not _pin_ok(pin_hash, pin):
            _fail()
            return _resp(401, login_page(base, "الرمز غير صحيح"))
        ck = (f"{COOKIE}={_cookie_value(token, secret, pin_hash)}; "
              f"Path={base}; Max-Age={COOKIE_DAYS * 86400}; HttpOnly;"
              " SameSite=Strict")
        return _resp(303, "", headers={"Location": base, "Set-Cookie": ck})
    if rest[:1] == ["logout"]:
        ck = f"{COOKIE}=; Path={base}; Max-Age=0; HttpOnly; SameSite=Strict"
        return _resp(303, "", headers={"Location": base, "Set-Cookie": ck})
    if not authed:
        if rest[:1] == ["img"]:
            return _resp(401, b"", "text/plain")
        return _resp(200, login_page(base))
    if method != "GET":
        return _resp(405, _GONE)
    if rest[:1] == ["img"] and len(rest) == 2:
        return _image(rest[1], query.get("full") == "1")
    if rest:
        return _resp(404, _GONE)
    with db(readonly=True) as conn:
        return _resp(200, page_html(conn, query, base))


def _image(model_no, full):
    from models import models_catalog as mc
    try:
        p = mc.image_path(model_no)
    except Exception:
        p = None
    if p is None:
        return _resp(404, b"", "text/plain")
    data, ctype = thumb(p, FULL_W if full else THUMB_W)
    if not data:
        return _resp(404, b"", "text/plain")
    return _resp(200, data, ctype, {"Cache-Control": "private, max-age=600"})


def thumb(path, width):
    """الصورة مصغّرةً ومضغوطة (JPEG) — من الذاكرة إن سبق تصغيرها."""
    import mimetypes
    try:
        st = os.stat(path)
    except OSError:
        return b"", ""
    key = (str(path), st.st_mtime_ns, int(width))
    with _lock:
        hit = _thumbs.get(key)
        if hit is not None:
            _thumbs.move_to_end(key)
            return hit
    raw = open(path, "rb").read()
    out = (raw, mimetypes.guess_type(str(path))[0] or "image/jpeg")
    try:
        from PyQt5.QtCore import QBuffer, QByteArray
        from PyQt5.QtGui import QImage
        img = QImage()
        if img.loadFromData(raw):
            if img.width() > width:
                img = img.scaledToWidth(int(width), 1)    # 1 = Smooth
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QBuffer.WriteOnly)
            if img.save(buf, "JPEG", 70):
                small = bytes(ba)
                if 0 < len(small) < len(raw):
                    out = (small, "image/jpeg")
            buf.close()
    except Exception:
        pass
    with _lock:
        _thumbs[key] = out
        _thumb_bytes[0] += len(out[0])
        while _thumb_bytes[0] > CACHE_CAP and len(_thumbs) > 1:
            _k, v = _thumbs.popitem(last=False)
            _thumb_bytes[0] -= len(v[0])
    return out


# ══════════════════════════════════════════════════════════════════
#  الصفحة
# ══════════════════════════════════════════════════════════════════

_CSS = """
:root{--bg:#F6F2EA;--card:#fff;--ink:#2b2723;--muted:#776b5e;--line:#e7dfd1;
--brown:#5A3E1B;--gold:#A8822E;--in:#1E6B33;--out:#8B5E1E}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:system-ui,"Segoe UI",Tahoma,sans-serif;font-size:15px}
header{position:sticky;top:0;z-index:5;background:var(--brown);color:#fff;
padding:10px 14px 12px;box-shadow:0 2px 8px rgba(0,0,0,.15)}
header h1{font-size:17px;margin:0}
header .sub{font-size:12px;opacity:.85;margin-top:2px}
.bar{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.bar input[type=search]{flex:1 1 200px;min-width:0;padding:9px 11px;
border:0;border-radius:9px;font-size:15px}
main{padding:12px;max-width:1200px;margin:auto}
.tabs,.seg{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.tabs a,.seg a{padding:7px 13px;border-radius:20px;background:#fff;
border:1px solid var(--line);color:var(--ink);text-decoration:none;
font-size:14px}
.tabs a.on,.seg a.on{background:var(--gold);border-color:var(--gold);
color:#fff;font-weight:600}
form.tools{display:flex;gap:6px;flex-wrap:wrap;align-items:center;
margin:0 0 10px}
form.tools select,form.tools input,form.tools button{padding:7px 9px;
border:1px solid var(--line);border-radius:8px;background:#fff;font-size:14px}
form.tools button{background:var(--brown);color:#fff;border-color:var(--brown)}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:8px;margin:0 0 12px}
.sum div{background:#fff;border:1px solid var(--line);border-radius:12px;
padding:10px 12px}
.sum b{display:block;font-size:19px;margin-top:3px}
.sum .in b{color:var(--in)} .sum .out b{color:var(--out)}
.grid{display:grid;gap:12px;
grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
overflow:hidden;display:flex;flex-direction:column}
.ph{display:block;background:#efe9dc;aspect-ratio:4/3}
.ph img{width:100%;height:100%;object-fit:cover;display:block}
.noimg{display:flex;align-items:center;justify-content:center;
color:var(--muted);font-size:13px;aspect-ratio:4/3;background:#f1ece2}
.b{padding:10px 12px 12px}
.b h2{font-size:16px;margin:0 0 6px;color:var(--brown)}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:13px;padding:3px 9px;border-radius:12px;background:#f3efe6}
.chip.in{color:var(--in);background:#e8f3ea}
.chip.out{color:var(--out);background:#f7eddd}
.chip.pick{color:#fff;background:#8a6d1d;font-weight:bold}
.sum .pick{grid-column:1/-1;border-color:#8a6d1d}
details{margin-top:8px;border-top:1px dashed var(--line);padding-top:6px}
summary{cursor:pointer;color:var(--gold);font-weight:600;font-size:14px}
h3{font-size:13.5px;margin:9px 0 4px}
h3.in{color:var(--in)} h3.out{color:var(--out)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:5px 4px;border-bottom:1px solid #f0ebe1;text-align:right}
th{color:var(--muted);font-weight:600}
td.n{direction:ltr;text-align:left;white-space:nowrap}
.empty{padding:30px;text-align:center;color:var(--muted)}
footer{padding:16px;text-align:center;color:var(--muted);font-size:12px}
footer a{color:var(--muted)}
"""

_JS = """
(function(){
 // 4.56: برقم الموديل يُعرض الموديل كاملاً؛ وباسم الجهة أو رقم التشغيل
 // تُعرض الأسطر المطابقة وحدها، وفي رأس البطاقة عددها ووزنها هي
 var q=document.getElementById('q');
 var sum=document.getElementById('pick');
 function fmt(x){return x.toLocaleString('en-US',{minimumFractionDigits:2,
  maximumFractionDigits:2});}
 function run(){
  var v=q.value.trim().toLowerCase(),n=0,tn=0,tw=0;
  document.querySelectorAll('.card').forEach(function(c){
   var rows=c.querySelectorAll('tr[data-r]'),whole=!v||
    (c.getAttribute('data-m')||'').indexOf(v)>=0,cn=0,cw=0;
   rows.forEach(function(r){
    var hit=whole||(r.getAttribute('data-r')||'').indexOf(v)>=0;
    r.style.display=hit?'':'none';
    if(hit&&!whole){cn++;cw+=parseFloat(r.getAttribute('data-w')||0);}});
   c.querySelectorAll('table').forEach(function(t){
    var vis=whole||t.querySelector('tr[data-r]:not([style*="none"])');
    t.style.display=vis?'':'none';
    var h=t.previousElementSibling;
    if(h&&h.tagName==='H3'){h.style.display=vis?'':'none';}});
   var show=whole||cn>0, pk=c.querySelector('.chip.pick');
   c.style.display=show?'':'none'; if(show)n++;
   var d=c.querySelector('details');
   if(pk){pk.style.display=(!whole&&cn)?'':'none';
    pk.textContent='نتيجة البحث: '+cn+' طقم · '+fmt(cw);}
   c.querySelectorAll('.chip:not(.pick)').forEach(function(x){
    x.style.display=(!whole&&cn)?'none':'';});
   if(d&&!whole&&cn){d.open=true;}
   if(!whole){tn+=cn;tw+=cw;}});
  var e=document.getElementById('none'); if(e)e.style.display=n?'none':'';
  if(sum){sum.style.display=(v&&tn)?'':'none';
   sum.innerHTML='نتيجة البحث «'+v.replace(/[<>&"]/g,'')+'»<b>'+n+
    ' موديل · '+tn+' طقم · '+fmt(tw)+'</b>';}
 }
 if(q){q.addEventListener('input',run);}
 document.querySelectorAll('select[data-auto]').forEach(function(s){
  s.addEventListener('change',function(){s.form.submit();});});
})();
"""


def _e(v):
    return html.escape(str(v if v is not None else ""), quote=True)


def _w(v):
    from services import karat_view as kv
    return f"{kv.g(float(v or 0)):,.2f}"


def _rk(i, with_holder):
    """مفتاح بحث السطر ووزنه (بعيار العرض) — للبحث داخل البطاقة."""
    from services import karat_view as kv
    key = str(i["wo"]) + (" " + str(i["holder"]) if with_holder else "")
    return (f' data-r="{_e(key.lower())}"'
            f' data-w="{kv.g(float(i["reg"] or 0)):.2f}"')


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _sorted(models, sort, view):
    from models.models_catalog import model_key as _k

    def _count(m):
        if view == "in_stock":
            return m["in_count"]
        if view == "sold":
            return m["out_count"]
        return m["count"]
    if sort == "za":
        return sorted(models, key=lambda m: _k(m["model"]), reverse=True)
    if sort == "most":
        return sorted(models, key=lambda m: (-_count(m), _k(m["model"])))
    if sort == "least":
        return sorted(models, key=lambda m: (_count(m), _k(m["model"])))
    return sorted(models, key=lambda m: _k(m["model"]))


def _company():
    try:
        import config
        return getattr(config, "COMPANY_NAME", "") or ""
    except Exception:
        return ""


def _link(base, **kw):
    q = "&".join(f"{k}={quote(str(v))}" for k, v in kw.items()
                 if v not in (None, ""))
    return base + ("?" + q if q else "")


def _photo(base, model, have):
    if not have:
        return '<div class="noimg">لا توجد صورة</div>'
    u = f"{base}/img/{quote(str(model), safe='')}"
    return (f'<a class="ph" href="{_e(u)}?full=1" target="_blank"'
            f' rel="noopener"><img loading="lazy" src="{_e(u)}"'
            f' alt="{_e(model)}"></a>')


def page_html(conn, query, base):
    """الشاشة كاملةً للجوال — الدليل، أو البضاعة الواردة بتاريخ."""
    from datetime import datetime

    from models import models_catalog as mc
    from services import karat_view as kv
    tab = query.get("tab") if query.get("tab") in ("guide", "received") \
        else "guide"
    view = query.get("view") if query.get("view") in (
        "all", "in_stock", "sold") else "all"
    sort = query.get("sort") if query.get("sort") in (
        "az", "za", "most", "least") else "az"
    imgs = mc.models_with_images(conn)
    unit = _e(kv.unit())

    tabs = "".join(
        f'<a class="{"on" if tab == k else ""}"'
        f' href="{_e(_link(base, tab=k, view=view, sort=sort))}">{t}</a>'
        for k, t in (("guide", "الدليل"),
                     ("received", "البضاعة الواردة بتاريخ")))
    seg = "".join(
        f'<a class="{"on" if view == k else ""}" href="'
        f'{_e(_link(base, tab=tab, view=k, sort=sort, day=query.get("day")))}'
        f'">{t}</a>'
        for k, t in (("all", "الكل"), ("in_stock", "المتاح للبيع"),
                     ("sold", "طرف المناديب")))
    sort_sel = "".join(
        f'<option value="{k}"{" selected" if sort == k else ""}>{t}</option>'
        for k, t in (("az", "أ ← ي"), ("za", "ي ← أ"),
                     ("most", "الأكثر عدداً"), ("least", "الأقل عدداً")))

    if tab == "received":
        body, summary, tools = _received(conn, query, base, view, sort,
                                         imgs, unit, sort_sel)
    else:
        body, summary, tools = _guide(conn, base, view, sort, imgs, unit,
                                      sort_sel)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    co = _company().strip()
    title = "دليل الموديلات" + (f" — {_e(co)}" if co else "")
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{title}</title>
<style>{_CSS}</style></head><body>
<header><h1>{title}</h1>
<div class="sub">مباشرةً من جهاز المصنع · {now} · الأوزان {unit}</div>
<div class="bar"><input id="q" type="search"
 placeholder="ابحث برقم الموديل أو رقم التشغيل أو اسم الجهة…"></div>
</header><main>
<nav class="tabs">{tabs}</nav>
<nav class="seg">{seg}</nav>
{tools}
<section class="sum">{summary}<div id="pick" class="pick"
 style="display:none"></div></section>
<section class="grid">{body}</section>
<div id="none" class="empty" style="display:none">لا نتائج للبحث</div>
</main>
<footer><a href="{_e(_link(base, tab=tab, view=view, sort=sort,
                                day=query.get('day')))}">↻ تحديث</a>
 · <a href="{_e(base)}/logout">خروج</a></footer>
<script>{_JS}</script></body></html>"""


def _guide(conn, base, view, sort, imgs, unit, sort_sel):
    from models import models_catalog as mc
    models = mc.list_models(conn)
    if view == "in_stock":
        models = [m for m in models if m["in_count"]]
    elif view == "sold":
        models = [m for m in models if m["out_count"]]
    models = _sorted(models, sort, view)
    full = mc.full_catalog(conn)
    cards = []
    for m in models:
        name = m["model"]
        g = full.get(name, {"sold": [], "in_stock": []})
        sold = g["sold"] if view in ("all", "sold") else []
        stock = g["in_stock"] if view in ("all", "in_stock") else []
        keys = " ".join([str(name)] + [str(i["wo"]) for i in sold + stock]
                        + [str(i["holder"]) for i in sold]).lower()
        chips = []
        if view in ("all", "in_stock"):
            chips.append(f'<span class="chip in">بالخزنة {m["in_count"]}'
                         f' · {_w(m["in_weight"])}</span>')
        if view in ("all", "sold"):
            chips.append(f'<span class="chip out">عند المناديب'
                         f' {m["out_count"]} · {_w(m["out_weight"])}</span>')
        det = []
        if sold:
            det.append('<h3 class="out">طرف المناديب</h3><table><tr>'
                       '<th>رقم التشغيل</th><th>الوزن</th><th>مع من</th>'
                       '<th>التاريخ</th></tr>' + "".join(
                           f'<tr{_rk(i, True)}><td>{_e(i["wo"])}</td>'
                           f'<td class="n">{_w(i["reg"])}</td>'
                           f'<td>{_e(i["holder"])}</td>'
                           f'<td class="n">{_e(i["date"])}</td></tr>'
                           for i in sold) + '</table>')
        if stock:
            det.append('<h3 class="in">الموجود (متاح للبيع)</h3><table><tr>'
                       '<th>رقم التشغيل</th><th>الوزن</th><th>أُدخل</th>'
                       '</tr>' + "".join(
                           f'<tr{_rk(i, False)}><td>{_e(i["wo"])}</td>'
                           f'<td class="n">{_w(i["reg"])}</td>'
                           f'<td class="n">{_e(i["date"])}</td></tr>'
                           for i in stock) + '</table>')
        n = len(sold) + len(stock)
        cards.append(
            f'<article class="card" data-s="{_e(keys)}"'
            f' data-m="{_e(str(name).lower())}">'
            f'{_photo(base, name, mc._safe_name(name) in imgs)}'
            f'<div class="b"><h2>الموديل {_e(name)}</h2>'
            f'<div class="chips">{"".join(chips)}'
            f'<span class="chip pick" style="display:none"></span></div>'
            + (f'<details><summary>التفاصيل — {n} قطعة</summary>'
               f'{"".join(det)}</details>' if det else "")
            + '</div></article>')
    n_in = sum(m["in_count"] for m in models)
    n_out = sum(m["out_count"] for m in models)
    w_in = sum(m["in_weight"] for m in models)
    w_out = sum(m["out_weight"] for m in models)
    summary = (f'<div>الموديلات<b>{len(models)}</b></div>'
               + (f'<div class="in">المتاح للبيع<b>{n_in} طقم · '
                  f'{_w(w_in)}</b></div>' if view != "sold" else "")
               + (f'<div class="out">عند المناديب<b>{n_out} طقم · '
                  f'{_w(w_out)}</b></div>' if view != "in_stock" else ""))
    tools = (f'<form class="tools" method="get" action="{_e(base)}">'
             f'<input type="hidden" name="tab" value="guide">'
             f'<input type="hidden" name="view" value="{view}">'
             f'<label>الفرز: <select name="sort" data-auto>{sort_sel}'
             f'</select></label></form>')
    body = "".join(cards) or '<div class="empty">لا موديلات</div>'
    return body, summary, tools


def _received(conn, query, base, view, sort, imgs, unit, sort_sel):
    from models import models_catalog as mc
    days = mc.received_days(conn, 120)
    day = query.get("day") if _DATE.match(query.get("day") or "") else ""
    d1 = query.get("from") if _DATE.match(query.get("from") or "") else ""
    d2 = query.get("to") if _DATE.match(query.get("to") or "") else ""
    if not (d1 and d2):
        day = day or (days[0]["date"] if days else "")
        d1 = d2 = day
    day_opts = "".join(
        f'<option value="{_e(d["date"])}"'
        f'{" selected" if d["date"] == day else ""}>{_e(d["date"])} — '
        f'{d["count"]} طقم · {d["models"]} موديل</option>' for d in days)
    tools = (f'<form class="tools" method="get" action="{_e(base)}">'
             f'<input type="hidden" name="tab" value="received">'
             f'<input type="hidden" name="view" value="{view}">'
             f'<select name="day" data-auto>{day_opts or "<option>لا وارد"}'
             f'</select>'
             f'<label>من <input type="date" name="from" value="'
             f'{_e(d1 if not day else "")}"></label>'
             f'<label>إلى <input type="date" name="to" value="'
             f'{_e(d2 if not day else "")}"></label>'
             f'<select name="sort" data-auto>{sort_sel}</select>'
             f'<button>عرض</button></form>')
    if not d1:
        return ('<div class="empty">لا وارد مسجَّل</div>', "", tools)
    res = mc.received(conn, d1, d2)
    models = []
    for m in res["models"]:
        items = [i for i in m["items"]
                 if view == "all" or (view == "in_stock" and i["safe"])
                 or (view == "sold" and not i["safe"])]
        if not items:
            continue
        g = dict(m, items=items, count=len(items),
                 weight=round(sum(i["reg"] for i in items), 2))
        g["in_count"] = sum(1 for i in items if i["safe"])
        g["out_count"] = g["count"] - g["in_count"]
        models.append(g)
    models = _sorted(models, sort, view)
    cards = []
    for m in models:
        name = m["model"]
        keys = " ".join([str(name)] + [str(i["wo"]) for i in m["items"]]
                        + [str(i["holder"]) for i in m["items"]]).lower()
        rows = "".join(
            f'<tr{_rk(i, True)}><td>{_e(i["wo"])}</td>'
            f'<td class="n">{_w(i["reg"])}</td>'
            f'<td>{_e(i["holder"])}{" · رصيد مجمّع" if i["bulk"] else ""}'
            f'</td><td class="n">{_e(i["date"])}</td></tr>'
            for i in m["items"])
        cards.append(
            f'<article class="card" data-s="{_e(keys)}"'
            f' data-m="{_e(str(name).lower())}">'
            f'{_photo(base, name, mc._safe_name(name) in imgs)}'
            f'<div class="b"><h2>الموديل {_e(name)}</h2>'
            f'<div class="chips"><span class="chip pick" style="display:none">'
            f'</span><span class="chip">{m["count"]} طقم ·'
            f' {_w(m["weight"])}</span>'
            + (f'<span class="chip in">بالخزنة {m["in_count"]}</span>'
               if m["in_count"] else "")
            + (f'<span class="chip out">عند الجهات {m["out_count"]}</span>'
               if m["out_count"] else "")
            + f'</div><details open><summary>أرقام التشغيل</summary>'
              f'<table><tr><th>رقم التشغيل</th><th>الوزن</th>'
              f'<th>مع من الآن</th><th>الوارد</th></tr>{rows}</table>'
              f'</details></div></article>')
    span = d1 if d1 == d2 else f"{d1} ← {d2}"
    n_in = sum(m["in_count"] for m in models)
    n_out = sum(m["out_count"] for m in models)
    summary = (f'<div>الوارد في<b>{_e(span)}</b></div>'
               f'<div>الموديلات<b>{len(models)}</b></div>'
               f'<div class="in">بالخزنة<b>{n_in} طقم</b></div>'
               f'<div class="out">عند الجهات<b>{n_out} طقم</b></div>')
    body = "".join(cards) or (f'<div class="empty">لا وارد في {_e(span)}'
                              f'</div>')
    return body, summary, tools


def login_page(base, error=""):
    err = (f'<p style="color:#a4262c;margin:0 0 10px">{_e(error)}</p>'
           if error else "")
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>دخول</title>
<style>{_CSS}
.box{{max-width:340px;margin:12vh auto;background:#fff;border-radius:16px;
border:1px solid var(--line);padding:22px;text-align:center}}
.box input{{width:100%;padding:12px;font-size:20px;text-align:center;
letter-spacing:6px;border:1px solid var(--line);border-radius:10px;
margin:8px 0 12px}}
.box button{{width:100%;padding:12px;border:0;border-radius:10px;
background:var(--brown);color:#fff;font-size:16px}}</style></head><body>
<div class="box"><h2 style="margin:0 0 6px;color:var(--brown)">دليل
 الموديلات</h2><p style="color:var(--muted);margin:0 0 10px">أدخل رمز
 الدخول</p>{err}
<form method="post" action="{_e(base)}/login">
<input name="pin" type="password" inputmode="numeric" autocomplete="off"
 autofocus required minlength="4" maxlength="12">
<button>دخول</button></form></div></body></html>"""
