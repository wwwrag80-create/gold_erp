# -*- coding: utf-8 -*-
"""نشر حزمة تحديث على السحابة.

    python tools/publish_update.py

يبني الحزمة، يرفعها إلى مساحة التخزين، ثم ينشر بيان `latest.json`
الذي يقرأه كل عميل فيرى الإشعار.

**ترتيب الخطوات مقصود**: تُرفع الحزمة **أولاً** ثم البيان. لو نُشر
البيان قبل اكتمال رفع الحزمة، لرأى العملاء إشعاراً برابط لا يعمل.

يحتاج مفتاح الخدمة (`SUPABASE_SERVICE_KEY`) — لا يُوزَّع مع النظام
ولا يُخزَّن فيه؛ يُقرأ من متغيّر البيئة عند النشر فقط.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BUCKET = "app-updates"
MANIFEST = "latest.json"


def _cfg():
    """يقرأ إعدادات السحابة من القارئ المركزي (.env) مباشرةً.

    فلا يحتاج المستخدم ضبط أي متغيّر بيئة يدوياً — الإعدادات
    الموجودة في `.env` تكفي للنشر.
    """
    from core import app_config
    url = (app_config.supabase_url() or "").strip().rstrip("/")
    key = (app_config.supabase_service_key()
           or os.environ.get("SUPABASE_SERVICE_KEY") or "").strip()
    if not url:
        raise SystemExit(
            "SUPABASE_URL غير موجود.\n"
            "افتح ملف .env وتأكد من وجود السطر:\n"
            "    SUPABASE_URL=https://xxxx.supabase.co")
    if not key:
        raise SystemExit(
            "SUPABASE_SERVICE_KEY غير موجود.\n"
            "افتح ملف .env وتأكد من وجود السطر:\n"
            "    SUPABASE_SERVICE_KEY=<مفتاح service_role>\n\n"
            "تجده في: Supabase ← Settings ← API ← service_role")
    return url, key


def _upload(url, key, name, data, content_type):
    """يرفع ملفاً — يستبدل الموجود إن وُجد."""
    endpoint = f"{url}/storage/v1/object/{BUCKET}/{name}"
    req = urllib.request.Request(
        endpoint, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": content_type,
            "x-upsert": "true",
        })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status in (200, 201)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if e.code == 404:
            raise SystemExit(
                f"مساحة التخزين «{BUCKET}» غير موجودة.\n"
                f"أنشئها في Supabase ← Storage باسم {BUCKET} "
                f"واجعلها عامة (public).")
        raise SystemExit(f"فشل الرفع ({e.code}): {detail}")


def main():
    url, key = _cfg()

    print("بناء الحزمة…")
    from tools.make_update import build
    r = build(str(ROOT.parent))
    pkg = Path(r["path"])
    print(f"  الإصدار {r['version']} · {r['files']} ملف · "
          f"{r['size_mb']} ميجابايت")

    # 1) الحزمة أولاً
    print("رفع الحزمة…")
    _upload(url, key, pkg.name, pkg.read_bytes(),
            "application/octet-stream")
    print(f"  ✔ {pkg.name}")

    # 2) ثم البيان — فلا يرى العميل إشعاراً برابط ناقص
    notes = ""
    for name in ("الجديد.txt", "WHATSNEW.txt"):
        p = ROOT / name
        if p.exists():
            notes = p.read_text(encoding="utf-8-sig")[:4000]
            break
    manifest = {
        "product": "Jadeite Gold ERP",
        "version": r["version"],
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "url": pkg.name,
        "sha256": r["sha256"],
        "size": pkg.stat().st_size,
        "notes": notes,
    }
    print("نشر البيان…")
    _upload(url, key, MANIFEST,
            json.dumps(manifest, ensure_ascii=False, indent=1)
            .encode("utf-8"),
            "application/json")
    print(f"  ✔ {MANIFEST}")

    pub = f"{url}/storage/v1/object/public/{BUCKET}/{MANIFEST}"
    print("=" * 56)
    print("  تم النشر — كل عميل سيرى الإشعار عند الإقلاع")
    print("=" * 56)
    print(f"  البيان: {pub}")
    print(f"  البصمة: {r['sha256'][:40]}…")


if __name__ == "__main__":
    main()
