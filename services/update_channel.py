# -*- coding: utf-8 -*-
"""قناة التحديث عبر الإنترنت.

**الغرض**: العميل في أي بلد يفتح النظام فيرى إشعاراً بوجود تحديث،
ينقر فيُحمَّل ويُثبَّت تلقائياً — بلا إرسال ملفات ولا خطوات يدوية.

**كيف تعمل**: يُنشر ملف بيان صغير (`latest.json`) في مساحة التخزين
السحابية، يحمل رقم الإصدار ورابط الحزمة وبصمتها. النظام يقرأ البيان
في الخلفية عند الإقلاع، فإن كان الإصدار المنشور أحدث ظهر الإشعار.

**الضمانات الأمنية** — تحميل كود من الإنترنت وتشغيله خطر بطبعه:

1. **HTTPS إلزامي**: أي رابط غير مشفّر يُرفض قبل الاتصال.
2. **النطاق مُقيَّد**: التحميل من نطاق السحابة المعتمد فقط، فلا
   يُمكن لبيان مُخترَق توجيه النظام لخادم غريب.
3. **بصمة SHA-256 إلزامية**: البيان يحمل بصمة الحزمة، وتُطابَق بعد
   التحميل. أي اختلاف يعني ملفاً تالفاً أو معدَّلاً — يُحذف فوراً.
4. **حدّ للحجم**: تحميل يتجاوز الحدّ يُقطع، فلا يُستنزف القرص.
5. **الفحص قبل التثبيت**: الحزمة تمرّ على `updater` بكل ضماناته —
   نسخة احتياطية، واستعادة تلقائية عند فشل فحص ما بعد التثبيت.
6. **لا تثبيت تلقائي**: التحميل والتثبيت لا يبدآن إلا بنقر المستخدم.
"""
import hashlib
import json
import os
import ssl
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

MANIFEST_NAME = "latest.json"
BUCKET = "app-updates"
MAX_BYTES = 300 * 1024 * 1024      # 300 ميجابايت حدّ أقصى
TIMEOUT = 20

_state = {"checked": False, "available": False, "info": None,
          "error": "", "when": ""}
_thread = None


# ══════════════════════════════════════════════════════════════════
# الروابط
# ══════════════════════════════════════════════════════════════════

def _base_url():
    """عنوان السحابة المعتمد — مصدر التحديثات الوحيد.

    يُقرأ من القارئ المركزي نفسه الذي يستعمله الدخول السحابي،
    فلا يحتاج إعداداً منفصلاً.
    """
    u = ""
    try:
        from core import app_config
        u = (app_config.supabase_url() or "").strip()
    except Exception:
        u = ""
    if not u:
        u = (os.environ.get("SUPABASE_URL") or "").strip()
    return u.rstrip("/")


def manifest_url():
    base = _base_url()
    if not base:
        return ""
    return f"{base}/storage/v1/object/public/{BUCKET}/{MANIFEST_NAME}"


def _allowed(url):
    """يتحقق أن الرابط مشفّر وضمن نطاق السحابة المعتمد."""
    if not url.lower().startswith("https://"):
        return False, "الرابط غير مشفّر (HTTPS مطلوب)"
    base = _base_url()
    if not base:
        return False, "عنوان السحابة غير مضبوط"
    host = base.split("//", 1)[-1].split("/", 1)[0].lower()
    url_host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    if url_host != host:
        return False, f"الرابط خارج النطاق المعتمد ({host})"
    return True, ""


def _ctx():
    return ssl.create_default_context()


# ══════════════════════════════════════════════════════════════════
# الفحص
# ══════════════════════════════════════════════════════════════════

def _vtuple(v):
    out = []
    for part in str(v).split("."):
        d = "".join(c for c in part if c.isdigit())
        out.append(int(d) if d else 0)
    while len(out) < 4:
        out.append(0)
    return tuple(out[:4])


