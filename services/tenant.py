# -*- coding: utf-8 -*-
"""هوية المصنع (Tenant Identity) وإعدادات السحابة.

**قرار معماري جوهري — الأداء أولاً:**
قاعدة البيانات المحلية في كل مصنع تخصّ ذلك المصنع وحده، فلا حاجة
لترشيح كل استعلام بـ`tenant_id` محلياً — وهو ما يبقي الشاشات بسرعتها
القصوى مهما ضخمت البيانات. يُختم `tenant_id` على السجلات وعلى حمولات
المزامنة، ويُستخدم للفصل **في السحابة** حيث تجتمع بيانات كل المصانع.

بهذا نجمع: صفر تأخير محلياً · وعزل تام سحابياً.
"""
import json
import uuid
from pathlib import Path

import config

TENANT_FILE = config.BASE_DIR / "data" / "tenant.json"

import app_config

_DEFAULTS = {
    "tenant_id": "",
    "factory_name": config.COMPANY_NAME,
    "license_key": "",
    # تُقرأ تلقائياً من .env / config.ini إن لم تُضبط يدوياً
    "cloud_url": app_config.supabase_url(),
    "cloud_key": app_config.supabase_key(),
    "sync_enabled": bool(app_config.supabase_url()
                         and app_config.supabase_key()),
    "sync_interval_sec": 30,
    "role": "factory",          # factory | super_admin
}


def _seed_from_bundle():
    """ينسخ هوية المصنع المرفقة مع الحزمة إلى المجلد الدائم أول مرة.

    النسخة المُسلَّمة تحمل هويتها داخلها؛ فتُنقل عند أول تشغيل إلى مجلد
    البيانات الدائم فتبقى ثابتة بعد ذلك.
    """
    if TENANT_FILE.exists():
        return
    try:
        import sys
        mei = getattr(sys, "_MEIPASS", None)
        if not mei:
            return
        src = Path(mei) / "data" / "tenant.json"
        if src.exists():
            TENANT_FILE.parent.mkdir(parents=True, exist_ok=True)
            TENANT_FILE.write_text(src.read_text(encoding="utf-8"),
                                   encoding="utf-8")
    except Exception:
        pass


def _read():
    _seed_from_bundle()
    try:
        if TENANT_FILE.exists():
            data = json.loads(TENANT_FILE.read_text(encoding="utf-8"))
            merged = dict(_DEFAULTS)
            merged.update({k: v for k, v in data.items() if k in _DEFAULTS})
            # ملف الإعدادات المركزي يملأ ما تُرك فارغاً
            if not merged.get("cloud_url"):
                merged["cloud_url"] = app_config.supabase_url()
            if not merged.get("cloud_key"):
                merged["cloud_key"] = app_config.supabase_key()
            return merged
    except Exception:
        pass
    return dict(_DEFAULTS)


def _write(data):
    TENANT_FILE.parent.mkdir(parents=True, exist_ok=True)
    TENANT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")


_state = _read()


def ensure_tenant_id():
    """يولّد هوية ثابتة للمصنع عند أول تشغيل ويحفظها محلياً."""
    global _state
    if not _state.get("tenant_id"):
        _state["tenant_id"] = f"F-{uuid.uuid4().hex[:12].upper()}"
        _write(_state)
    return _state["tenant_id"]


def tenant_id():
    return _state.get("tenant_id") or ensure_tenant_id()


def factory_name():
    return _state.get("factory_name") or config.COMPANY_NAME


def is_super_admin():
    return _state.get("role") == "super_admin"


def cloud_config():
    return {"url": _state.get("cloud_url", ""),
            "key": _state.get("cloud_key", ""),
            "enabled": bool(_state.get("sync_enabled")),
            "interval": int(_state.get("sync_interval_sec") or 30)}


def get_all():
    return dict(_state)


def update(**kw):
    """تحديث إعدادات المصنع أو السحابة وحفظها."""
    global _state
    for k, v in kw.items():
        if k in _DEFAULTS:
            _state[k] = v
    _write(_state)
    return dict(_state)


# ══════════════════════════════════════════════════════════════════
# انتحال الشخصية (Impersonation) — للمدير الأعلى فقط
# ══════════════════════════════════════════════════════════════════

_impersonated = {"tenant_id": None, "name": None}


def impersonate(target_tenant_id, target_name=None):
    """يتبنّى هوية مصنع آخر لعرض بياناته كما يراها صاحبه.

    متاح للمدير الأعلى حصراً، ولا يتطلب كلمة مرور المصنع لأن الاتصال
    يتم بمفتاح السحابة الخاص بالمالك.
    """
    if not is_super_admin():
        raise PermissionError("انتحال الشخصية متاح للمدير الأعلى فقط")
    if not target_tenant_id:
        raise ValueError("حدّد المصنع المطلوب")
    _impersonated["tenant_id"] = target_tenant_id
    _impersonated["name"] = target_name or target_tenant_id
    return dict(_impersonated)


def stop_impersonation():
    _impersonated["tenant_id"] = None
    _impersonated["name"] = None


def impersonating():
    return _impersonated["tenant_id"] is not None


def impersonation_info():
    return dict(_impersonated)


def effective_tenant_id():
    """الهوية المعتمدة حالياً — هوية المصنع المنتحَل إن وُجد."""
    return _impersonated["tenant_id"] or tenant_id()
