# -*- coding: utf-8 -*-
"""رابط المدير يعمل دائماً (5.8.5) — ولو انطفأت الشاشة أو غاب المستخدم.

الرابط يُعرض من هذا الجهاز نفسه (`photo_server` + Tailscale)، فما يوقفه
أربعة أشياء — ولكلٍّ علاجه هنا، وكلها تلقائية ما دام الرابط مفعّلاً
وخيار «الرابط يعمل دائماً» مختاراً (الافتراضي):

1. **نوم الجهاز من الخمول**: طلبُ «النظام مطلوب» من ويندوز
   (`SetThreadExecutionState`) — كما تفعل برامج البثّ والخوادم: الشاشة
   تنطفئ كالمعتاد وتُقفل، والجهاز يبقى يعمل ومتصلاً. يُرفع الطلب فور
   إيقاف الرابط أو الخيار. وإغلاقُ غطاء الحاسب المحمول وهو على الكهرباء
   لا يُنيمه (يُعاد إعداده السابق عند الإيقاف).
2. **نومٌ أو انقطاعٌ حدث فعلاً** (زرّ السكون، أو بطارية): حارسٌ يلاحظ
   القفزة في الوقت عند الاستيقاظ أو توقّف الخادم — فيعيد تشغيل الرابط
   وتوجيه Tailscale بلا لمسة.
3. **إغلاق نافذة البرنامج**: تُخفى النافذة إلى جوار الساعة (أيقونة البرنامج)
   ويبقى الرابط يعمل — والخروج النهائي من قائمة الأيقونة.
4. **إعادة تشغيل الجهاز** (تحديثات ويندوز): البرنامج يبدأ مع ويندوز،
   والرابط يعمل من شاشة الدخول نفسها قبل أن يدخل أحد.

خارج ويندوز (الفحص) كل ما يخصّ النظام لا يفعل شيئاً.
"""
import json
import os
import sys
import threading
import time

K_ALWAYS = "link_always_on"            # "0" = المستخدم أوقف الخيار
K_LID_PREV = "link_lid_prev"           # إعداد الغطاء قبل أن يغيّره البرنامج
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "GoldERP_ManagerLink"
CHECK_EVERY = 30                       # ثانية بين كل فحص
WAKE_GAP = 120                         # قفزة وقتٍ أطول من هذا = استيقظ الجهاز

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040

_STATE = {"thread": None, "awake": False, "stop": None, "poke": None,
          "last": 0.0, "restarts": 0, "lid": False}
_LOCK = threading.Lock()


def is_windows():
    return sys.platform.startswith("win")


# ══════════════════════════ الإعدادات ══════════════════════════
def _get(key, default=""):
    try:
        from database.database import db
        from models.fiscal import get_setting
        with db(readonly=True) as conn:
            return get_setting(conn, key, default)
    except Exception:                                  # noqa: BLE001
        return default


def _set(key, value, username="system"):
    try:
        from database.database import db
        from models.fiscal import set_setting
        with db() as conn:
            set_setting(conn, key, value, username)
        return True
    except Exception:                                  # noqa: BLE001
        return False


def link_on():
    """هل رابط المدير مفعّل؟"""
    try:
        from services import models_web as mw
        return _get(mw.K_ENABLED, "0") == "1"
    except Exception:                                  # noqa: BLE001
        return False


def always_on():
    """خيار «الرابط يعمل دائماً» (مختارٌ افتراضاً)."""
    return str(_get(K_ALWAYS, "1") or "1") != "0"


def active():
    """الرابط مفعّل والخيار مختار — فيعمل كل ما في هذا الملف."""
    return link_on() and always_on()


def set_always_on(on, username=None):
    _set(K_ALWAYS, "1" if on else "0", username or "system")
    apply_now()


# ══════════════════════════ 1) لا نوم من الخمول ══════════════════════════
def _execution_state(flags):
    """`SetThreadExecutionState` — يعيد True إن قبله ويندوز."""
    if not is_windows():
        return False
    try:
        import ctypes
        fn = ctypes.windll.kernel32.SetThreadExecutionState
        fn.restype = ctypes.c_uint
        return bool(fn(ctypes.c_uint(flags)))
    except Exception:                                  # noqa: BLE001
        return False


