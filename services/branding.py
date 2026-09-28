# -*- coding: utf-8 -*-
"""هوية المصنع — الشعار والاسم والبلد والعنوان والسجل في كل القوالب.

النسخة الواحدة من النظام تُسلَّم لأكثر من مصنع، ولكل مصنعٍ اسمه
وشعاره وعنوانه. الهوية لذلك **بيانٌ في قاعدة المصنع نفسها** لا ثابتٌ
في الكود:

* المصدر الوحيد: إعداد `factory_identity` في `app_settings` — فتنتقل
  الهوية مع النسخة الاحتياطية ومع نقل القاعدة، ولا تختلط بين مصنعين.
* نسخةٌ مرآة في مجلد البيانات (`branding/identity.json` والصور) —
  تُقرأ قبل فتح القاعدة، فتظهر البوابة بشعار المصنع من أول لحظة.
* `apply()` يكتب القيم على وحدة `config` وقت التشغيل: كل قالب وكل
  شاشة تقرأ `config.COMPANY_NAME` و`config.LOGO_PATH` عند الاستعمال،
  فيتبدّل كل شيء بلا إعادة تشغيل.

الصور تُحفظ بأسماء تحمل بصمتها (`logo_<hash>.png`): المتصفح ومحرّك
الطباعة يخزّنان الصورة بعنوانها، فلو بقي الاسم ثابتاً لطُبع الشعار
القديم بعد تغييره.
"""
import base64
import hashlib
import json
from pathlib import Path

import config

KEY = "factory_identity"

# (الحقل، اسم الثابت في config)
_CONFIG_MAP = (
    ("name", "COMPANY_NAME"), ("name_en", "COMPANY_NAME_EN"),
    ("tagline", "COMPANY_TAGLINE"),
    ("country", "COMPANY_COUNTRY"), ("country_en", "COMPANY_COUNTRY_EN"),
    ("address", "COMPANY_ADDRESS"), ("address_en", "COMPANY_ADDRESS_EN"),
    ("cr", "COMPANY_CR"), ("vat", "COMPANY_VAT_NUMBER"),
    ("phone", "COMPANY_PHONE"), ("email", "COMPANY_EMAIL"),
)
TEXT_FIELDS = tuple(k for k, _c in _CONFIG_MAP)
FIELDS = TEXT_FIELDS + ("layout", "logo_h", "logo_b64", "stamp_b64",
                        "show_vat", "show_en", "hide_logo")

# ترتيب الترويسة
LAYOUTS = (
    ("logo_left", "الشعار يساراً — الاسم وتحته البلد والعنوان والسجل يميناً"),
    ("logo_right", "الشعار يميناً — البيانات يساراً"),
    ("classic", "عربي يميناً · الشعار في الوسط · إنجليزي يساراً"),
)
LOGO_SIZES = ((70, "صغير"), (95, "متوسط"), (120, "كبير"), (150, "كبير جداً"))

# القيم الأصلية المسلَّمة مع الكود — تُلتقط مرةً قبل أي تطبيق
_ORIG = {c: getattr(config, c, "") for _k, c in _CONFIG_MAP}
_ORIG["LOGO_PATH"] = getattr(config, "LOGO_PATH", None)
_ORIG["LOGO_GOLD_PATH"] = getattr(config, "LOGO_GOLD_PATH", None)

_current = {}


def _dir():
    return Path(str(config.BASE_DIR)) / "branding"


def _mirror():
    return _dir() / "identity.json"


def defaults():
    """هوية المصنع قبل أن يعدّلها أحد — القيم المسلَّمة مع النظام.

    المصنع الذي جُهّزت نسخته بأداة «مصنع جديد» يحمل اسمه في
    `tenant.json` — فيُقترح اسمه لا اسم مصنع آخر.
    """
    d = {k: _ORIG.get(c, "") or "" for k, c in _CONFIG_MAP}
    try:
        from services import tenant
        fn = (tenant.get_all().get("factory_name") or "").strip()
        if fn:
            d["name"] = fn
    except Exception:
        pass
    d.update({"layout": "classic", "logo_h": 120, "logo_b64": "",
              "stamp_b64": "", "show_vat": False, "show_en": True,
              "hide_logo": False})
    return d