def check(timeout=TIMEOUT):
    """يقرأ البيان المنشور ويقارن الإصدار — بلا تحميل."""
    from services import updater
    url = manifest_url()
    if not url:
        raise ValueError("عنوان السحابة غير مضبوط في إعدادات النظام")
    ok, why = _allowed(url)
    if not ok:
        raise ValueError(why)

    req = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout,
                                context=_ctx()) as r:
        raw = r.read(1 << 20).decode("utf-8", "replace")
    man = json.loads(raw)

    ver = str(man.get("version") or "")
    cur = updater.current_version()
    pkg = str(man.get("url") or "")
    if pkg and not pkg.lower().startswith("http"):
        pkg = f"{_base_url()}/storage/v1/object/public/{BUCKET}/{pkg}"

    return {
        "version": ver,
        "current": cur,
        "newer": bool(ver) and _vtuple(ver) > _vtuple(cur),
        "url": pkg,
        "sha256": str(man.get("sha256") or ""),
        "size": int(man.get("size") or 0),
        "notes": man.get("notes") or "",
        "date": man.get("date") or "",
        "min_version": str(man.get("min_version") or ""),
    }


def start_background_check(delay=8.0, on_done=None):
    """فحص صامت بعد الإقلاع — لا يعطّل شيئاً ولا يزعج عند الفشل."""
    global _thread

    def runner():
        import time
        time.sleep(delay)
        try:
            info = check()
            _state.update({"checked": True, "available": info["newer"],
                           "info": info, "error": "",
                           "when": info.get("date", "")})
        except Exception as e:
            # تعذّر الفحص (بلا إنترنت مثلاً) ليس خطأ يُعرض للمستخدم
            _state.update({"checked": True, "available": False,
                           "info": None,
                           "error": f"{type(e).__name__}: {e}"})
        if callable(on_done):
            try:
                on_done(dict(_state))
            except Exception:
                pass

    if _thread is not None and _thread.is_alive():
        return _thread
    _thread = threading.Thread(target=runner, daemon=True,
                               name="JadeiteUpdateCheck")
    _thread.start()
    return _thread


def status():
    return dict(_state)


# ══════════════════════════════════════════════════════════════════
# التحميل
# ══════════════════════════════════════════════════════════════════

def download(url, sha256="", on_progress=None, timeout=TIMEOUT):
    """يحمّل الحزمة ويتحقق من بصمتها — يحذفها عند أي خلل.

    البصمة إلزامية: بلا تحقق قد يُثبَّت ملف مبتور أو مُبدَّل، وهذا
    كود يعمل على بيانات محاسبية.
    """
    ok, why = _allowed(url)
    if not ok:
        raise ValueError(why)
    if not sha256:
        raise ValueError(
            "البيان بلا بصمة تحقق — التحميل مرفوض لأمان النظام")

    tmp_dir = Path(tempfile.gettempdir()) / "jadeite_updates"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / (url.rsplit("/", 1)[-1] or "update.jup")
    if dest.exists():
        dest.unlink()

    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=_ctx()) as r:
            total = int(r.headers.get("Content-Length") or 0)
            if total and total > MAX_BYTES:
                raise ValueError("حجم الحزمة يتجاوز الحدّ المسموح")
            with open(str(dest), "wb") as f:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_BYTES:
                        raise ValueError(
                            "حجم الحزمة يتجاوز الحدّ المسموح")
                    h.update(chunk)
                    f.write(chunk)
                    if callable(on_progress):
                        try:
                            on_progress(got, total)
                        except Exception:
                            pass
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    if h.hexdigest().lower() != str(sha256).lower():
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise ValueError(
            "بصمة الحزمة المحمَّلة لا تطابق المعلنة — "
            "الملف تالف أو معدَّل. أُلغي التحديث.")
    return str(dest)


def download_and_apply(info, on_progress=None, on_step=None):
    """يحمّل ثم يثبّت — بكل ضمانات المُحدِّث المحلي."""
    from services import updater
    path = download(info["url"], info.get("sha256", ""),
                    on_progress=on_progress)
    if callable(on_step):
        on_step("التحقق من الحزمة وتثبيتها…")
    return updater.apply_update(path, on_step=on_step)
