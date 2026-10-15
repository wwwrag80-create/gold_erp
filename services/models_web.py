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
محاولاتٍ خاطئة متكررة. والخادم **قراءةٌ فقط** إلا في أمرٍ واحد (4.65):
**طلبات العملاء** — تُسجَّل وتُعدَّل وتُطبع من الرابط كما في البرنامج،
فتُحفظ في قاعدة جهاز المصنع وتظهر في البرنامج وفي الرابط معاً. والكتابة
بنموذجٍ (POST) يحمل رمز تحقّقٍ من الصفحة نفسها (CSRF)، وكل حفظٍ يُسجَّل في
سجل التتبع باسم «رابط المدير». ولا مسار غيره يكتب في القاعدة.
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
# المصغّرة أكبر قليلاً (4.57): الجوال يكبّر الشبكة بالأصابع فتُرى الصورة
# بأضعاف حجمها في الصف، وكاملُها يُفتح بالنقر عليها
THUMB_W, FULL_W = 640, 1600
CACHE_CAP = 96 * 1024 * 1024         # ذاكرة الصور المصغّرة (في الذاكرة)
IMG_CHECK_S = 20                     # الصفحة المفتوحة تتحقّق من تغيّر الصور
LOCK_AFTER, LOCK_WINDOW = 10, 15 * 60

_lock = threading.Lock()
_fails = []                          # أوقات محاولات رمز الدخول الخاطئة
_thumbs = OrderedDict()              # (المسار, التعديل, العرض) → بايتات
_thumb_bytes = [0]
# 4.66: تصغير الصور ثقيل — ثلاثٌ معاً على الأكثر، والبقية تنتظر دورها بدل
# أن تتزاحم كلها فتبطؤ جميعاً حتى ينقطع بعضها في الطريق إلى الجوال
_gen = threading.BoundedSemaphore(3)
_warming = [False]


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
    addr = photo_server.ensure_running(wait=8)
    if not addr:
        return {"ok": False, "url": "", "lan": "", "mode": st["mode"],
                "reason": "server",
                "message": "تعذّر تشغيل الخادم على هذا الجهاز (منفذ مشغول"
                           " أو جدار حماية)"}
    register()
    warm_async()                     # المصغّرات جاهزةٌ قبل أول فتح
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


# ══════════════════════════════════════════════════════════════════
#  فحص الرابط طبقةً طبقة (4.58)
# ══════════════════════════════════════════════════════════════════
# «الرابط لا يعمل على الجوال» جملةٌ واحدة لأعطالٍ مختلفة تماماً: البرنامج
# مغلق · الصفحة فيها خطأ · جدار الحماية · Tailscale غير متصل · العنوان
# الثابت غير موجَّه إلى البرنامج · الجوال يفتح رابط الشبكة المحلية من
# خارجها. والفحص يجرّب كل طبقة بالترتيب من جهاز المصنع نفسه ويقول أين
# انقطع الطريق وما إصلاحه — بدل التخمين.

FW_RULE = "Jadeite Models Link"


def _http_get(url, timeout, local=False):
    """(رمز HTTP أو None, نصّ قصير) — بلا وكيل للعناوين المحلية."""
    import urllib.error
    import urllib.request
    handlers = [urllib.request.ProxyHandler({})] if local else []
    op = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent":
                                               "Jadeite-LinkCheck"})
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, r.read(1500).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(1500).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:                          # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def ts_targets():
    """المنافذ المحلية التي وجّه إليها Tailscale عنوانَ الجهاز الثابت."""
    out = set()
    funnel = False
    for cmd in (["funnel", "status", "--json"], ["serve", "status",
                                                  "--json"]):
        res = RUNNER(cmd, 15)
        if not res:
            continue
        _c, txt = res
        for m in re.finditer(r"127\.0\.0\.1:(\d+)|localhost:(\d+)", txt):
            out.add(int(m.group(1) or m.group(2)))
        if '"AllowFunnel"' in txt and "true" in txt.split(
                '"AllowFunnel"', 1)[1][:200]:
            funnel = True
    return out, funnel