def _clean(data):
    out = defaults()
    for k, v in (data or {}).items():
        if k not in FIELDS:
            continue
        if k in TEXT_FIELDS:
            v = " ".join(str(v or "").split())
        out[k] = v
    if out["layout"] not in dict(LAYOUTS):
        out["layout"] = "logo_left"
    try:
        out["logo_h"] = max(50, min(180, int(out["logo_h"] or 120)))
    except (TypeError, ValueError):
        out["logo_h"] = 120
    out["show_vat"] = bool(out.get("show_vat"))
    out["show_en"] = bool(out.get("show_en"))
    out["hide_logo"] = bool(out.get("hide_logo"))
    return out


def validate(data):
    """أخطاء تمنع الاعتماد — نصوص عربية تُعرض كما هي."""
    d = _clean(data)
    errs = []
    if not d["name"]:
        errs.append("اسم المصنع مطلوب — هو أول ما يُطبع في كل ورقة")
    cr = d["cr"].replace(" ", "")
    if cr and not cr.isdigit():
        errs.append("السجل التجاري أرقامٌ فقط")
    vat = d["vat"].replace(" ", "")
    if vat and not (len(vat) == 15 and vat.isdigit()
                    and vat[0] == "3" and vat[-1] == "3"):
        errs.append("الرقم الضريبي 15 رقماً يبدأ وينتهي بـ 3")
    for key, label in (("logo_b64", "الشعار"), ("stamp_b64", "الختم")):
        if d[key] and not image_ok(d[key]):
            errs.append(f"صورة {label} غير صالحة")
    return errs


def image_ok(b64):
    try:
        raw = base64.b64decode(b64 or "", validate=True)
    except Exception:
        return False
    return raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff"


# ══════════════════════════════════════════════════════════════════
#  القراءة والحفظ
# ══════════════════════════════════════════════════════════════════

def load(conn):
    from models.fiscal import get_setting
    raw = get_setting(conn, KEY, "")
    if not raw:
        return defaults()
    try:
        return _clean(json.loads(raw))
    except Exception:
        return defaults()


def is_custom(conn):
    from models.fiscal import get_setting
    return bool(get_setting(conn, KEY, ""))


def save(conn, data, username=None):
    """يعتمد الهوية: تُحفظ في قاعدة المصنع ثم تُطبَّق فوراً."""
    from models.fiscal import set_setting
    errs = validate(data)
    if errs:
        raise ValueError("\n".join(errs))
    d = _clean(data)
    set_setting(conn, KEY, json.dumps(d, ensure_ascii=False), username)
    try:
        from services.audit import log_action
        log_action(conn, username, "update", "app_settings", 0,
                   f"هوية المصنع: {d['name']}")
    except Exception:
        pass
    apply(d)
    return d


def reset(conn, username=None):
    """يعيد الهوية المسلَّمة مع النظام."""
    conn.execute("DELETE FROM app_settings WHERE key=?", (KEY,))
    d = defaults()
    apply(d, custom=False)
    return d


# ══════════════════════════════════════════════════════════════════
#  التطبيق على النظام
# ══════════════════════════════════════════════════════════════════

def _write_image(b64, stem):
    """يكتب الصورة باسمٍ يحمل بصمتها ويعيد مسارها (أو None)."""
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
    ext = ".jpg" if raw[:3] == b"\xff\xd8\xff" else ".png"
    h = hashlib.sha1(raw).hexdigest()[:10]
    p = _dir() / f"{stem}_{h}{ext}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(raw)
        # صور النسخ السابقة لا حاجة لها
        for old in p.parent.glob(f"{stem}_*"):
            if old != p:
                try:
                    old.unlink()
                except OSError:
                    pass
        return p
    except OSError:
        return None