def _hold_awake(on):
    """يُنادى من خيط الحارس نفسه (الطلب يخصّ الخيط الذي طلبه)."""
    if on:
        # «وضع الغياب» حيث يسمح به ويندوز: زرّ السكون يطفئ الشاشة والصوت
        # ويبقي الجهاز يعمل — وإلا فطلب «النظام مطلوب» وحده
        ok = _execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                              | ES_AWAYMODE_REQUIRED) or \
            _execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        _STATE["awake"] = ok
    elif _STATE["awake"]:
        _execution_state(ES_CONTINUOUS)
        _STATE["awake"] = False


# غطاء الحاسب المحمول على الكهرباء: «لا شيء» بدل «سكون» ما دام الرابط يعمل
def _powercfg(args, timeout=15):
    import subprocess
    kw = {}
    if is_windows():
        kw["creationflags"] = 0x08000000            # بلا نافذة سوداء
    r = subprocess.run(["powercfg"] + list(args), capture_output=True,
                       timeout=timeout, **kw)
    out = (r.stdout or b"").decode("utf-8", "replace")
    return r.returncode, out


def _lid_ac():
    """إعداد الغطاء الحالي على الكهرباء (0 لا شيء · 1 سكون · 2 إسبات ·
    3 إيقاف) — من آخر قيمتين ست عشريتين في الناتج (الكهرباء ثم البطارية)
    فلا تهمّ لغة ويندوز."""
    import re
    code, out = _powercfg(["/query", "SCHEME_CURRENT", "SUB_BUTTONS",
                           "LIDACTION"])
    vals = re.findall(r"0x([0-9a-fA-F]{8})", out)
    if code != 0 or len(vals) < 2:
        return None
    return int(vals[-2], 16)


def _set_lid_ac(value):
    code, _o = _powercfg(["/setacvalueindex", "SCHEME_CURRENT",
                          "SUB_BUTTONS", "LIDACTION", str(int(value))])
    if code == 0:
        _powercfg(["/setactive", "SCHEME_CURRENT"])
    return code == 0


def _hold_lid(on):
    if not is_windows():
        return
    try:
        if on and not _STATE["lid"]:
            cur = _lid_ac()
            if cur is None:
                return
            if cur != 0:
                prev = _get(K_LID_PREV, "")
                if not prev:
                    _set(K_LID_PREV, json.dumps({"ac": cur}))
                _set_lid_ac(0)
            _STATE["lid"] = True
        elif not on:
            prev = _get(K_LID_PREV, "")
            if prev:
                try:
                    _set_lid_ac(int(json.loads(prev).get("ac", 1)))
                finally:
                    _set(K_LID_PREV, "")
            _STATE["lid"] = False
    except Exception:                                  # noqa: BLE001
        pass


# ══════════════════════════ 4) البدء مع ويندوز ══════════════════════════
def _exe_command():
    """أمر تشغيل البرنامج — نسخة exe وحدها (لا نسخة المطوّر)."""
    if not getattr(sys, "frozen", False):
        return ""
    return f'"{os.path.abspath(sys.executable)}"'


def autostart_registered():
    if not is_windows():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _t = winreg.QueryValueEx(k, RUN_NAME)
            return bool(v)
    except Exception:                                  # noqa: BLE001
        return False


def set_autostart(on):
    """يسجّل البرنامج (أو يلغيه) في «بدء التشغيل» للمستخدم الحالي — بلا
    صلاحيات مدير."""
    if not is_windows():
        return False
    try:
        import winreg
        cmd = _exe_command()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if on and cmd:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, cmd)
            elif not on:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:                                  # noqa: BLE001
        return False


# ══════════════════════════ 2) الحارس ══════════════════════════
def _restart_link(why=""):
    """يعيد تشغيل الخادم وتوجيه Tailscale — في خيطٍ منفصل (قد يطول)."""
    if _STATE.get("restarting"):
        return False                     # إعادةٌ جارية — لا تتراكم

    def work():
        try:
            from services import models_web
            models_web.autostart(tries=6, wait=20)
        except Exception:                              # noqa: BLE001
            pass
        finally:
            _STATE["restarting"] = False
    _STATE["restarting"] = True
    _STATE["restarts"] += 1
    threading.Thread(target=work, daemon=True,
                     name=f"link-restart-{why or 'x'}").start()
    return True


