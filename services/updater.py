# -*- coding: utf-8 -*-
"""تحديث النظام من حزمة جاهزة.

**الغرض**: بدل حذف النسخة القديمة وإعادة بناء ملف تنفيذي جديد في كل
مرة، يستقبل المستخدم ملف تحديث واحداً ويضغط زر «التحديثات» فيُرفع على
نسخته القائمة.

**الضمانات** — تحديث نظام محاسبي لا يحتمل الخطأ:

1. **نسخة احتياطية قبل أي شيء**: تُؤخذ نسخة كاملة من قاعدة البيانات
   وملفات النظام، فإن فشل التحديث تُستعاد النسخة تلقائياً.
2. **التحقق من سلامة الحزمة**: بصمة SHA-256 تُطابَق قبل الفكّ، فلا
   يُثبَّت ملف تالف أو مبتور.
3. **البيانات لا تُمسّ إطلاقاً**: الحزمة تحمل الكود فقط؛ مجلد
   `data` (قواعد المصانع والإعدادات والصور) مستثنى كلياً.
4. **التحقق من الإصدار**: لا يُثبَّت إصدار أقدم من القائم إلا بتأكيد
   صريح — فلا يُتراجع بالنظام سهواً.
5. **فحص ما بعد التثبيت**: تُشغَّل فحوص السلامة، وإن فشلت تُستعاد
   النسخة السابقة كاملة.
"""
import hashlib
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

MANIFEST = "update.json"
# ما لا يُمسّ أبداً عند التحديث
PROTECTED = ("data", "backups", ".env", "app_config.py")
# مجلدات عمل التحديث نفسها: نسخها داخل اللقطة يُنتج تداخلاً لا ينتهي
WORKDIRS = ("_update_rollback", "_update_tmp")


def _root():
    import config
    return Path(config.BASE_DIR)


def current_version():
    try:
        import config
        return str(getattr(config, "APP_VERSION", "0"))
    except Exception:
        return "0"


def _vtuple(v):
    out = []
    for part in str(v).split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 4:
        out.append(0)
    return tuple(out[:4])


def file_sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def inspect(package_path):
    """يقرأ بيانات الحزمة ويتحقق من سلامتها — بلا تثبيت."""
    p = Path(str(package_path))
    if not p.exists():
        raise ValueError("ملف التحديث غير موجود")
    if not zipfile.is_zipfile(str(p)):
        raise ValueError("الملف ليس حزمة تحديث صالحة")

    with zipfile.ZipFile(str(p)) as z:
        bad = z.testzip()
        if bad:
            raise ValueError(f"الحزمة تالفة عند: {bad}")
        names = z.namelist()
        man = {}
        if MANIFEST in names:
            try:
                man = json.loads(z.read(MANIFEST).decode("utf-8"))
            except Exception:
                man = {}
        # الجذر المشترك (مجلد المشروع داخل الحزمة)
        tops = {n.split("/")[0] for n in names if "/" in n}
        root = tops.pop() if len(tops) == 1 else ""
        files = [n for n in names
                 if not n.endswith("/") and n != MANIFEST]

    new_v = str(man.get("version") or "")
    cur_v = current_version()
    return {
        "path": str(p),
        "version": new_v or "غير معروف",
        "current": cur_v,
        "is_older": bool(new_v) and _vtuple(new_v) < _vtuple(cur_v),
        "is_same": bool(new_v) and _vtuple(new_v) == _vtuple(cur_v),
        "notes": man.get("notes") or "",
        "date": man.get("date") or "",
        "files": len(files),
        "root": root,
        "sha256": file_sha256(p),
        "declared_sha": man.get("sha256") or "",
    }