def apply(data, custom=True):
    """يكتب الهوية على `config` فتقرؤها القوالب والشاشات فوراً."""
    d = _clean(data)
    for k, c in _CONFIG_MAP:
        setattr(config, c, d[k])
    logo = _write_image(d["logo_b64"], "logo") if custom else None
    if custom and d["hide_logo"]:
        # مصنعٌ بلا شعار: لا يُطبع شعار مصنعٍ آخر مكانه
        config.LOGO_PATH = None
        config.LOGO_GOLD_PATH = None
    elif logo:
        config.LOGO_PATH = logo
        config.LOGO_GOLD_PATH = logo     # البوابة والرئيسية بالشعار نفسه
    else:
        config.LOGO_PATH = _ORIG["LOGO_PATH"]
        config.LOGO_GOLD_PATH = _ORIG["LOGO_GOLD_PATH"]
        if custom and not d["logo_b64"]:
            for old in _dir().glob("logo_*"):
                try:
                    old.unlink()
                except OSError:
                    pass
    config.STAMP_PATH = (_write_image(d["stamp_b64"], "stamp")
                         if custom else None)
    config.HEADER_LAYOUT = d["layout"] if custom else "classic"
    config.LOGO_HEIGHT = d["logo_h"]
    config.HEADER_SHOW_VAT = d["show_vat"]
    config.HEADER_SHOW_EN = d["show_en"]
    _current.clear()
    _current.update(d)
    _current["custom"] = bool(custom)
    _write_mirror(d if custom else None)
    return d


def _write_mirror(d):
    try:
        m = _mirror()
        if d is None:
            if m.exists():
                m.unlink()
            return
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def apply_cached():
    """قبل فتح القاعدة: يطبّق آخر هويةٍ اعتُمدت على هذا الجهاز."""
    try:
        m = _mirror()
        if m.exists():
            apply(json.loads(m.read_text(encoding="utf-8")))
            return True
    except Exception:
        pass
    return False


def sync_from_db():
    """بعد فتح القاعدة: القاعدة هي المرجع — فلو استُعيدت نسخةُ مصنعٍ
    آخر أو نُقلت القاعدة إلى جهاز جديد تتبعها الهوية."""
    from database.database import db
    with db(readonly=True) as conn:
        custom = is_custom(conn)
        d = load(conn)
    apply(d, custom=custom)
    return d


_PREVIEW_ATTRS = tuple(c for _k, c in _CONFIG_MAP) + (
    "LOGO_PATH", "LOGO_GOLD_PATH", "STAMP_PATH", "HEADER_LAYOUT",
    "LOGO_HEIGHT", "HEADER_SHOW_VAT", "HEADER_SHOW_EN")


def preview_html(data):
    """ترويسةٌ بقيمٍ لم تُعتمد بعد — للمعاينة الحيّة في الحوار.

    تُكتب القيم على `config` لحظة البناء ثم تُعاد كما كانت، والصور
    بأسماء معاينة مستقلة فلا تُمسّ صورة الهوية المعتمدة.
    """
    from services import print_manager as pm
    d = _clean(data)
    saved = {a: getattr(config, a, None) for a in _PREVIEW_ATTRS}
    try:
        for k, c in _CONFIG_MAP:
            setattr(config, c, d[k])
        logo = _write_image(d["logo_b64"], "preview_logo")
        if d["hide_logo"]:
            config.LOGO_PATH = None
        elif logo:
            config.LOGO_PATH = logo
        else:
            config.LOGO_PATH = _ORIG["LOGO_PATH"]
        config.STAMP_PATH = _write_image(d["stamp_b64"], "preview_stamp")
        config.HEADER_LAYOUT = d["layout"]
        config.LOGO_HEIGHT = d["logo_h"]
        config.HEADER_SHOW_VAT = d["show_vat"]
        config.HEADER_SHOW_EN = d["show_en"]
        return pm.letterhead(), pm._footer()
    finally:
        for a, v in saved.items():
            setattr(config, a, v)


def current():
    return dict(_current) if _current else dict(defaults(), custom=False)


# ══════════════════════════════════════════════════════════════════
#  التصدير والاستيراد — لنقل الهوية بين الأجهزة أو تجهيز نسخة مصنع
# ══════════════════════════════════════════════════════════════════

EXPORT_TAG = "gold_erp.factory_identity"


def export_file(path, data):
    payload = {"type": EXPORT_TAG, "version": 1,
               "identity": _clean(data)}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    return path


def import_file(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        raise ValueError("الملف ليس ملف هوية مصنع صالحاً")
    if not isinstance(payload, dict) or payload.get("type") != EXPORT_TAG:
        raise ValueError("الملف ليس ملف هوية مصنع صالحاً")
    return _clean(payload.get("identity") or {})
