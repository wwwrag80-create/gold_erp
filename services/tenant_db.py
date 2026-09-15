# -*- coding: utf-8 -*-
"""عزل بيانات المصانع — قاعدة بيانات مستقلة لكل مصنع.

**الثغرة التي يعالجها**: كانت قاعدة البيانات ملفاً واحداً ثابتاً
(`data/gold_erp.db`) لا يعتمد على هوية المصنع. فأي حساب يدخل على نفس
الجهاز يرى بيانات كل المصانع: شجرة الحسابات نفسها والفواتير نفسها —
وهو خرق كامل لعزل مساحات العمل.

**الحل**: لكل مصنع (tenant) ملف قاعدة بيانات مستقل تماماً:

    <مجلد البيانات>/tenants/<tenant_id>/gold_erp.db

فالعميل «أ» لا يستطيع رؤية بيانات العميل «ب» ولو على الجهاز نفسه،
لأنهما لا يتشاركان ملفاً واحداً أصلاً — وهو أقوى من الترشيح بالاستعلام
لأنه عزل فيزيائي لا يمكن تجاوزه بخطأ برمجي.
"""
import os
import threading
from pathlib import Path

# هوية المصنع النشطة في هذه الجلسة (تُضبط بعد تسجيل الدخول)
_active = threading.local()

LEGACY_NAME = "gold_erp.db"


def set_active_tenant(tenant_id):
    """يضبط هوية المصنع للجلسة الحالية — تُستدعى بعد تسجيل الدخول."""
    _active.tenant_id = (tenant_id or "").strip() or None
    return _active.tenant_id


def active_tenant():
    return getattr(_active, "tenant_id", None)


def clear_active_tenant():
    _active.tenant_id = None


def _safe_id(tid):
    """اسم مجلد آمن من هوية المصنع."""
    keep = "-_"
    return "".join(c for c in str(tid) if c.isalnum() or c in keep)[:64]


def tenant_db_path(base_dir, tenant_id=None):
    """مسار قاعدة بيانات المصنع.

    بلا هوية (أول تشغيل قبل الدخول) يُستخدم الملف الافتراضي، فيعمل
    النظام كما كان ولا تنكسر التهيئة الأولى.
    """
    base = Path(base_dir)
    tid = tenant_id if tenant_id is not None else active_tenant()
    if not tid:
        return base / "data" / LEGACY_NAME
    d = base / "data" / "tenants" / _safe_id(tid)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d / LEGACY_NAME


def migrate_legacy_into(base_dir, tenant_id):
    """ينقل قاعدة البيانات القديمة المشتركة إلى مصنع محدد — مرة واحدة.

    يُستدعى عند أول دخول للمالك بعد الترقية، فلا تضيع بياناته السابقة
    ولا تُرى من بقية المصانع.
    """
    import shutil
    base = Path(base_dir)
    legacy = base / "data" / LEGACY_NAME
    target = tenant_db_path(base, tenant_id)
    if not legacy.exists() or target.exists():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        for ext in ("-wal", "-shm"):
            src = Path(str(legacy) + ext)
            if src.exists():
                shutil.copy2(src, Path(str(target) + ext))
        # نُبقي الأصل كنسخة احتياطية بدل حذفه
        legacy.rename(legacy.with_name("gold_erp_legacy_backup.db"))
        return True
    except Exception:
        return False


def list_tenant_dbs(base_dir):
    """قواعد بيانات المصانع الموجودة على هذا الجهاز — للمدير."""
    root = Path(base_dir) / "data" / "tenants"
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        f = d / LEGACY_NAME
        if f.exists():
            try:
                size = round(f.stat().st_size / 1024, 1)
            except Exception:
                size = 0
            out.append({"tenant_id": d.name, "path": str(f),
                        "size_kb": size})
    return out