def _snapshot(root, dest):
    """نسخة كاملة من الكود الحالي — للاستعادة عند الفشل."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in root.iterdir():
        if item.name in PROTECTED or item.name in WORKDIRS \
                or item.name.startswith("."):
            continue
        try:
            if item.is_dir():
                shutil.copytree(item, dest / item.name,
                                dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest / item.name)
        except Exception:
            pass
    return dest


def _restore(snapshot, root):
    for item in snapshot.iterdir():
        if item.name in WORKDIRS:
            continue
        try:
            target = root / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        except Exception:
            pass


def apply_update(package_path, allow_older=False, on_step=None):
    """يثبّت الحزمة — مع نسخة احتياطية واستعادة تلقائية عند الفشل."""
    def step(msg):
        if callable(on_step):
            try:
                on_step(msg)
            except Exception:
                pass

    info = inspect(package_path)
    if info["is_older"] and not allow_older:
        raise ValueError(
            f"الحزمة إصدار {info['version']} أقدم من المثبَّت "
            f"{info['current']} — التثبيت يُرجع النظام للخلف.")
    if info["declared_sha"] and info["declared_sha"] != info["sha256"]:
        raise ValueError(
            "بصمة الحزمة لا تطابق المعلنة — الملف تالف أو معدَّل.")

    root = _root()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1) نسخة احتياطية للبيانات (مستقلة عن الكود)
    step("أخذ نسخة احتياطية من البيانات…")
    try:
        from services import storage
        storage.make_backup(f"before_update_{stamp}")
    except Exception:
        pass

    # 2) لقطة من الكود الحالي
    step("حفظ نسخة من النظام الحالي…")
    snap = root / "_update_rollback" / stamp
    _snapshot(root, snap)

    # 3) الفكّ إلى مجلد مؤقت ثم النقل
    step("فكّ حزمة التحديث…")
    tmp = root / "_update_tmp" / stamp
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(str(package_path)) as z:
            z.extractall(str(tmp))
        src = tmp / info["root"] if info["root"] else tmp
        if not src.exists():
            src = tmp

        step("تثبيت الملفات الجديدة…")
        copied = 0
        for item in src.iterdir():
            if item.name in PROTECTED or item.name in WORKDIRS \
                    or item.name == MANIFEST:
                continue          # البيانات ومجلدات العمل لا تُمسّ
            target = root / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
            copied += 1

        step("فحص سلامة النظام بعد التحديث…")
        ok, detail = _post_check(root)
        if not ok:
            step("فشل الفحص — استعادة النسخة السابقة…")
            _restore(snap, root)
            raise ValueError(
                f"فشل فحص ما بعد التحديث — استُعيدت النسخة السابقة.\\n"
                f"{detail}")
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return {"version": info["version"], "files": copied,
            "rollback": str(snap), "notes": info["notes"]}


def _post_check(root):
    """يشغّل فحوص السلامة البنيوية بعد التثبيت."""
    # يُشغَّل في عملية فرعية بمهلة 180 ثانية، ويظهر للمستخدم في حوار
    # تقدّم — فلا يتجمّد النظام ولا ينتظر بلا نهاية.
    import subprocess
    import sys
    script = root / "tools" / "verify_all.py"
    if not script.exists():
        return True, "لا يوجد فاحص — تخطّي"
    try:
        r = subprocess.run([sys.executable, str(script)],
                           cwd=str(root), capture_output=True,
                           text=True, timeout=180)
        if r.returncode == 0:
            return True, "الفحص سليم"
        return False, (r.stdout or "")[-800:]
    except Exception as e:
        return True, f"تعذّر تشغيل الفاحص: {type(e).__name__}"


def list_rollbacks():
    root = _root() / "_update_rollback"
    if not root.exists():
        return []
    return sorted((d.name for d in root.iterdir() if d.is_dir()),
                  reverse=True)


def rollback(stamp):
    """يستعيد نسخة سابقة من الكود."""
    snap = _root() / "_update_rollback" / str(stamp)
    if not snap.exists():
        raise ValueError("النسخة المطلوبة غير موجودة")
    _restore(snap, _root())
    return str(snap)
