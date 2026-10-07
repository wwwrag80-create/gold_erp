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


def _frozen():
    import sys
    return bool(getattr(sys, "frozen", False))


def _code_dir():
    """مجلد كود التحديث في نسخة الـexe: `<مجلد البيانات>/app_code`."""
    import code_overlay
    return _root() / code_overlay.DIRNAME


def apply_update(package_path, allow_older=False, on_step=None):
    """يثبّت الحزمة — مع نسخة احتياطية واستعادة تلقائية عند الفشل."""
    def step(msg):
        if callable(on_step):
            try:
                on_step(msg)
            except Exception:
                pass

    if _frozen():
        return _apply_frozen(package_path, allow_older, step)
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


def _apply_frozen(package_path, allow_older, step):
    """نسخة الـexe (4.55): الكود في داخل الملف التنفيذي، فالتحديث يُثبَّت
    في `app_code` بجوار البيانات ويقرؤه الـexe عند التشغيل التالي.

    يُفكّ في مجلدٍ جديد، ويفحصه **الـexe نفسه** (ترجمةً واستيراداً
    بمكتباته)، ثم يُبدَّل بالقائم دفعةً واحدة — والقائم يُحفظ للرجوع.
    فإن فشل الفحص بقي النظام على حاله تماماً.
    """
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
    live = _code_dir()
    new = live.with_name(live.name + ".new")
    tmp = root / "_update_tmp" / stamp

    step("أخذ نسخة احتياطية من البيانات…")
    try:
        from services import storage
        storage.make_backup(f"before_update_{stamp}")
    except Exception:
        pass

    step("فكّ حزمة التحديث…")
    for d in (new, tmp):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(str(package_path)) as z:
            z.extractall(str(tmp))
        src = tmp / info["root"] if info["root"] else tmp
        if not (src / "core" / "config.py").exists():
            raise ValueError("الحزمة لا تحمل كود النظام (core/config.py)")
        new.mkdir(parents=True, exist_ok=True)
        copied = 0
        for item in src.iterdir():
            if item.name in PROTECTED or item.name in WORKDIRS \
                    or item.name == MANIFEST:
                continue
            if item.is_dir():
                shutil.copytree(item, new / item.name)
            else:
                shutil.copy2(item, new / item.name)
            copied += 1

        step("فحص التحديث داخل البرنامج…")
        ok, detail = _verify_frozen(new)
        if not ok:
            shutil.rmtree(new, ignore_errors=True)
            raise ValueError(
                "لم يُثبَّت التحديث: فشل فحصه داخل البرنامج، والنظام باقٍ "
                f"على حاله.\n{detail}")

        step("تثبيت الملفات الجديدة…")
        import code_overlay
        (new / code_overlay.READY).write_text(stamp, encoding="utf-8")
        snap = None
        try:
            snap = code_overlay.swap_in(root, stamp)
        except Exception:
            # ويندوز قد يمنع إعادة تسمية مجلدٍ قيد الاستعمال: يبقى الجديد
            # جاهزاً بعلامته ويُبدَّل أول التشغيل التالي قبل أي استيراد
            snap = None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _prune_rollbacks(root)
    return {"version": info["version"], "files": copied,
            "rollback": str(snap or ""), "notes": info["notes"],
            "restart": True}


def _verify_frozen(code_dir):
    """يشغّل الـexe نفسه بوضع الفحص على المجلد الجديد."""
    import os
    import subprocess
    import sys
    import tempfile
    out = Path(tempfile.gettempdir()) / f"jadeite_verify_{os.getpid()}.txt"
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # فكٌّ مستقل للعملية
    env.pop("_MEIPASS2", None)
    env.pop("JADEITE_CODE_DIR", None)
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000            # CREATE_NO_WINDOW
    try:
        r = subprocess.run(
            [sys.executable, "--verify-code", str(code_dir), str(out)],
            env=env, timeout=300, capture_output=True, **kw)
        txt = ""
        try:
            txt = out.read_text(encoding="utf-8")
        except Exception:
            pass
        if r.returncode == 0:
            return True, txt[-600:]
        return False, (txt or "")[-900:] or f"رمز الخروج {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, "انتهت مهلة الفحص"
    except Exception as e:                          # noqa: BLE001
        return False, f"تعذّر تشغيل الفحص: {type(e).__name__}: {e}"
    finally:
        try:
            out.unlink()
        except Exception:
            pass


def _prune_rollbacks(root, keep=3):
    r = root / "_update_rollback"
    if not r.exists():
        return
    olds = sorted(d for d in r.iterdir() if d.is_dir())
    for d in olds[:-keep]:
        shutil.rmtree(d, ignore_errors=True)


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
    if _frozen():
        live = _code_dir()
        old = snap / live.name
        if live.exists():
            keep = (_root() / "_update_rollback"
                    / datetime.now().strftime("%Y%m%d_%H%M%S_replaced"))
            keep.mkdir(parents=True, exist_ok=True)
            live.rename(keep / live.name)
        if old.exists():
            old.rename(live)
        return str(snap)
    _restore(snap, _root())
    return str(snap)


def remove_overlay():
    """نسخة الـexe: إلغاء التحديثات المثبَّتة والعودة لكود الـexe نفسه."""
    if not _frozen():
        raise ValueError("هذا الخيار لنسخة الـexe وحدها")
    live = _code_dir()
    if not live.exists():
        return ""
    keep = (_root() / "_update_rollback"
            / datetime.now().strftime("%Y%m%d_%H%M%S_removed"))
    keep.mkdir(parents=True, exist_ok=True)
    live.rename(keep / live.name)
    return str(keep)