def firewall_ok(port):
    """هل لقاعدة البرنامج في جدار حماية ويندوز أثر؟ (None خارج ويندوز)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             f"name={FW_RULE}"], capture_output=True, timeout=10,
            creationflags=0x08000000)
        return r.returncode == 0 and str(port).encode() in (r.stdout or b"")
    except Exception:
        return None


def firewall_allow(first_port=None):
    """يضيف استثناءً في جدار حماية ويندوز (يطلب موافقة المسؤول).

    يفتح نافذة «هل تسمح لهذا البرنامج بإجراء تغييرات؟» — بلا موافقتها
    لا يتغيّر شيء. المنافذ وحدها التي يستعملها الخادم (8733–8742).
    """
    if not sys.platform.startswith("win"):
        return False
    from services import photo_server
    a = int(first_port or photo_server.DEFAULT_PORT)
    args = (f'advfirewall firewall add rule name="{FW_RULE}" dir=in '
            f'action=allow protocol=TCP localport={a}-{a + 9} profile=any')
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh",
                                                 args, None, 0)
        return int(rc) > 32
    except Exception:
        return False


def diagnose():
    """يجرّب الرابط طبقةً طبقة — قائمة {key, ok, title, detail, fix}.

    `ok`: True نجح · False انقطع هنا · None معلومة/تنبيه.
    `fix`: activate · firewall · ts_install · ts_login · ts_enable · report
    """
    import config
    from database.database import db
    from services import photo_server
    out = []

    def add(key, ok, title, detail="", fix="", url=""):
        out.append({"key": key, "ok": ok, "title": title,
                    "detail": str(detail or ""), "fix": fix, "url": url})

    add("version", None, f"الإصدار الذي يعرض الرابط: "
                         f"{getattr(config, 'APP_VERSION', '?')}")
    with db(readonly=True) as conn:
        st = settings(conn)
    if not (st["enabled"] and st["token"]):
        add("enabled", False, "الرابط موقوف في البرنامج",
            "لا يُفتح من أي مكان حتى يُفعَّل.", "activate")
        return out
    add("enabled", True, "الرابط مفعّل في البرنامج")
    addr = photo_server.current()
    if not addr:
        add("server", False, "الخادم لا يعمل على هذا الجهاز",
            "اضغط «تفعيل الرابط» لتشغيله.", "activate")
        return out
    port = addr[1]
    add("server", True, f"الخادم يعمل على المنفذ {port}")
    tok = st["token"]
    try:
        with db(readonly=True) as conn:
            body = page_html(conn, {}, f"/{PREFIX}/{tok}")
        add("page", True, f"الصفحة تُبنى بلا أخطاء ({len(body) // 1024}"
                          " ك.ب)")
    except Exception as e:                          # noqa: BLE001
        import traceback
        add("page", False, "الصفحة فيها خطأ في البرنامج",
            f"{type(e).__name__}: {e}\n"
            + traceback.format_exc(limit=4), "report")
    le = photo_server.last_error()
    if le:
        add("last_error", None, f"آخر خطأ أثناء فتح الصفحة ({le['at']})",
            le["error"], "report")
    code, txt = _http_get(f"http://127.0.0.1:{port}/{PREFIX}/{tok}", 10,
                          local=True)
    add("local", code == 200, "الصفحة تُفتح على هذا الجهاز"
        if code == 200 else "الصفحة لا تُفتح حتى على هذا الجهاز",
        "" if code == 200 else f"HTTP {code or '—'} {txt[:200]}", "report")
    lan = f"http://{addr[0]}:{port}/{PREFIX}/{tok}"
    if str(addr[0]).startswith("127."):
        add("lan", False, "الجهاز غير متصل بشبكة محلية",
            "رابط شبكة المصنع لا يعمل — يلزم الرابط الثابت عبر الإنترنت.")
    else:
        fw = firewall_ok(port)
        add("lan", None, "رابط شبكة المصنع (يعمل فقط والجوال على Wi-Fi"
                         " المصنع نفسه)", lan, url=lan)
        if fw is False:
            add("firewall", False, "جدار حماية ويندوز قد يمنع الجوال على"
                                   " شبكة المصنع",
                "يحتاجه رابط شبكة المصنع وحده (الرابط الثابت عبر الإنترنت"
                " لا يتأثر به). «السماح عبر الجدار» يطلب موافقة المسؤول.",
                "firewall")
        elif fw:
            add("firewall", True, "جدار حماية ويندوز يسمح بالرابط")
    if st["mode"] == "lan":
        add("mode", None, "نوع الرابط: «شبكة المصنع» — لا يُفتح من خارجها",
            "لرابطٍ يُفتح من أي مكان اختر «ثابت عبر الإنترنت» ثم «تفعيل"
            " الرابط».")
        return out
    ts = ts_status()
    if not ts["installed"]:
        add("ts", False, "برنامج Tailscale غير مثبّت على هذا الجهاز",
            "بدونه لا يوجد رابط ثابت عبر الإنترنت، ويعمل الرابط على شبكة"
            " المصنع وحدها. نزّله مجاناً ثم سجّل الدخول وفعّل الرابط.",
            "ts_install", "https://tailscale.com/download/windows")
        return out
    if not (ts["running"] and ts["dns"]):
        add("ts", False, "Tailscale مثبّت لكنه غير متصل",
            f"الحالة: {ts.get('state') or '—'} — افتحه وسجّل الدخول ثم"
            " «تفعيل الرابط».", "ts_login", ts.get("login_url") or "")
        return out
    add("ts", True, f"Tailscale متصل — اسم الجهاز {ts['dns']}")
    targets, funnel_on = ts_targets()
    if port not in targets:
        add("route", False, "العنوان الثابت غير موجَّه إلى البرنامج",
            ("موجّه إلى المنفذ " + ", ".join(map(str, sorted(targets)))
             if targets else "لا توجيه مسجّل في Tailscale")
            + " — «تفعيل الرابط» يعيد توجيهه.", "activate")
    else:
        add("route", True, f"العنوان الثابت موجَّه إلى المنفذ {port}")
    if st["mode"] == "funnel" and not funnel_on:
        add("funnel", False, "ميزة Funnel (الفتح من الإنترنت) غير مفعّلة"
                             " في حساب Tailscale",
            "«تفعيل الرابط» يُظهر رابط الموافقة عليها — افتحه ووافق.",
            "activate")
    url = ts_url(ts["dns"], tok)
    code, txt = _http_get(url, 25)
    if code == 200:
        add("public", True, "الرابط الثابت يُفتح عبر الإنترنت", url,
            url=url)
    else:
        why = txt[:220] if code is None else f"HTTP {code}"
        if code is None and ("getaddrinfo" in txt or "Name or service"
                             in txt or "11001" in txt):
            why += " — اسم الرابط لم ينتشر بعد (قد يستغرق دقائق بعد أول" \
                   " تفعيل)"
        add("public", False, "الرابط الثابت لا يُفتح عبر الإنترنت", why,
            "activate", url)
    return out


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
        " script-src 'unsafe-inline'; connect-src 'self';"
        " form-action 'self'; base-uri 'none'"),
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
    if rest[:1] == ["order"]:
        return _order_route(method, rest[1:], query, body, base,
                            _csrf(token, secret), not pin_hash)
    if method != "GET":
        return _resp(405, _GONE)
    if rest[:1] == ["img"] and len(rest) == 2:
        return _image(rest[1], query.get("full") == "1", query.get("v"),
                      headers)
    if rest == ["imgver"]:
        return _resp(200, json.dumps(_img_versions()), "application/json",
                     {"Cache-Control": "no-store"})
    if rest:
        return _resp(404, _GONE)
    with db(readonly=True) as conn:
        return _resp(200, page_html(conn, query, base))


def _ver_of(path):
    """إصدار الصورة من تاريخ ملفها وحجمه — يتغيّر متى استُبدلت أو عولجت."""
    from models.models_catalog import file_stamp
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return f"{file_stamp(st):x}-{st.st_size:x}"


def _vkey(model):
    """مفتاح صورة الموديل في `_img_versions` — بلا فرقٍ بين الحروف
    الكبيرة والصغيرة كملفات ويندوز (A12 وa12 ملفٌ واحد هناك)."""
    from models.models_catalog import _safe_name
    return _safe_name(model).casefold()


def _img_versions():
    """{مفتاح الصورة: إصدارها} لكل صور الدليل — بقراءة المجلد مرةً واحدة.

    **لماذا**: كان رابط الصورة ثابتاً والجوال يحتفظ بها عشر دقائق، فإن
    استُبدلت صورة موديلٍ بقي الجوال يعرض القديمة. الآن الإصدار جزءٌ من
    الرابط (`?v=`) — صورةٌ جديدة = رابطٌ جديد، فتظهر فوراً. وإن تعدّد
    للموديل ملفان فالأحدث — كما يختار `image_path` تماماً.
    """
    from models import models_catalog as mc
    out, newest = {}, {}
    try:
        for f in mc.images_dir().iterdir():
            if f.suffix.lower() in mc.IMAGE_EXTS:
                try:
                    st = f.stat()
                except OSError:
                    continue
                k = f.stem.casefold()
                t = mc.file_stamp(st)
                if t > newest.get(k, -1):
                    newest[k] = t
                    out[k] = f"{t:x}-{st.st_size:x}"
    except Exception:
        pass
    return out


def _img_url(base, model, ver, full=False):
    q = (["full=1"] if full else []) + ([f"v={ver}"] if ver else [])
    return (f"{base}/img/{quote(str(model), safe='')}"
            + ("?" + "&".join(q) if q else ""))


def _find_ci(model_no):
    """صورة الموديل بلا فرقٍ بين الحروف الكبيرة والصغيرة — كما تراها
    الصفحة (`_vkey`)، على أي نظام ملفات. يُستدعى عند تعذّر المطابقة
    التامة وحدها."""
    from models import models_catalog as mc
    key, best, best_t = _vkey(model_no), None, -1
    try:
        for f in mc.images_dir().iterdir():
            if f.suffix.lower() in mc.IMAGE_EXTS \
                    and f.stem.casefold() == key:
                t = mc.file_stamp(f.stat())
                if t > best_t:
                    best, best_t = f, t
    except OSError:
        return None
    return best


def _image(model_no, full, v=None, headers=None):
    from models import models_catalog as mc
    try:
        p = mc.image_path(model_no) or _find_ci(model_no)
    except Exception:
        p = None
    if p is None:
        return _resp(404, b"", "text/plain")
    ver = _ver_of(p)
    etag = f'"{ver}-{"f" if full else "t"}"'
    # برابطٍ يحمل الإصدار الحالي: تُحفظ في الجوال طويلاً (لن تتغيّر تحت
    # هذا الرابط أبداً). وبلا إصدار أو بإصدارٍ قديم: يُسأل الجهاز كل مرة
    cache = ("private, max-age=31536000, immutable" if v and v == ver
             else "private, no-cache")
    inm = (headers.get("If-None-Match") if headers is not None else "") or ""
    if etag in inm:
        return _resp(304, b"", "image/jpeg",
                     {"Cache-Control": cache, "ETag": etag})
    data, ctype = thumb(p, FULL_W if full else THUMB_W)
    if not data:
        return _resp(404, b"", "text/plain")
    return _resp(200, data, ctype, {"Cache-Control": cache, "ETag": etag})


def warm_async():
    """يجهّز مصغّرات الدليل في الخلفية بترتيب الصفحة (4.66).

    أول فتحٍ للرابط بعد تشغيل البرنامج كان يصغّر كل الصور لحظتها فيبطؤ
    بعضها حتى يتعثّر. والتجهيز يقف قبل امتلاء ذاكرة المصغّرات فلا يطرد
    بعضُه بعضاً.
    """
    with _lock:
        if _warming[0]:
            return
        _warming[0] = True

    def run():
        try:
            from models import models_catalog as mc
            files = sorted((f for f in mc.images_dir().iterdir()
                            if f.suffix.lower() in mc.IMAGE_EXTS),
                           key=lambda f: mc.model_key(f.stem))
            for f in files:
                with _lock:
                    full = _thumb_bytes[0] > CACHE_CAP * 0.85
                if full:
                    break
                thumb(f, THUMB_W)
        except Exception:
            pass
        finally:
            with _lock:
                _warming[0] = False
    threading.Thread(target=run, daemon=True,
                     name="models-web-warm").start()


def thumb(path, width):
    """الصورة مصغّرةً ومضغوطة (JPEG) — من الذاكرة إن سبق تصغيرها."""
    try:
        st = os.stat(path)
    except OSError:
        return b"", ""
    from models.models_catalog import file_stamp
    key = (str(path), file_stamp(st), st.st_size, int(width))
    with _lock:
        hit = _thumbs.get(key)
        if hit is not None:
            _thumbs.move_to_end(key)
            return hit
    with _gen:
        with _lock:                  # صغّرها خيطٌ آخر وهذا ينتظر دوره؟
            hit = _thumbs.get(key)
        if hit is not None:
            return hit
        return _make_thumb(path, width, key)


def _make_thumb(path, width, key):
    import mimetypes
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:                   # تُستبدل الآن — والصفحة تعيد المحاولة
        return b"", ""
    out = (raw, mimetypes.guess_type(str(path))[0] or "image/jpeg")
    try:
        from PyQt5.QtCore import QBuffer, QByteArray
        from PyQt5.QtGui import QImage
        img = QImage()
        if img.loadFromData(raw):
            if img.width() > width:
                img = img.scaledToWidth(int(width), 1)    # 1 = Smooth
            # JPEG بلا شفافية: الصورة المزالة خلفيتها تُوضع على أبيض
            # البطاقة نفسه — وإلا خرجت الأجزاء الشفافة سوداء
            from services.cutout import flatten
            img = flatten(img)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QBuffer.WriteOnly)
            # 84 لا 70: خطوط الرسومات الدقيقة تتلطّخ بضغط JPEG الشديد
            if img.save(buf, "JPEG", 84):
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

# ══ تصميم الكمبيوتر حتى على الجوال (4.57) ══
# الصفحة تُرسم بعرضٍ ثابت كموقع كمبيوتر (`DESKTOP_W`)، فيفتحها الجوال
# مصغّرةً كاملة: خمس صورٍ في الصف (أو أربع/ست بالاختيار)، والتكبير
# والتصغير بالأصابع والتمرير في كل اتجاه كما في أي موقع كمبيوتر — لا
# صورةً واحدة في الشاشة يُسحب بعدها إلى الأسفل.
DESKTOP_W = 1280
COLS = (4, 5, 6)
DEFAULT_COLS = 5

_CSS = """
:root{--bg:#F6F2EA;--card:#fff;--ink:#2b2723;--muted:#776b5e;--line:#e7dfd1;
--brown:#5A3E1B;--gold:#A8822E;--in:#1E6B33;--out:#8B5E1E;--cols:5}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);min-width:1200px;
font-family:system-ui,"Segoe UI",Tahoma,sans-serif;font-size:14px}
header{background:var(--brown);color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.15)}
header .hi{max-width:1500px;margin:auto;padding:12px 22px;display:flex;
align-items:center;gap:20px}
header h1{font-size:20px;margin:0;white-space:nowrap}
header .sub{font-size:12px;opacity:.85;margin-top:3px;white-space:nowrap}
.bar{flex:1 1 auto;display:flex;justify-content:flex-end}
.bar input[type=search]{width:460px;padding:9px 12px;border:0;
border-radius:9px;font-size:14px}
main{padding:16px 22px;max-width:1500px;margin:auto}
.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
margin:0 0 12px}
.tabs,.seg{display:flex;gap:6px;flex-wrap:wrap}
.tabs a,.seg a{padding:7px 14px;border-radius:20px;background:#fff;
border:1px solid var(--line);color:var(--ink);text-decoration:none;
font-size:13.5px;white-space:nowrap}
.tabs a.on,.seg a.on{background:var(--gold);border-color:var(--gold);
color:#fff;font-weight:600}
.sep{width:1px;height:26px;background:var(--line)}
form.tools{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:0}
form.tools select,form.tools input,form.tools button{padding:6px 9px;
border:1px solid var(--line);border-radius:8px;background:#fff;font-size:13px}
form.tools button{background:var(--brown);color:#fff;border-color:var(--brown)}
.cols{display:flex;align-items:center;gap:4px;margin-inline-start:auto;
color:var(--muted);font-size:13px;white-space:nowrap}
.cols button{min-width:34px;padding:5px 0;border:1px solid var(--line);
border-radius:8px;background:#fff;color:var(--ink);font-weight:600;
font-size:13px;cursor:pointer}
.cols button.on{background:var(--brown);color:#fff;border-color:var(--brown)}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
gap:10px;margin:0 0 14px}
.sum div{background:#fff;border:1px solid var(--line);border-radius:12px;
padding:9px 12px}
.sum b{display:block;font-size:18px;margin-top:2px}
.sum .in b{color:var(--in)} .sum .out b{color:var(--out)}
.grid{display:grid;gap:14px;align-items:start;
grid-template-columns:repeat(var(--cols),minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
overflow:hidden;display:flex;flex-direction:column}
.ph{display:block;background:transparent;aspect-ratio:1/1;padding:6px}
.ph img{width:100%;height:100%;object-fit:contain;display:block}
.noimg{display:flex;align-items:center;justify-content:center;
color:var(--muted);font-size:13px;aspect-ratio:1/1;background:#f1ece2}
.b{padding:8px 10px 10px}
.b h2{font-size:15px;margin:0 0 6px;color:var(--brown)}
.chips{display:flex;gap:5px;flex-wrap:wrap}
.chip{font-size:12px;padding:2px 8px;border-radius:11px;background:#f3efe6;
white-space:nowrap}
.chip.in{color:var(--in);background:#e8f3ea}
.chip.out{color:var(--out);background:#f7eddd}
.chip.pick{color:#fff;background:#8a6d1d;font-weight:bold}
.sum .pick{grid-column:1/-1;border-color:#8a6d1d}
details{margin-top:7px;border-top:1px dashed var(--line);padding-top:5px}
summary{cursor:pointer;color:var(--gold);font-weight:600;font-size:13px}
h3{font-size:12.5px;margin:7px 0 3px}
h3.in{color:var(--in)} h3.out{color:var(--out)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:4px 3px;border-bottom:1px solid #f0ebe1;text-align:right;
vertical-align:top}
td .who{display:block}
td .d{display:block;color:var(--muted);font-size:10.5px;direction:ltr;
text-align:right;white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:11.5px;line-height:1.25}
details{overflow-x:auto}
td.n{direction:ltr;text-align:left;white-space:nowrap}
.empty{padding:30px;text-align:center;color:var(--muted);grid-column:1/-1}
.orders{display:flex;flex-direction:column;gap:16px}
.order{background:#fff;border:1px solid var(--line);border-radius:14px;
padding:12px 14px}
.oh{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px;
margin:0 0 10px;font-size:14px}
.oh .no{font-size:16px;font-weight:700;color:var(--brown)}
.oh .cu{font-size:16px;font-weight:700}
.oh .m{color:var(--muted);font-size:13px}
.st{padding:2px 10px;border-radius:11px;font-size:12px;font-weight:600}
.st.open{background:#f7eddd;color:var(--out)}
.st.done{background:#e8f3ea;color:var(--in)}
.st.cancelled{background:#eee;color:#777}
.og{display:grid;gap:10px;grid-template-columns:repeat(var(--cols),minmax(0,1fr))}
.oc{border:1px solid var(--line);border-radius:10px;overflow:hidden;
background:#fff}
.oc .b h2{font-size:14px;margin:0 0 5px}
.chip.q{color:#fff;background:var(--gold);font-weight:700}
.chip.short{color:#a4262c;background:#fbeaea}
.onote{margin-top:8px;color:var(--muted);font-size:13px}
.prod{background:#fff;border:1px solid var(--line);border-radius:14px;
padding:8px 14px}
.prod table{font-size:13px;margin-top:6px}
.prod th,.prod td,.prod td.n{text-align:center}
.prod th:first-child,.prod td:first-child,.prod th:last-child,
.prod td:last-child{text-align:right}
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
  // 4.59: الطلبات — بالعميل أو رقم الطلب أو رقم موديلٍ فيه
  // 4.73: والعملاء — باسم العميل أو رقم حسابه
  document.querySelectorAll('.order,tr.crow').forEach(function(o){
   var hit=!v||(o.getAttribute('data-s')||'').indexOf(v)>=0;
   o.style.display=hit?'':'none'; if(hit)n++;});
  var e=document.getElementById('none'); if(e)e.style.display=n?'none':'';
  if(sum){sum.style.display=(v&&tn)?'':'none';
   sum.innerHTML='نتيجة البحث «'+v.replace(/[<>&"]/g,'')+'»<b>'+n+
    ' موديل · '+tn+' طقم · '+fmt(tw)+'</b>';}
 }
 if(q){q.addEventListener('input',run); if(q.value){run();}}
 // عدد الصور في الصف — يُحفظ في الجهاز نفسه
 var cb=document.querySelectorAll('.cols button[data-c]');
 function setCols(n){
  document.documentElement.style.setProperty('--cols',n);
  cb.forEach(function(b){b.classList.toggle('on',b.getAttribute('data-c')==n);});
  try{localStorage.setItem('mw_cols',n);}catch(e){}}
 var sv=null; try{sv=localStorage.getItem('mw_cols');}catch(e){}
 if(cb.length){setCols(sv&&/^[3-8]$/.test(sv)?sv:
  (document.documentElement.getAttribute('data-cols')||'5'));}
 cb.forEach(function(b){b.addEventListener('click',function(){
  setCols(b.getAttribute('data-c'));});});
 document.querySelectorAll('select[data-auto]').forEach(function(s){
  s.addEventListener('change',function(){s.form.submit();});});
})();
"""


_IMG_JS = """
(function(){
 // 4.66: صورةٌ تعثّر تحميلها (انقطاعٌ في الطريق أو استبدالٌ لحظتها)
 // تُعاد تلقائياً بمهلةٍ تتضاعف — بدل أن تبقى مكسورة
 document.addEventListener('error',function(e){var t=e.target;
  if(!t||t.tagName!=='IMG')return;var n=+(t.getAttribute('data-r')||0);
  if(n>=5)return;t.setAttribute('data-r',n+1);
  setTimeout(function(){var u=t.src.replace(/([?&])r=\\d+&?/,'$1')
   .replace(/[?&]$/,'');t.src=u+(u.indexOf('?')<0?'?':'&')+'r='+(n+1);},
   800*Math.pow(2,n));},true);
 // والصورة المستبدَلة أو المضافة تظهر في الصفحة المفتوحة وحدها
 var base=document.documentElement.getAttribute('data-base');
 if(!base||!window.fetch)return;
 function setv(u,v){return /[?&]v=/.test(u)?u.replace(/([?&]v=)[^&]*/,'$1'+v)
  :u+(u.indexOf('?')<0?'?':'&')+'v='+v;}
 function apply(m){
  document.querySelectorAll('img[data-s]').forEach(function(t){
   var v=m[t.getAttribute('data-s')];
   if(!v||v===t.getAttribute('data-v'))return;
   t.setAttribute('data-v',v);t.removeAttribute('data-r');
   t.src=setv(t.src.replace(/([?&])r=\\d+&?/,'$1').replace(/[?&]$/,''),v);
   var a=t.closest('a');if(a)a.href=setv(a.href,v);});
  document.querySelectorAll('.noimg[data-s]').forEach(function(d){
   var s=d.getAttribute('data-s'),v=m[s];if(!v)return;
   var n=d.getAttribute('data-n'),u=base+'/img/'+encodeURIComponent(n);
   var a=document.createElement('a');a.className='ph';a.target='_blank';
   a.rel='noopener';a.href=u+'?full=1&v='+v;
   var i=document.createElement('img');i.src=u+'?v='+v;i.alt=n;
   i.setAttribute('data-s',s);i.setAttribute('data-v',v);
   a.appendChild(i);d.parentNode.replaceChild(a,d);});}
 function check(){
  if(document.visibilityState&&document.visibilityState!=='visible')return;
  fetch(base+'/imgver',{cache:'no-store',credentials:'same-origin'})
   .then(function(r){return r.ok?r.json():null;})
   .then(function(m){if(m)apply(m);}).catch(function(){});}
 setInterval(check,%d);
 document.addEventListener('visibilitychange',check);
 window.addEventListener('pageshow',function(e){if(e.persisted)check();});
})();
""" % (IMG_CHECK_S * 1000)


def _e(v):
    return html.escape(str(v if v is not None else ""), quote=True)


def _w(v):
    from services import karat_view as kv
    return f"{kv.g(float(v or 0)):,.2f}"


def _who(holder, date, bulk=False):
    """الجهة وتحتها التاريخ بخطٍّ صغير — ثلاثة أعمدة تتّسع لها البطاقة
    في صفٍّ من خمس، فلا يُقصّ التاريخ ولا يُكسر الاسم بين حروفه."""
    extra = " · رصيد مجمّع" if bulk else ""
    return (f'<span class="who">{_e(holder)}{extra}</span>'
            f'<small class="d">{_e(date)}</small>')


def _version():
    try:
        import config
        return str(getattr(config, "APP_VERSION", ""))
    except Exception:
        return ""


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


def _photo(base, model, ver):
    """صورة الموديل برابطٍ يحمل إصدارها — أو «لا توجد صورة» تتحوّل إلى
    الصورة وحدها إن أُضيفت والصفحة مفتوحة (`_IMG_JS`)."""
    s = _e(_vkey(model))
    if not ver:
        return (f'<div class="noimg" data-s="{s}" data-n="{_e(model)}">'
                'لا توجد صورة</div>')
    return (f'<a class="ph" href="{_e(_img_url(base, model, ver, True))}"'
            f' target="_blank" rel="noopener"><img loading="lazy"'
            f' src="{_e(_img_url(base, model, ver))}" alt="{_e(model)}"'
            f' data-s="{s}" data-v="{_e(ver)}"></a>')


def page_html(conn, query, base):
    """الشاشة كاملةً بتصميم الكمبيوتر (يُفتح كذلك على الجوال ويُكبَّر
    بالأصابع) — الدليل، أو البضاعة الواردة بتاريخ."""
    from datetime import datetime

    from services import karat_view as kv
    tab = query.get("tab") if query.get("tab") in (
        "guide", "received", "orders", "customers") else "guide"
    view = query.get("view") if query.get("view") in (
        "all", "in_stock", "sold") else "all"
    sort = query.get("sort") if query.get("sort") in (
        "az", "za", "most", "least") else "az"
    imgs = _img_versions()               # {اسم الملف: إصدار الصورة}
    warm_async()
    unit = _e(kv.unit())

    try:
        from models import model_orders as _mo
        n_orders = _mo.count_open(conn)
    except Exception:
        n_orders = 0
    tabs = "".join(
        f'<a class="{"on" if tab == k else ""}"'
        f' href="{_e(_link(base, tab=k, view=view, sort=sort))}">{t}</a>'
        for k, t in (("guide", "الدليل"),
                     ("received", "البضاعة الواردة بتاريخ"),
                     ("orders", "طلبات العملاء"
                      + (f" ({n_orders})" if n_orders else "")),
                     ("customers", "العملاء — المبيعات والسداد")))
    seg = "".join(
        f'<a class="{"on" if view == k else ""}" href="'
        f'{_e(_link(base, tab=tab, view=k, sort=sort, day=query.get("day")))}'
        f'">{t}</a>'
        for k, t in (("all", "الكل"), ("in_stock", "المتاح للبيع"),
                     ("sold", "طرف المناديب")))
    if tab == "orders":
        st = query.get("st") if query.get("st") in (
            "open", "done", "all") else "open"
        seg = "".join(
            f'<a class="{"on" if st == k else ""}" href="'
            f'{_e(_link(base, tab="orders", st=k))}">{t}</a>'
            for k, t in (("open", "المفتوحة"), ("done", "المُسلَّمة"),
                         ("all", "الكل")))
    sort_sel = "".join(
        f'<option value="{k}"{" selected" if sort == k else ""}>{t}</option>'
        for k, t in (("az", "أ ← ي"), ("za", "ي ← أ"),
                     ("most", "الأكثر عدداً"), ("least", "الأقل عدداً")))

    if tab == "customers":
        body, summary, tools, seg = _board(conn, query, base)
    elif tab == "received":
        body, summary, tools = _received(conn, query, base, view, sort,
                                         imgs, unit, sort_sel)
    elif tab == "orders":
        body, summary, tools = _orders(conn, base, st, imgs)
    else:
        body, summary, tools = _guide(conn, base, view, sort, imgs, unit,
                                      sort_sel)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    co = _company().strip()
    board = tab == "customers"
    title = (("العملاء — المبيعات والسداد" if board else "دليل الموديلات")
             + (f" — {_e(co)}" if co else ""))
    cols = "".join(f'<button type="button" data-c="{c}">{c}</button>'
                   for c in COLS)
    cols_bar = ("" if board else
                f'<div class="cols">الصور في الصف: {cols}</div>')
    hint = ("ابحث باسم العميل أو رقم حسابه…" if board else
            "ابحث برقم الموديل أو رقم التشغيل أو اسم الجهة…")
    sect = ("board" if board else
            "orders" if tab == "orders" else "grid")
    again = (_link(base, tab=tab, side=query.get("side"),
                   **{k: query.get(k)
                      for k in ("from", "to", "all", "f", "dim")})
             if board else
             _link(base, tab=tab, view=view, sort=sort,
                   day=query.get('day'), st=query.get('st')))
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar" data-cols="{DEFAULT_COLS}" data-base="{_e(base)}"><head>
<meta charset="utf-8">
<meta name="viewport" content="width={DESKTOP_W}">
<meta name="robots" content="noindex,nofollow">
<title>{title}</title>
<style>{_CSS}{_ORDER_CSS}{_BOARD_CSS}</style></head><body>
<header><div class="hi"><div class="t"><h1>{title}</h1>
<div class="sub">مباشرةً من جهاز المصنع · {now} · الأوزان {unit}</div></div>
<div class="bar"><input id="q" type="search"
 placeholder="{hint}"></div>
</div></header><main>
<div class="top"><nav class="tabs">{tabs}</nav><span class="sep"></span>
<nav class="seg">{seg}</nav><span class="sep"></span>
{tools}
{cols_bar}</div>
<section class="sum">{summary}<div id="pick" class="pick"
 style="display:none"></div></section>
<section class="{sect}">{body}</section>
<div id="none" class="empty" style="display:none">لا نتائج للبحث</div>
</main>
<footer><a href="{_e(again)}">↻ تحديث</a>
 · إصدار {_e(_version())}
 · <a href="{_e(base)}/logout">خروج</a></footer>
<script>{_JS}{_IMG_JS}</script></body></html>"""


# ══════════════════════════════════════════════════════════════════
#  العملاء — المبيعات والسداد (4.73): شاشة العملاء نفسها في الرابط
# ------------------------------------------------------------------
#  الأرقام من `customer_board.board` الذي تقرأ منه الشاشة على الجهاز —
#  فلا يختلف ما يراه المدير في الرابط عمّا في البرنامج. ثلاثة أقسام
#  كالشاشة: الذهب · النقد · نظرة عامة، والفترة أو «منذ البداية».
# ══════════════════════════════════════════════════════════════════

_BOARD_CSS = """
.board{background:#fff;border:1px solid var(--line);border-radius:12px;
padding:6px 8px;overflow:auto}
.board table{font-size:13px}
.board th{position:sticky;top:0;background:#f4efe5;color:var(--ink);
padding:8px 6px;border-bottom:2px solid var(--line);line-height:1.3}
.board td{padding:7px 6px;border-bottom:1px solid #f0eadf;text-align:center;
white-space:nowrap;font-variant-numeric:tabular-nums}
.board td.n{text-align:right;font-weight:600}
.board tr.crow:nth-child(even) td{background:#fbf8f2}
.board tr.tot td{background:#2b2723;color:#fff;font-weight:700}
.board td.rem{font-weight:700}
.g-ok{color:var(--in);font-weight:600} .g-mid{color:#8a6d1d;font-weight:600}
.g-low{color:#b0791c;font-weight:600} .g-bad{color:#b3261e;font-weight:600}
.cr{color:var(--in)} .late{color:#b3261e}
form.tools label{display:flex;gap:4px;align-items:center;font-size:13px}
"""

_GRADE_CSS = {"مسدَّد": "g-ok", "ممتاز": "g-ok", "جيد": "g-mid",
              "مقبول": "g-low", "سيء": "g-bad"}


def _board_period(query):
    """الفترة من الرابط: «منذ البداية» افتراضاً كالشاشة."""
    from datetime import date
    to = query.get("to") if _DATE.match(query.get("to") or "") else ""
    to = to or date.today().isoformat()
    frm = query.get("from") if _DATE.match(query.get("from") or "") else ""
    # النموذج يرسل `f=1`: بلا مربّع «منذ البداية» المؤشَّر ← الفترة
    all_ = (query.get("all") == "1") if query.get("f") == "1" else not frm
    if not frm:
        frm = f"{to[:4]}-01-01"
    return (None if all_ else frm), frm, to, all_


def _board(conn, query, base):
    from models import customer_board as cb
    from services import karat_view as kv
    side = query.get("side") if query.get("side") in (
        "gold", "cash", "over", "aging") else "gold"
    d_from, frm, to, all_ = _board_period(query)
    res = cb.board(conn, d_from, to)
    rows = res["rows"]

    def fmt(sd, v):
        return f"{kv.g(v):,.3f}" if sd == "gold" else f"{v:,.2f}"

    def pct(v):
        return "—" if v is None else f"{v:,.1f}%"

    def grade(gr):
        return f'<span class="{_GRADE_CSS.get(gr, "")}">{_e(gr)}</span>'

    def srch(r):
        return _e(f'{r["name"]} {r.get("code") or ""}'.lower())

    keep = {"from": None if all_ else frm, "to": to,
            "all": "1" if all_ else None, "f": "1"}
    seg = "".join(
        f'<a class="{"on" if side == k else ""}" href="'
        f'{_e(_link(base, tab="customers", side=k, **keep))}">{t}</a>'
        for k, t in (("gold", "الذهب"), ("cash", "النقد"),
                     ("over", "نظرة عامة"), ("aging", "أعمار الديون")))
    tools = (
        f'<form class="tools" method="get" action="{_e(base)}">'
        '<input type="hidden" name="tab" value="customers">'
        f'<input type="hidden" name="side" value="{_e(side)}">'
        '<input type="hidden" name="f" value="1">'
        f'<label>من <input type="date" name="from" value="{_e(frm)}"></label>'
        f'<label>إلى <input type="date" name="to" value="{_e(to)}"></label>'
        f'<label><input type="checkbox" name="all" value="1"'
        f'{" checked" if all_ else ""}> منذ البداية</label>'
        '<button type="submit">عرض</button></form>')
    if side == "aging":
        return _aging(conn, query, base, to, keep, tools, seg)

    # اللوحات: كالشاشة — الذهب إلا في قسم النقد
    ps = "cash" if side == "cash" else "gold"
    tot = {k: sum(r[ps][k] for r in rows) for k in cb.KINDS}
    s = cb._side(tot, ps)
    u = _e(kv.unit()) if ps == "gold" else "ريال"
    active = sum(1 for r in rows if r["active"])
    owing = sum(1 for r in rows if r[ps]["remaining"] > 0.0005)
    summary = (
        f'<div>العملاء<b>{len(rows):,}</b>{active:,} بحركة</div>'
        f'<div>المبيعات<b>{fmt(ps, s["sales"])}</b>{u} · صافيها '
        f'{fmt(ps, s["net"])}</div>'
        f'<div class="out">المرتجع<b>{fmt(ps, s["returns"])}</b>{u} · '
        f'{pct(s["ret_pct"])}</div>'
        f'<div class="in">السداد<b>{fmt(ps, s["paid"])}</b>{u} · '
        f'{pct(s["paid_pct"])} من الصافي</div>'
        f'<div>الباقي<b>{fmt(ps, s["remaining"])}</b>{u} · على '
        f'{owing:,} عميلاً</div>')

    if side == "over":
        rows = cb.by_paid(rows, "gold")
        head = ["العميل", "الجوال", "عدد الفواتير", "آخر بيع", "آخر سداد",
                "منذ آخر سداد", "الباقي ذهباً", "تقدير الذهب",
                "الباقي نقداً", "تقدير النقد"]
        trs = []
        for r in rows:
            d = r["days_since_paid"]
            owes = (r["gold"]["remaining"] > 0.0005
                    or r["cash"]["remaining"] > 0.005)
            late = ' class="late"' if owes and (d is None or d > 60) else ""
            trs.append(
                f'<tr class="crow" data-s="{srch(r)}">'
                f'<td class="n">{_e(r["name"])}</td>'
                f'<td>{_e(r.get("phone") or "—")}</td>'
                f'<td>{r["n_sales"]:,}</td>'
                f'<td>{_e(r["last_sale"] or "—")}</td>'
                f'<td>{_e(r["last_paid"] or "—")}</td>'
                f'<td{late}>{"—" if d is None else f"{d:,} يوماً"}</td>'
                f'<td class="rem">{fmt("gold", r["gold"]["remaining"])}</td>'
                f'<td>{grade(r["gold"]["grade"])}</td>'
                f'<td class="rem">{fmt("cash", r["cash"]["remaining"])}</td>'
                f'<td>{grade(r["cash"]["grade"])}</td></tr>')
        foot = (
            f'<tr class="tot"><td class="n">الإجمالي ({len(rows)})</td><td></td>'
            f'<td>{sum(r["n_sales"] for r in rows):,}</td><td></td><td></td>'
            '<td></td>'
            f'<td>{fmt("gold", sum(r["gold"]["remaining"] for r in rows))}</td>'
            '<td></td>'
            f'<td>{fmt("cash", sum(r["cash"]["remaining"] for r in rows))}</td>'
            '<td></td></tr>')
    else:
        rows = cb.by_paid(rows, side)
        # «رصيد سابق» و«حركات أخرى» يُخفيان إن خلَوا — كالشاشة
        show_open = any(abs(r[side]["open"]) > 0.0005 for r in rows)
        show_other = any(abs(r[side]["other"]) > 0.0005 for r in rows)
        cols = [("العميل", None), ("رصيد سابق", "open"),
                ("المبيعات", "sales"), ("المرتجع", "returns"),
                ("صافي المبيعات", "net"), ("السداد", "paid"),
                ("حركات أخرى", "other"), ("الباقي", "remaining"),
                ("نسبة المرتجع", "ret_pct"), ("نسبة السداد", "paid_pct"),
                ("آخر سداد", "last"), ("التقدير", "grade")]
        cols = [c for c in cols
                if (c[1] != "open" or show_open)
                and (c[1] != "other" or show_other)]
        head = [c[0] for c in cols]

        def cell(r, key, x):
            if key is None:
                return f'<td class="n">{_e(r["name"])}</td>'
            if key in ("ret_pct", "paid_pct"):
                warn = (key == "ret_pct" and x[key] is not None
                        and x[key] >= 20)
                return f'<td{" class=late" if warn else ""}>{pct(x[key])}</td>'
            if key == "last":
                return f'<td>{_e(r["last_paid"] or "—")}</td>'
            if key == "grade":
                return f'<td>{grade(x["grade"])}</td>'
            if key == "remaining":
                cr = " cr" if x[key] < -0.0005 else ""
                return f'<td class="rem{cr}">{fmt(side, x[key])}</td>'
            return f'<td>{fmt(side, x[key])}</td>'
        trs = [f'<tr class="crow" data-s="{srch(r)}">'
               + "".join(cell(r, k, r[side]) for _t, k in cols) + "</tr>"
               for r in rows]
        t2 = cb._side({k: sum(r[side][k] for r in rows) for k in cb.KINDS},
                      side)

        def tcell(key):
            if key is None:
                return f'<td class="n">الإجمالي ({len(rows)})</td>'
            if key in ("ret_pct", "paid_pct"):
                return f"<td>{pct(t2[key])}</td>"
            if key in ("last", "grade"):
                return "<td></td>"
            return f"<td>{fmt(side, t2[key])}</td>"
        foot = ('<tr class="tot">' + "".join(tcell(k) for _t, k in cols)
                + "</tr>")
    if not rows:
        return ('<div class="empty">لا عملاء في هذه الفترة</div>', summary,
                tools, seg)
    body = ("<table><thead><tr>"
            + "".join(f"<th>{_e(h)}</th>" for h in head)
            + "</tr></thead><tbody>" + "".join(trs) + "</tbody><tfoot>"
            + foot + "</tfoot></table>")
    return body, summary, tools, seg


def _aging(conn, query, base, to, keep, tools, seg):
    """أعمار الديون كما في البرنامج (`models.aging`): رصيد كل عميلٍ
    موزَّعاً على فئاته العمرية حتى تاريخ «إلى» — الذهب أولاً ثم الأجور."""
    from models import aging
    from services import karat_view as kv
    dim = query.get("dim") if query.get("dim") in (
        "both", "gold", "cash") else "both"
    rows = aging.report(conn, "customer", to)
    t = aging.totals(rows)
    dims = "".join(
        f'<a class="{"on" if dim == k else ""}" href="'
        f'{_e(_link(base, tab="customers", side="aging", dim=k, **keep))}">'
        f'{x}</a>'
        for k, x in (("both", "نقد وذهب معاً"), ("gold", "الذهب فقط"),
                     ("cash", "النقد فقط")))
    tools = (tools.replace('name="side" value="aging">',
                           'name="side" value="aging">'
                           f'<input type="hidden" name="dim" value="{dim}">')
             + f'<nav class="seg">{dims}</nav>')
    labels = aging.BUCKET_LABELS
    late = t["cash_buckets"][1] + t["cash_buckets"][2]
    summary = (
        f'<div>عدد الجهات المدينة<b>{t["count"]:,}</b>لها رصيد قائم</div>'
        f'<div class="in">جارٍ (أقل من 30)<b>{t["cash_buckets"][0]:,.2f}</b>'
        f'أجور ريال · {t["cash_pct"][0]:.1f}%</div>'
        f'<div>متأخر (أقل من 90)<b>{late:,.2f}</b>أجور ريال · '
        f'{t["cash_pct"][1] + t["cash_pct"][2]:.1f}%</div>'
        f'<div class="out">متعثّر (أكثر من 90)<b>{t["cash_buckets"][3]:,.2f}'
        f'</b>أجور ريال · {t["cash_pct"][3]:.1f}%</div>'
        f'<div>إجمالي الذهب<b>{kv.g(t["gold"]):,.3f}</b>{_e(kv.unit())}</div>')
    if rows:
        w = rows[0]
        summary += (f'<div style="grid-column:1/-1">أقدم دين: '
                    f'<b style="display:inline;font-size:15px">{_e(w["name"])}'
                    f'</b> منذ {w["days"]:,} يوماً ({_e(w["oldest"])})</div>')
    both = dim == "both"
    head = ["العميل", "الجوال", "أحدث دين", "أقدم دين"]
    if dim in ("both", "gold"):
        head += [(f"ذهب {b}" if both else b) for b in labels] + [
            "إجمالي الذهب"]
    if dim in ("both", "cash"):
        head += [(f"أجور {b}" if both else b) for b in labels] + [
            "إجمالي الأجور"]
    head.append("له علينا")

    def g(x):
        return f"{kv.g(x):,.3f}" if x else ""

    def c(x):
        return f"{x:,.2f}" if x else ""

    trs = []
    for r in rows:
        nd, od = aging.ages(r, dim)
        cells = [f'<td class="n">{_e(r["name"])}</td>',
                 f'<td>{_e(r["phone"] or "—")}</td>',
                 f'<td>{"—" if nd is None else nd}</td>',
                 f'<td>{"—" if not od else od}</td>']
        if dim in ("both", "gold"):
            cells += [f"<td>{g(x)}</td>" for x in r["gold_buckets"]]
            cells.append(f'<td class="rem">{g(r["gold"])}</td>')
        if dim in ("both", "cash"):
            cells += [f"<td>{c(x)}</td>" for x in r["cash_buckets"]]
            cells.append(f'<td class="rem">{c(r["cash"])}</td>')
        cr = []
        if r["cash_credit"]:
            cr.append(f"نقد {abs(r['cash_credit']):,.2f}")
        if r["gold_credit"]:
            cr.append(f"ذهب {kv.g(abs(r['gold_credit'])):,.3f}")
        cells.append(f'<td class="cr">{" · ".join(cr) or "—"}</td>')
        # المتعثّر يُلوَّن كالشاشة: العين تلتقطه قبل الأرقام
        tone = (' style="color:#9A1414"' if r["days"] >= 91 else
                ' style="color:#5E4A0C"' if r["days"] >= 61 else "")
        s_ = _e(f'{r["name"]} {r.get("code") or ""}'.lower())
        trs.append(f'<tr class="crow" data-s="{s_}"{tone}>'
                   + "".join(cells) + "</tr>")
    if not rows:
        return ('<div class="empty">لا أرصدة قائمة على العملاء</div>',
                summary, tools, seg)
    tot = ['<td class="n">الإجمالي</td>', "<td>—</td>", "<td>—</td>",
           "<td>—</td>"]
    if dim in ("both", "gold"):
        tot += [f"<td>{kv.g(x):,.3f}</td>" for x in t["gold_buckets"]]
        tot.append(f"<td>{kv.g(t['gold']):,.3f}</td>")
    if dim in ("both", "cash"):
        tot += [f"<td>{x:,.2f}</td>" for x in t["cash_buckets"]]
        tot.append(f"<td>{t['cash']:,.2f}</td>")
    tot.append(f"<td>نقد {abs(t['cash_credit']):,.2f}</td>"
               if t["cash_credit"] else "<td>—</td>")
    body = ("<table><thead><tr>"
            + "".join(f"<th>{_e(h)}</th>" for h in head)
            + "</tr></thead><tbody>" + "".join(trs) + "</tbody><tfoot>"
            + '<tr class="tot">' + "".join(tot) + "</tr></tfoot></table>")
    return body, summary, tools, seg


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
                       '<th>رقم التشغيل</th><th>الوزن</th>'
                       '<th>مع من · التاريخ</th></tr>' + "".join(
                           f'<tr{_rk(i, True)}><td>{_e(i["wo"])}</td>'
                           f'<td class="n">{_w(i["reg"])}</td>'
                           f'<td>{_who(i["holder"], i["date"])}</td></tr>'
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
            f'{_photo(base, name, imgs.get(_vkey(name)))}'
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
            f'<td>{_who(i["holder"], i["date"], i["bulk"])}</td></tr>'
            for i in m["items"])
        cards.append(
            f'<article class="card" data-s="{_e(keys)}"'
            f' data-m="{_e(str(name).lower())}">'
            f'{_photo(base, name, imgs.get(_vkey(name)))}'
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
              f'<th>مع من الآن · الوارد</th></tr>{rows}</table>'
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


def _orders(conn, base, status, imgs):
    """طلبات العملاء (4.59): كل طلبٍ بعميله وتاريخه، وتحته صور موديلاته
    بالعدد المطلوب وما بالخزنة منه وما يلزم تصنيعه. وفي أعلاها «خلاصة
    التصنيع» للطلبات المفتوحة مجتمعةً. ومنذ 4.65: «➕ طلب جديد»، ولكل
    طلبٍ «🖨 عرض وطباعة» و«✏ تعديل» — كما في البرنامج."""
    from models import model_orders as mo
    rows = mo.list_orders(conn, status)
    arts = []
    tot_pieces = tot_short = 0
    for r in rows:
        o = mo.get_order(conn, r["id"])
        if not o:
            continue
        tot_pieces += o["pieces"]
        tot_short += o["short"] if o["status"] == "open" else 0
        keys = " ".join([o["order_no"], o["customer_name"]]
                        + [ln["model"] for ln in o["lines"]]).lower()
        cards = []
        for ln in o["lines"]:
            chips = [f'<span class="chip q">العدد {ln["qty"]}</span>']
            if o["status"] == "open":
                chips.append(f'<span class="chip in">بالخزنة'
                             f' {ln["in_count"]}</span>')
                if ln["short"]:
                    chips.append(f'<span class="chip short">للتصنيع'
                                 f' {ln["short"]}</span>')
            note = (f'<div class="onote">{_e(ln["note"])}</div>'
                    if ln.get("note") else "")
            cards.append(
                f'<div class="oc">'
                f'{_photo(base, ln["model"], imgs.get(_vkey(ln["model"])))}'
                f'<div class="b"><h2>{_e(ln["model"])}</h2>'
                f'<div class="chips">{"".join(chips)}</div>{note}</div></div>')
        due = (f'<span class="m">التسليم {_e(o["due_date"])}</span>'
               if o.get("due_date") else "")
        arts.append(
            f'<article class="order" data-s="{_e(keys)}">'
            f'<div class="oh"><a class="no" href="{_e(base)}/order/{o["id"]}">'
            f'{_e(o["order_no"])}</a>'
            f'<span class="cu">{_e(o["customer_name"])}</span>'
            f'<span class="m">{_e(o["order_date"])}</span>{due}'
            f'<span class="m">{o["models"]} موديل · {o["pieces"]} قطعة</span>'
            f'<span class="st {_e(o["status"])}">{_e(o["status_label"])}'
            f'</span><span class="acts"><a class="btn sm gold"'
            f' href="{_e(base)}/order/{o["id"]}">🖨 عرض وطباعة</a>'
            f'<a class="btn sm gh" href="{_e(base)}/order/{o["id"]}/edit">'
            f'✏ تعديل</a></span></div><div class="og">{"".join(cards)}</div>'
            + (f'<div class="onote">ملاحظات: {_e(o["notes"])}</div>'
               if o.get("notes") else "")
            + '</article>')
    prod = mo.production(conn) if status in ("open", "all") else []
    if prod:
        trs = "".join(
            f'<tr><td>{_e(p["model"])}</td><td class="n">{p["qty"]}</td>'
            f'<td class="n">{p["in_count"]}</td>'
            f'<td class="n">{"<b>%d</b>" % p["short"] if p["short"] else "✔"}'
            f'</td><td>{_e("، ".join(p["customers"]))}</td></tr>'
            for p in prod)
        arts.insert(0, (
            '<details class="prod"><summary>🏭 خلاصة التصنيع — ما تطلبه'
            ' الطلبات المفتوحة كلها مجتمعةً</summary><table><tr>'
            '<th>الموديل</th><th>المطلوب</th><th>بالخزنة</th>'
            '<th>للتصنيع</th><th>العملاء</th></tr>' + trs
            + '</table></details>'))
    label = {"open": "الطلبات المفتوحة", "done": "الطلبات المُسلَّمة",
             "all": "كل الطلبات"}[status]
    summary = (f'<div>{label}<b>{len(rows)}</b></div>'
               f'<div>القطع المطلوبة<b>{tot_pieces}</b></div>'
               + (f'<div class="out">يلزم تصنيعه<b>{tot_short} قطعة</b></div>'
                  if status != "done" else ""))
    body = "".join(arts) or '<div class="empty">لا طلبات</div>'
    tools = (f'<a class="btn" href="{_e(base)}/order/new">➕ طلب جديد</a>')
    return body, summary, tools


# ══════════════════════════════════════════════════════════════════
#  طلبات العملاء من الرابط (4.65): تسجيلٌ وتعديلٌ وطباعة
# ══════════════════════════════════════════════════════════════════

WEB_USER = "رابط المدير"             # اسم المستخدم في سجل التتبع
ORDER_PP = (2, 4, 6, 9, 12)          # الصور في صفحة الطباعة
_GRID = {2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 12: (3, 4)}


def _csrf(token, secret):
    """رمز التحقّق في كل نموذج — صفحةٌ من موقعٍ آخر لا تعرفه فلا تكتب."""
    return hmac.new(secret.encode("utf-8"), f"csrf|{token}".encode("utf-8"),
                    hashlib.sha256).hexdigest()[:32]


def _form_val(form, key, limit=200):
    return str((form.get(key) or [""])[-1]).strip()[:limit]


def _order_route(method, rest, query, body, base, csrf, no_pin):
    from database.database import db
    from models import model_orders as mo
    if method == "POST":
        form = parse_qs((body or b"").decode("utf-8", "replace"),
                        keep_blank_values=True)
        if not hmac.compare_digest(_form_val(form, "csrf", 64), csrf):
            return _resp(403, _note_page(
                base, "انتهت صلاحية الصفحة — افتحها من جديد ثم أعد"
                      " المحاولة."))
        if rest == ["save"]:
            return _order_save(form, base, csrf, no_pin)
        if len(rest) == 2 and rest[0].isdigit() and rest[1] == "status":
            st = _form_val(form, "st", 20)
            try:
                with db() as conn:
                    mo.set_status(conn, int(rest[0]), st, WEB_USER)
            except ValueError as e:
                return _resp(400, _note_page(base, str(e)))
            return _resp(303, "", headers={
                "Location": f"{base}/order/{rest[0]}"})
        return _resp(404, _GONE)
    if method != "GET":
        return _resp(405, _GONE)
    with db(readonly=True) as conn:
        if rest == ["new"]:
            return _resp(200, order_form(conn, base, None, csrf, no_pin))
        if len(rest) == 2 and rest[0].isdigit() and rest[1] == "edit":
            o = mo.get_order(conn, int(rest[0]))
            if not o:
                return _resp(404, _note_page(base, "الطلب غير موجود"))
            return _resp(200, order_form(conn, base, o, csrf, no_pin))
        if len(rest) == 1 and rest[0].isdigit():
            o = mo.get_order(conn, int(rest[0]))
            if not o:
                return _resp(404, _note_page(base, "الطلب غير موجود"))
            return _resp(200, order_page(base, o, query, csrf))
    return _resp(404, _GONE)


def _customers(conn):
    """{الاسم: المعرّف} — كل جهات التعامل كما في البرنامج عدا الداخلية."""
    try:
        from models import entities
        return {r["name"]: r["id"] for r in entities.list_customers(conn)
                if r["entity_type"] != "internal"}
    except Exception:
        return {}


def _order_save(form, base, csrf, no_pin):
    from datetime import date

    from database.database import db
    from models import model_orders as mo
    oid = _form_val(form, "id", 12)
    oid = int(oid) if oid.isdigit() else None
    name = _form_val(form, "customer", 120)
    d1 = _form_val(form, "date", 10)
    d1 = d1 if _DATE.match(d1) else date.today().isoformat()
    due = _form_val(form, "due", 10)
    due = due if _DATE.match(due) else None
    notes = _form_val(form, "notes", 500)
    ms, qs, ns = form.get("m", []), form.get("q", []), form.get("n", [])
    lines = []
    for i, m in enumerate(ms[:3000]):
        try:
            q = int((qs[i] if i < len(qs) else "0") or 0)
        except ValueError:
            q = 0
        q = max(0, min(q, 9999))
        if q:
            lines.append({"model": str(m).strip()[:80], "qty": q,
                          "note": str(ns[i] if i < len(ns) else "")
                          .strip()[:200]})
    try:
        with db() as conn:
            known = {c["model"] for c in mo.catalog(conn)}
            if oid:
                old = mo.get_order(conn, oid)
                known |= {ln["model"] for ln in (old or {}).get("lines", [])}
            lines = [ln for ln in lines if ln["model"] in known]
            res = mo.save_order(conn, name, lines, WEB_USER, order_id=oid,
                                entity_id=_customers(conn).get(name),
                                order_date=d1, due_date=due, notes=notes)
    except ValueError as e:
        draft = {"id": oid, "customer_name": name, "order_date": d1,
                 "due_date": due, "notes": notes, "lines": lines,
                 "order_no": ""}
        with db(readonly=True) as conn:
            return _resp(400, order_form(conn, base, draft, csrf, no_pin,
                                         error=str(e)))
    loc = f"{base}/order/{res['id']}?saved=1"
    if _form_val(form, "go", 10) == "print":
        loc += "&print=1"
    return _resp(303, "", headers={"Location": loc})


_ORDER_CSS = """
.btn{display:inline-block;padding:8px 16px;border-radius:9px;border:0;
background:var(--brown);color:#fff;text-decoration:none;font-weight:600;
font-size:14px;cursor:pointer;white-space:nowrap}
.btn.gold{background:var(--gold)}
.btn.gh{background:#fff;color:var(--brown);border:1px solid var(--line)}
.btn.sm{padding:5px 11px;font-size:12.5px}
.acts{display:flex;gap:6px;flex-wrap:wrap;margin-inline-start:auto}
.ofh{display:grid;grid-template-columns:2fr 1fr 1fr 3fr;gap:10px 14px;
background:#fff;border:1px solid var(--line);border-radius:14px;
padding:12px 14px;margin:0 0 12px}
.ofh label{display:flex;flex-direction:column;gap:4px;font-size:12.5px;
color:var(--muted)}
.ofh input{padding:9px 10px;border:1px solid var(--line);border-radius:9px;
font-size:15px;color:var(--ink)}
.selbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;
gap:10px;flex-wrap:wrap;background:#fffaf0;border:1px solid #e9d9b5;
border-radius:12px;padding:9px 12px;margin:0 0 12px}
.selbar b{color:var(--brown);font-size:15px}
.selbar .chips2{flex:1 1 300px;color:var(--muted);font-size:12.5px}
.selbar input[type=search]{padding:7px 10px;border:1px solid var(--line);
border-radius:8px;width:260px}
.pk .ph{cursor:pointer}
.pk.sel{border-color:var(--gold);box-shadow:0 0 0 2px var(--gold)}
.qty{display:flex;align-items:center;gap:6px;margin:7px 0 5px}
.qty button{width:34px;height:34px;border-radius:9px;border:1px solid
var(--line);background:#fff;font-size:18px;font-weight:700;cursor:pointer;
color:var(--brown)}
.qty input{width:64px;height:34px;text-align:center;font-size:17px;
font-weight:700;border:1px solid var(--line);border-radius:9px}
.pk input.nt{width:100%;padding:5px 7px;border:1px solid var(--line);
border-radius:7px;font-size:12px}
.err{background:#fbeaea;color:#a4262c;border-radius:10px;padding:10px 14px;
margin:0 0 12px;font-weight:600}
.ok{background:#e8f3ea;color:var(--in);border-radius:10px;padding:10px 14px;
margin:0 0 12px;font-weight:600}
.warn{color:var(--out);font-size:12.5px;margin:0 0 10px}
.oh a.no{text-decoration:none}
"""

_FORM_JS = """
(function(){
 var f=document.getElementById('of'),q=document.getElementById('pq'),
  only=document.getElementById('only'),tot=document.getElementById('tot'),
  chips=document.getElementById('chips');
 var cards=[].slice.call(document.querySelectorAll('.pk'));
 function inp(c){return c.querySelector('input[name=q]');}
 function val(c){var v=parseInt(inp(c).value,10);return isNaN(v)||v<0?0:v;}
 function filt(){var s=(q.value||'').trim().toLowerCase(),o=only.checked;
  cards.forEach(function(c){var hit=(!s||c.getAttribute('data-m')
   .indexOf(s)>=0)&&(!o||val(c)>0);c.style.display=hit?'':'none';});}
 function upd(){var n=0,p=0,h=[];cards.forEach(function(c){var v=val(c);
  c.classList.toggle('sel',v>0);if(v>0){n++;p+=v;
  h.push(c.getAttribute('data-n')+' × '+v);}});
  tot.textContent=n+' موديل · '+p+' قطعة';
  chips.textContent=h.join('   ·   ')||'لم يُختر موديلٌ بعد — اضغط صورته أو +';
  filt();}
 cards.forEach(function(c){var i=inp(c);
  c.querySelector('.plus').addEventListener('click',function(){
   i.value=val(c)+1;upd();});
  c.querySelector('.minus').addEventListener('click',function(){
   i.value=Math.max(0,val(c)-1);upd();});
  c.querySelector('.ph').addEventListener('click',function(){
   if(!val(c)){i.value=1;upd();}});
  i.addEventListener('input',upd);});
 q.addEventListener('input',filt);only.addEventListener('change',filt);
 f.addEventListener('submit',function(e){var any=false;
  cards.forEach(function(c){var z=!val(c);if(!z)any=true;
   c.querySelectorAll('input').forEach(function(x){x.disabled=z;});});
  if(!any){e.preventDefault();cards.forEach(function(c){
   c.querySelectorAll('input').forEach(function(x){x.disabled=false;});});
   alert('اختر موديلاً واحداً على الأقل بعددٍ أكبر من صفر');}});
 upd();
})();
"""


def _shell(base, title, inner, css="", js="", back=True):
    """صفحةٌ بتصميم الرابط نفسه — للطلب وطباعته."""
    co = _company().strip()
    head = (f'<a class="btn gh sm" href="{_e(_link(base, tab="orders"))}">'
            '← الطلبات</a>' if back else "")
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar" data-base="{_e(base)}"><head><meta charset="utf-8">
<meta name="viewport" content="width={DESKTOP_W}">
<meta name="robots" content="noindex,nofollow">
<title>{_e(title)}</title>
<style>{_CSS}{_ORDER_CSS}{css}</style></head><body>
<header><div class="hi"><div class="t"><h1>{_e(title)}</h1>
<div class="sub">{_e(co) + " · " if co else ""}دليل الموديلات — من جهاز
 المصنع مباشرةً</div></div><div class="bar">{head}</div></div></header>
<main>{inner}</main>
<footer>إصدار {_e(_version())}</footer>
<script>{js}{_IMG_JS}</script></body></html>"""


def _note_page(base, text):
    return _shell(base, "طلبات العملاء",
                  f'<div class="err">{_e(text)}</div>')


def order_form(conn, base, order, csrf, no_pin, error=""):
    """نموذج الطلب: العميل والتاريخ، وكل الموديلات بصورها وخانة عددٍ
    تحت كل صورة (+ و−)، والبحث برقم الموديل، و«المختار فقط»."""
    from datetime import date

    from models import model_orders as mo
    order = order or {}
    picked = {ln["model"]: ln for ln in order.get("lines", [])}
    cat = mo.catalog(conn)
    names = [c["model"] for c in cat]
    extra = [m for m in picked if m not in set(names)]
    stock = {c["model"]: c for c in cat}
    imgs = _img_versions()
    cards = []
    for m in extra + names:
        ln = picked.get(m, {})
        q = int(ln.get("qty") or 0)
        c = stock.get(m, {})
        sn = _vkey(m)
        ver = imgs.get(sn)
        ph = (f'<div class="ph"><img loading="lazy"'
              f' src="{_e(_img_url(base, m, ver))}" alt="{_e(m)}"'
              f' data-s="{_e(sn)}" data-v="{_e(ver)}"></div>' if ver
              else '<div class="ph noimg">لا توجد صورة</div>')
        cards.append(
            f'<article class="card pk{" sel" if q else ""}"'
            f' data-m="{_e(str(m).lower())}" data-n="{_e(m)}">{ph}'
            f'<div class="b"><h2>{_e(m)}</h2><div class="chips">'
            f'<span class="chip in">بالخزنة {int(c.get("in_count") or 0)}'
            f'</span></div>'
            f'<input type="hidden" name="m" value="{_e(m)}">'
            f'<div class="qty"><button type="button" class="minus"'
            f' aria-label="أقل">−</button><input name="q" type="number"'
            f' min="0" max="9999" inputmode="numeric" value="{q}">'
            f'<button type="button" class="plus" aria-label="أكثر">+'
            f'</button></div><input class="nt" name="n" maxlength="200"'
            f' placeholder="ملاحظة على الموديل (اختياري)"'
            f' value="{_e(ln.get("note") or "")}"></div></article>')
    custs = "".join(f'<option value="{_e(n)}">'
                    for n in sorted(_customers(conn)))
    oid = order.get("id")
    title = (f"تعديل الطلب {order.get('order_no')}" if oid
             and order.get("order_no") else "طلب عميل جديد")
    d1 = order.get("order_date") or date.today().isoformat()
    warn = ('<div class="warn">🔒 الرابط صار يسجّل طلبات — يُنصح بتفعيل'
            ' «رمز الدخول» من شاشة «رابط المدير» في البرنامج.</div>'
            if no_pin else "")
    inner = (
        (f'<div class="err">⚠ {_e(error)}</div>' if error else "")
        + f'<form id="of" method="post" action="{_e(base)}/order/save">'
        f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
        f'<input type="hidden" name="id" value="{_e(oid or "")}">'
        f'<div class="ofh">'
        f'<label>اسم العميل<input name="customer" list="custs" required'
        f' maxlength="120" autocomplete="off"'
        f' value="{_e(order.get("customer_name") or "")}"></label>'
        f'<label>تاريخ الطلب<input type="date" name="date"'
        f' value="{_e(d1)}"></label>'
        f'<label>موعد التسليم (اختياري)<input type="date" name="due"'
        f' value="{_e(order.get("due_date") or "")}"></label>'
        f'<label>ملاحظات الطلب<input name="notes" maxlength="500"'
        f' value="{_e(order.get("notes") or "")}"></label></div>'
        f'<datalist id="custs">{custs}</datalist>{warn}'
        f'<div class="selbar"><b id="tot"></b><span id="chips"'
        f' class="chips2"></span><input id="pq" type="search"'
        f' placeholder="ابحث برقم الموديل…"><label><input id="only"'
        f' type="checkbox"> المختار فقط</label>'
        f'<button class="btn" name="go" value="save">💾 حفظ الطلب</button>'
        f'<button class="btn gold" name="go" value="print">💾 حفظ وطباعة'
        f'</button></div>'
        f'<section class="grid">{"".join(cards)}</section></form>')
    return _shell(base, title, inner, js=_FORM_JS)


_PRINT_CSS = """
@page{size:A4;margin:8mm}
.sheet{display:flex;flex-direction:column;align-items:center;gap:14px}
.pg{width:194mm;height:279mm;background:#fff;display:flex;
flex-direction:column;box-sizing:content-box;padding:8mm;
box-shadow:0 2px 10px rgba(0,0,0,.12);overflow:hidden}
.pgh{display:flex;align-items:baseline;gap:5mm;flex-wrap:wrap;
border-bottom:.5mm solid #B99B33;padding:0 0 2mm;margin:0 0 3mm;
font-size:11pt;color:#4A3A1E}
.pgh .cu{font-size:13pt;font-weight:700}
.pgh .no{font-weight:700}
.pgh .pn{margin-inline-start:auto;color:#776b5e;font-size:9pt}
.info{font-size:10.5pt;color:#4A3A1E;margin:0 0 3mm}
.cells{flex:1;min-height:0;display:grid;gap:3mm}
.cell{display:flex;flex-direction:column;min-height:0;border:.3mm solid
#e7dfd1;border-radius:2.5mm;padding:2mm;overflow:hidden}
.cell .im{flex:1;min-height:0;display:flex;align-items:center;
justify-content:center}
.cell img{max-width:100%;max-height:100%;object-fit:contain}
.cell .ni{color:#9a8f7c;font-size:10pt}
.cap{text-align:center;color:#4A3A1E;padding-top:1.5mm;line-height:1.35}
.cap .mn{font-size:13pt;font-weight:700}
.cap .q{font-size:15pt;font-weight:800;color:#8a6d1d}
.cap .s,.cap .t{display:block;font-size:9.5pt;color:#5a5040}
.ws table{width:100%;font-size:11pt}
.ws th,.ws td{border:.3mm solid #e7dfd1;padding:1.5mm;text-align:center}
.tb{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
background:#fff;border:1px solid var(--line);border-radius:14px;
padding:10px 12px;margin:0 0 14px}
.tb form{display:inline;margin:0}
.tb select{padding:6px 8px;border:1px solid var(--line);border-radius:8px}
.st2{padding:3px 10px;border-radius:11px;font-weight:700;font-size:13px}
@media print{
 header,footer,.tb,.ok{display:none!important}
 body{background:#fff;min-width:0}
 main{padding:0;max-width:none}
 .sheet{gap:0;display:block}
 .pg{box-shadow:none;padding:0;page-break-after:always;break-after:page}
 .pg:last-child{page-break-after:auto;break-after:auto}
}
"""


def order_page(base, o, query, csrf):
    """الطلب كما يُطبع: صفحات A4 في رأس كلٍّ منها العميل ورقم الطلب، وتحت
    كل صورةٍ الموديل والعدد بخطٍّ بارز — وفوقها شريطٌ للطباعة والتعديل
    والحالة لا يظهر في الورقة."""
    try:
        pp = int(query.get("pp") or 4)
    except ValueError:
        pp = 4
    pp = pp if pp in _GRID else 4
    ws = query.get("stock") == "1"
    cols, rows = _GRID[pp]
    oid = o["id"]
    vers = _img_versions()
    cells = []
    for ln in o["lines"]:
        sn = _vkey(ln["model"])
        ver = vers.get(sn)
        im = (f'<img src="{_e(_img_url(base, ln["model"], ver, True))}"'
              f' alt="{_e(ln["model"])}" data-s="{_e(sn)}"'
              f' data-v="{_e(ver)}">' if ver
              else '<span class="ni">لا صورة لهذا الموديل</span>')
        extra = ""
        if ws:
            extra = (f'<span class="s">بالخزنة {ln["in_count"]}'
                     + (f' · للتصنيع <b>{ln["short"]}</b>' if ln["short"]
                        else " · متوفّر ✔") + "</span>")
        if ln.get("note"):
            extra += f'<span class="t">{_e(ln["note"])}</span>'
        cells.append(
            f'<div class="cell"><div class="im">{im}</div><div class="cap">'
            f'<span class="mn">{_e(ln["model"])}</span> &nbsp;—&nbsp;'
            f' العدد: <span class="q">{ln["qty"]}</span>{extra}</div></div>')
    pages_n = max(1, (len(cells) + pp - 1) // pp)
    head = (f'<span class="no">طلب {_e(o["order_no"])}</span>'
            f'<span>العميل: <span class="cu">{_e(o["customer_name"])}'
            f'</span></span><span>{_e(o["order_date"])}</span>')
    info = (f'<div class="info">{o["models"]} موديل · <b>{o["pieces"]}</b>'
            ' قطعة'
            + (f' &nbsp;·&nbsp; موعد التسليم: <b>{_e(o["due_date"])}</b>'
               if o.get("due_date") else "")
            + (f'<br>ملاحظات: {_e(o["notes"])}' if o.get("notes") else "")
            + "</div>")
    grid = (f'grid-template-columns:repeat({cols},minmax(0,1fr));'
            f'grid-template-rows:repeat({rows},minmax(0,1fr))')
    pages = []
    for i in range(pages_n):
        chunk = cells[i * pp:(i + 1) * pp]
        pages.append(
            f'<section class="pg"><div class="pgh">{head}<span class="pn">'
            f'صفحة {i + 1} من {pages_n}</span></div>'
            + (info if i == 0 else "")
            + f'<div class="cells" style="{grid}">{"".join(chunk)}</div>'
            '</section>')
    if ws:
        trs = "".join(
            f'<tr><td>{_e(ln["model"])}</td><td>{ln["qty"]}</td>'
            f'<td>{ln["in_count"]}</td>'
            f'<td>{ln["short"] if ln["short"] else "✔"}</td>'
            f'<td>{_e(ln.get("note") or "")}</td></tr>' for ln in o["lines"])
        pages.append(
            f'<section class="pg ws"><div class="pgh">{head}<span class="pn">'
            'خلاصة الطلب للورشة</span></div><table><tr><th>الموديل</th>'
            '<th>العدد</th><th>بالخزنة</th><th>للتصنيع</th><th>ملاحظة</th>'
            f'</tr>{trs}<tr><th>الإجمالي</th><th>{o["pieces"]}</th><th></th>'
            f'<th>{o["short"]}</th><th></th></tr></table></section>')

    def _st(st, label, cls="gh"):
        return (f'<form method="post" action="{_e(base)}/order/{oid}/status">'
                f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
                f'<input type="hidden" name="st" value="{st}">'
                f'<button class="btn sm {cls}">{label}</button></form>')
    states = []
    if o["status"] != "done":
        states.append(_st("done", "✔ تم التسليم"))
    if o["status"] != "open":
        states.append(_st("open", "↺ إعادة فتح"))
    if o["status"] != "cancelled":
        states.append(_st("cancelled", "✖ إلغاء الطلب"))
    pp_opts = "".join(f'<option value="{n}"{" selected" if n == pp else ""}>'
                      f'{n} صور في الصفحة</option>' for n in ORDER_PP)
    tb = (
        f'<div class="tb"><button class="btn gold" type="button"'
        f' onclick="window.print()">🖨 طباعة</button>'
        f'<a class="btn" href="{_e(base)}/order/{oid}/edit">✏ تعديل</a>'
        f'<form method="get" action="{_e(base)}/order/{oid}">'
        f'<select name="pp" onchange="this.form.submit()">{pp_opts}</select>'
        f' <label><input type="checkbox" name="stock" value="1"'
        f'{" checked" if ws else ""} onchange="this.form.submit()">'
        f' ورقة الورشة (بالخزنة وللتصنيع)</label></form>'
        f'<span class="st2 st {_e(o["status"])}">{_e(o["status_label"])}'
        f'</span><span class="acts">{"".join(states)}'
        f'<a class="btn gh sm" href="{_e(base)}/order/new">➕ طلب جديد</a>'
        '</span></div>')
    ok = ('<div class="ok">✔ حُفظ الطلب — وهو الآن في البرنامج على جهاز'
          ' المصنع وفي هذا الرابط معاً.</div>'
          if query.get("saved") == "1" else "")
    js = ("window.addEventListener('load',function(){setTimeout(function()"
          "{window.print();},300);});" if query.get("print") == "1" else "")
    return _shell(base, f"طلب {o['order_no']} — {o['customer_name']}",
                  ok + tb + f'<div class="sheet">{"".join(pages)}</div>',
                  css=_PRINT_CSS, js=js)


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
