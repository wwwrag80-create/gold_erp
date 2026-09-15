# -*- coding: utf-8 -*-
"""قارئ الإعدادات المركزي (.env / config.ini).

ترتيب الأولوية: متغيّرات البيئة ← ملف `.env` ← ملف `config.ini` ←
القيم الافتراضية. فيمكن لكل مصنع تخصيص اتصاله دون تعديل الكود.
"""
import configparser
import os
from pathlib import Path

import os
import sys


def _app_dir():
    """مجلد الإعدادات الدائم — نفس مجلد بيانات النظام.

    في نسخة الملف الواحد يكون مجلد التنفيذ مؤقتاً، فتُقرأ الإعدادات
    وتُكتب في المجلد الدائم مع قاعدة البيانات.
    """
    try:
        import config as _cfg
        return Path(_cfg.BASE_DIR)
    except Exception:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent


def _bundle_dir():
    """مجلد الحزمة — لقراءة .env المرفق مع النسخة المُسلَّمة."""
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        return Path(mei)
    # هذا الملف داخل core/، فجذر المشروع أعلاه
    return Path(__file__).resolve().parent.parent


def _user_dir():
    """مجلد بيانات المستخدم القابل للكتابة دائماً.

    عند التثبيت في Program Files يكون مجلد التطبيق للقراءة فقط، فتُحفظ
    إعدادات المصنع هنا: %APPDATA%/JadeiteERP (أو ~/.jadeite_erp).
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
        d = base / "JadeiteERP"
    else:
        d = Path.home() / ".jadeite_erp"
    d.mkdir(parents=True, exist_ok=True)
    return d


BASE_DIR = _app_dir()
USER_DIR = _user_dir()

# الأولوية: ملف المستخدم (قابل للكتابة) ثم ملف بجانب التطبيق
BUNDLE_DIR = _bundle_dir()

# الأولوية: ملف دائم عند المستخدم ← بجانب التطبيق ← المرفق في الحزمة
if (BASE_DIR / ".env").exists():
    ENV_FILE = BASE_DIR / ".env"
elif (USER_DIR / ".env").exists():
    ENV_FILE = USER_DIR / ".env"
else:
    ENV_FILE = BUNDLE_DIR / ".env"
INI_FILE = ((BASE_DIR / "config.ini")
            if (BASE_DIR / "config.ini").exists()
            else (BUNDLE_DIR / "config.ini"))

_cache = None


def _load_env_file():
    data = {}
    if not ENV_FILE.exists():
        return data
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[_normalize_key(k)] = v.strip().strip('"').strip("'")
    return data


def _load_ini():
    data = {}
    if not INI_FILE.exists():
        return data
    cp = configparser.ConfigParser()
    try:
        cp.read(INI_FILE, encoding="utf-8")
        for section in cp.sections():
            for k, v in cp.items(section):
                data[_normalize_key(f"{section}_{k}")] = v
                data[_normalize_key(k)] = v
    except Exception:
        pass
    return data


# أخطاء إملائية شائعة تُصحَّح تلقائياً عند القراءة، فلا يتعطّل
# النظام بسبب حرف ناقص في اسم المفتاح.
_ALIASES = {
    "SUPABASE": "SUPABASE",      # SUP_BASE بلا حرف A
    "SUPPABASE": "SUPABASE",
    "SUPBASE": "SUPABASE",
    "SUPERBASE": "SUPABASE",
}


def _normalize_key(k):
    """يوحّد اسم المفتاح: أحرف كبيرة، بلا مسافات، مع تصحيح الإملاء."""
    k = (k or "").strip().upper().replace(" ", "").replace("-", "_")
    for wrong, right in _ALIASES.items():
        if k.startswith(wrong + "_"):
            return right + k[len(wrong):]
    return k


def _all():
    global _cache
    if _cache is None:
        merged = {}
        merged.update(_load_ini())
        merged.update(_load_env_file())
        merged.update({_normalize_key(k): v for k, v in os.environ.items()
                       if _normalize_key(k).startswith(
                           ("SUPABASE_", "JADEITE_"))})
        _cache = merged
    return _cache


def get(key, default=""):
    return _all().get(key, default)


def reload():
    global _cache
    _cache = None
    return _all()


def env_write_target():
    """أين تُكتب الإعدادات: بجانب التطبيق إن أمكن، وإلا مجلد المستخدم."""
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        probe = BASE_DIR / ".write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return BASE_DIR / ".env"
    except Exception:
        return USER_DIR / ".env"


def write_env(**kw):
    """يحفظ القيم في ملف .env (يُنشأ إن لم يوجد)."""
    global ENV_FILE
    current = _load_env_file()
    current.update({k: str(v) for k, v in kw.items()})
    lines = ["# إعدادات الاتصال السحابي — نظام جاديت",
             "# لا تشارك هذا الملف علناً إن حوى مفاتيح خدمية.", ""]
    lines += [f"{k}={v}" for k, v in sorted(current.items())]
    target = env_write_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV_FILE = target
    reload()
    return str(target)


# ══════════════════════════════════════════════════════════════════
# القيم السحابية المعتمدة
# ══════════════════════════════════════════════════════════════════

def supabase_url():
    """رابط المشروع منظّفاً من أي مسار زائد مثل /rest/v1."""
    u = (get("SUPABASE_URL", "") or "").strip().rstrip("/")
    for tail in ("/rest/v1", "/rest", "/auth/v1"):
        if u.endswith(tail):
            u = u[: -len(tail)]
    if u and not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u.rstrip("/")


def supabase_key():
    """المفتاح العام (publishable/anon) — يُستخدم في نسخ المصانع."""
    return get("SUPABASE_PUBLISHABLE_KEY") or get("SUPABASE_ANON_KEY", "")


def supabase_service_key():
    """مفتاح الخدمة — **لنسخة المدير الأعلى فقط** ولا يُوزَّع للمصانع."""
    return get("SUPABASE_SERVICE_KEY", "")
