# -*- coding: utf-8 -*-
"""بناء حزمة التحديث.

يُنتج ملف `.jup` (حزمة تحديث جاديت) يحمل الكود مع بيان يوضّح الإصدار
والتاريخ وما تغيّر، وبصمة SHA-256 للتحقق من سلامته.

    python tools/make_update.py

الحزمة **لا تحمل أي بيانات**: مجلد `data` والنسخ الاحتياطية وملف
البيئة مستثناة — فالتحديث لا يمكن أن يمسّ قواعد المصانع.
"""
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ما لا يدخل الحزمة إطلاقاً
SKIP_DIRS = {
    "data", "backups", "dist", "build", "__pycache__", ".git",
    "_update_tmp", "_update_rollback", ".idea", ".vscode",
}
SKIP_SUFFIX = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".bak",
               ".spec", ".log", ".jup"}
SKIP_FILES = {".env", ".setup_done", "app_config.py"}


def _version():
    import config
    return str(getattr(config, "APP_VERSION", "0"))


def _notes():
    """ملاحظات التحديث من ملف «الجديد.txt» إن وُجد."""
    for name in ("الجديد.txt", "WHATSNEW.txt"):
        p = ROOT / name
        if p.exists():
            try:
                return p.read_text(encoding="utf-8-sig")[:4000]
            except Exception:
                pass
    return ""


def _files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        if p.name in SKIP_FILES:
            continue
        yield p, rel


def build(out_dir=None):
    ver = _version()
    out_dir = Path(out_dir) if out_dir else ROOT.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"jadeite_update_{ver}.jup"

    manifest = {
        "product": "Jadeite Gold ERP",
        "version": ver,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes": _notes(),
        "protected": ["data", "backups", ".env", "app_config.py"],
    }

    n = 0
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for p, rel in _files():
            z.write(str(p), f"gold_erp/{rel.as_posix()}")
            n += 1
        z.writestr("update.json",
                   json.dumps(manifest, ensure_ascii=False, indent=1))

    # البصمة تُحسب بعد الإغلاق ثم تُكتب في بيان مرافق
    h = hashlib.sha256()
    with open(str(out), "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    sha = h.hexdigest()
    (out.with_suffix(".sha256")).write_text(
        f"{sha}  {out.name}\n", encoding="utf-8")

    size = round(out.stat().st_size / 1024 / 1024, 2)
    return {"path": str(out), "files": n, "version": ver,
            "size_mb": size, "sha256": sha}


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else None
    r = build(dest)
    print("=" * 56)
    print("  حزمة التحديث جاهزة")
    print("=" * 56)
    print(f"  الإصدار : {r['version']}")
    print(f"  الملفات : {r['files']}")
    print(f"  الحجم   : {r['size_mb']} ميجابايت")
    print(f"  المسار  : {r['path']}")
    print(f"  البصمة  : {r['sha256'][:32]}…")
    print("=" * 56)