def _server_alive():
    try:
        from services import photo_server
        return photo_server.current() is not None
    except Exception:                                  # noqa: BLE001
        return True


def tick(now=None):
    """فحصٌ واحد — يُنادى كل `CHECK_EVERY` ثانية من خيط الحارس.

    يعيد ما فعله (للفحص): awake/released/wake/server."""
    now = time.time() if now is None else now
    did = []
    on = active()
    if on and not _STATE["awake"]:
        _hold_awake(True)
        did.append("awake")
    elif not on and _STATE["awake"]:
        _hold_awake(False)
        did.append("released")
    elif on:
        _hold_awake(True)                # يُجدَّد الطلب (لا يضرّ تكراره)
    _hold_lid(on)
    last = _STATE["last"]
    _STATE["last"] = now
    if link_on():
        if last and now - last > WAKE_GAP:
            did.append("wake")           # استيقظ الجهاز — يعود الرابط
            _restart_link("wake")
        elif not _server_alive():
            did.append("server")
            _restart_link("server")
    return did


def _loop(stop, poke):
    # طلب «النظام مطلوب» يخصّ الخيط الذي طلبه — فكل فحصٍ في هذا الخيط
    # وحده؛ ومن خارجه «نكزة» (`apply_now`) توقظه ليفحص الآن
    try:
        _STATE["last"] = time.time()
        if link_on():
            _restart_link("start")           # الرابط يعود مع البرنامج
    except Exception:                                  # noqa: BLE001
        pass
    while not stop.is_set():
        try:
            tick()
        except Exception:                              # noqa: BLE001
            pass
        poke.wait(CHECK_EVERY)
        poke.clear()
    _hold_awake(False)


def start():
    """يبدأ الحارس مرةً واحدة (من الإقلاع، قبل الدخول) — ويُعيد True إن
    بدأ الآن."""
    with _LOCK:
        t = _STATE["thread"]
        if t is not None and t.is_alive():
            return False
        stop, poke = threading.Event(), threading.Event()
        _STATE["stop"], _STATE["poke"] = stop, poke
        t = threading.Thread(target=_loop, args=(stop, poke), daemon=True,
                             name="link-keeper")
        _STATE["thread"] = t
        t.start()
    try:
        sync_autostart()
    except Exception:                                  # noqa: BLE001
        pass
    return True


def started():
    t = _STATE["thread"]
    return t is not None and t.is_alive()


def stop():
    with _LOCK:
        ev, poke = _STATE["stop"], _STATE["poke"]
        if ev is not None:
            ev.set()
        if poke is not None:
            poke.set()


def sync_autostart():
    """البدء مع ويندوز يتبع الرابط والخيار معاً."""
    want = active()
    if want != autostart_registered():
        set_autostart(want)


def apply_now():
    """بعد تفعيل الرابط أو إيقافه أو تغيير الخيار: يُطبَّق كل شيء الآن."""
    if not started():
        start()
    elif _STATE["poke"] is not None:
        _STATE["poke"].set()             # الحارس يفحص الآن في خيطه
    try:
        sync_autostart()
    except Exception:                                  # noqa: BLE001
        pass


def status_text():
    """سطرٌ لنافذة الرابط يقول ما يُفعل الآن."""
    if not link_on():
        return "الرابط موقوف"
    if not always_on():
        return "الرابط يعمل والبرنامج مفتوح فقط (الخيار موقوف)"
    bits = ["الجهاز لا ينام ما دام الرابط مفعّلاً (الشاشة تنطفئ عادياً)",
            "إغلاق النافذة يبقي البرنامج يعمل بجوار الساعة"]
    if getattr(sys, "frozen", False):
        bits.append("البرنامج يبدأ مع ويندوز والرابط يعمل قبل الدخول")
    return " · ".join(bits)
